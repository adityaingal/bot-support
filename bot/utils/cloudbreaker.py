# ╔══════════════════════════════════════════════════════════════════╗
# ║   Discord REST circuit breaker & recovery controller             ║
# ║                                                                  ║
# ║   States:                                                        ║
# ║     NORMAL         — REST working, breaker idle                  ║
# ║     SUSPECTED_LIMIT— short route/global 429 seen (no suppression)║
# ║     EDGE_BLOCKED   — Cloudflare edge ban; REST suppressed        ║
# ║     PROBING        — a recovery probe is in flight               ║
# ║     RECOVERING     — probe succeeded, verifying normal traffic   ║
# ║     WARMING_UP     — resuming optional REST gradually            ║
# ║                                                                  ║
# ║   Only the login probe (GET /users/@me) and the background       ║
# ║   recovery probe are allowed while EDGE_BLOCKED, so the ban can  ║
# ║   expire naturally instead of being renewed by outbound traffic. ║
# ╚══════════════════════════════════════════════════════════════════╝

import os
import json
import time
import random
import asyncio

# --- Tunables (env-overridable) -------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


BAN_COOLDOWN = 300.0
# A Discord route rate-limit returns Retry-After in seconds/minutes. A
# Cloudflare EDGE block returns minutes/hours (observed 1958s, 55333s).
# Only treat a 429 at/above this wait without X-RateLimit headers as an
# edge ban worth full REST suppression.
EDGE_BAN_MIN_RETRY_AFTER = _env_float("DISCORD_EDGE_BAN_MIN_RETRY_AFTER", 600.0)
# Adaptive probe cadence while EDGE_BLOCKED:
#   remaining > LONG_BAN_PROBE_AFTER : probe every LONG_BAN_PROBE_INTERVAL
#   remaining <= that                 : probe every PROBE_INTERVAL
#   remaining < NEAR_EXPIRY          : probe every NEAR_EXPIRY_INTERVAL
LONG_BAN_PROBE_AFTER = _env_float("DISCORD_LONG_BAN_PROBE_AFTER", 900.0)
LONG_BAN_PROBE_INTERVAL = _env_float("DISCORD_LONG_BAN_PROBE_INTERVAL", 300.0)
PROBE_INTERVAL = _env_float("DISCORD_PROBE_INTERVAL", 120.0)
NEAR_EXPIRY = _env_float("DISCORD_PROBE_NEAR_EXPIRY", 120.0)
NEAR_EXPIRY_INTERVAL = _env_float("DISCORD_PROBE_NEAR_EXPIRY_INTERVAL", 30.0)
# How long RECOVERING -> WARMING_UP -> NORMAL takes after a successful probe.
WARMUP_HOLD = _env_float("DISCORD_WARMUP_HOLD", 45.0)
# Recovery probes are disabled entirely when false (manual mode).
RECOVERY_ENABLED = (os.getenv("REST_RECOVERY_ENABLED", "true").strip().lower() == "true")

# --- Module state ----------------------------------------------------------

STATE_NORMAL = "NORMAL"
STATE_SUSPECTED_LIMIT = "SUSPECTED_LIMIT"
STATE_EDGE_BLOCKED = "EDGE_BLOCKED"
STATE_PROBING = "PROBING"
STATE_RECOVERING = "RECOVERING"
STATE_WARMING_UP = "WARMING_UP"

_state = STATE_NORMAL
# Cooldown deadlines use the monotonic clock (immune to wall-clock jumps);
# wall timestamps are kept only for persistence/diagnostics.
_blocked_until_mono = 0.0
_detected_at_wall = 0.0
_last_status = None
_last_cf_ray = None
_classification = None
_retry_after = 0.0
_last_ok_wall = 0.0
_recovered_at_mono = 0.0

_probe_lock: asyncio.Lock | None = None
_probe_task: asyncio.Task | None = None
_probe_token = ""
_probing = False
_warm_task: asyncio.Task | None = None

_last_log = 0.0
_LOG_GAP = 300

_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".rest_state.json"
)

# Readable state names for logs / dashboard
STATES = (
    STATE_NORMAL, STATE_SUSPECTED_LIMIT, STATE_EDGE_BLOCKED,
    STATE_PROBING, STATE_RECOVERING, STATE_WARMING_UP,
)


class CloudflareBanError(RuntimeError):
    """Raised when a Discord REST call is suppressed due to an active edge ban."""


# --- Core state queries ----------------------------------------------------

def state() -> str:
    return _state


def is_banned() -> bool:
    return _state in (STATE_EDGE_BLOCKED, STATE_PROBING) and time.monotonic() < _blocked_until_mono


def seconds_left() -> float:
    if _state not in (STATE_EDGE_BLOCKED, STATE_PROBING):
        return 0.0
    return max(0.0, _blocked_until_mono - time.monotonic())


def snapshot() -> dict:
    """Status payload for /api/status and the dashboard. No secrets."""
    remaining = seconds_left()
    return {
        "state": _state,
        "banned": remaining > 0,
        "retry_after_s": round(_retry_after, 1) if _retry_after else None,
        "remaining_s": round(remaining, 1),
        "next_probe_in_s": round(suggested_wait(), 1) if remaining > 0 else None,
        "http_status": _last_status,
        "cf_ray": _last_cf_ray,
        "classification": _classification,
        "last_ok": _last_ok_wall or None,
    }


# --- Adaptive scheduling ---------------------------------------------------

def suggested_wait() -> float:
    """Adaptive delay until the next login/recovery probe while blocked.

    Long bans: conservative 300s probes. As the expected expiry nears,
    tighten to the configured probe interval, then to the near-expiry
    interval. Bounded jitter (±10%) is added but never pushes the wait
    below the remaining server-mandated cooldown floor of a few seconds.
    """
    remaining = seconds_left()
    if remaining <= 0:
        return 0.0
    if remaining > LONG_BAN_PROBE_AFTER:
        base = LONG_BAN_PROBE_INTERVAL
    elif remaining > NEAR_EXPIRY:
        base = PROBE_INTERVAL
    else:
        base = min(NEAR_EXPIRY_INTERVAL, max(remaining, 5.0))
    jittered = base * random.uniform(0.9, 1.1)
    # Never sleep past the end of the ban window by a large margin, and
    # never below 5s (avoid tight loops).
    return max(5.0, min(jittered, max(remaining, 5.0)))


# --- Transitions (centralized) --------------------------------------------

def _log(msg: str) -> None:
    global _last_log
    now = time.time()
    # Transitions always log; steady-state re-trips are rate-limited.
    print(f"[REST] {msg}", flush=True)
    _last_log = now


def _transition(new_state: str, *, force: bool = False) -> None:
    global _state
    if _state != new_state or force:
        _state = new_state


def report_ban(duration: float = BAN_COOLDOWN, *, status: int | None = 429,
               cf_ray: str | None = None, classification: str = "edge") -> None:
    """Trip (or extend) the edge-blocked state. Wall-clock duration only
    sets a monotonic deadline; safe against clock jumps."""
    global _blocked_until_mono, _detected_at_wall, _last_status
    global _last_cf_ray, _classification, _retry_after, _last_log
    duration = max(5.0, float(duration or BAN_COOLDOWN))
    now_mono = time.monotonic()
    now_wall = time.time()
    if duration > (_blocked_until_mono - now_mono):
        _blocked_until_mono = now_mono + duration
    _detected_at_wall = now_wall
    _last_status = status
    if cf_ray:
        _last_cf_ray = cf_ray
    _classification = classification
    _retry_after = duration
    if now_wall - _last_log >= _LOG_GAP or _state != STATE_EDGE_BLOCKED:
        _last_log = now_wall
        print(
            f"[REST] State: EDGE_BLOCKED ({classification}) — suppressing Discord "
            f"REST for {duration:.0f}s"
            + (f" | CF-RAY={cf_ray}" if cf_ray else ""),
            flush=True,
        )
    _transition(STATE_EDGE_BLOCKED)
    _persist()


def report_ok() -> None:
    """Any successful Discord REST response proves the edge is serving us
    again — clear immediately and begin the staged recovery."""
    global _blocked_until_mono, _last_ok_wall, _recovered_at_mono
    global _last_log
    if _state in (STATE_EDGE_BLOCKED, STATE_PROBING) or _blocked_until_mono > time.monotonic():
        _blocked_until_mono = 0.0
        _last_ok_wall = time.time()
        _recovered_at_mono = time.monotonic()
        _last_log = time.time()
        print("[REST] State: RECOVERING — Discord responding again", flush=True)
        _transition(STATE_RECOVERING)
        _persist()
        _schedule_warmup()


def report_suspected_limit(status: int, retry_after: float, cf_ray: str | None = None) -> None:
    """Record a short route/global 429 without suppressing anything."""
    global _last_status, _last_cf_ray, _classification, _retry_after
    _last_status = status
    if cf_ray:
        _last_cf_ray = cf_ray
    _classification = "route_limit"
    _retry_after = retry_after
    if _state == STATE_NORMAL:
        _transition(STATE_SUSPECTED_LIMIT)


def _schedule_warmup() -> None:
    """RECOVERING -> WARMING_UP -> NORMAL after a short hold. Fire-and-forget;
    falls back to NORMAL immediately when no loop is running (tests)."""
    global _warm_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _transition(STATE_NORMAL)
        return
    if _warm_task is not None and not _warm_task.done():
        return

    async def _warm():
        try:
            await asyncio.sleep(WARMUP_HOLD / 2)
            _transition(STATE_WARMING_UP)
            print("[REST] State: WARMING_UP", flush=True)
            _persist()
            await asyncio.sleep(WARMUP_HOLD / 2)
        except asyncio.CancelledError:
            pass
        finally:
            if _state in (STATE_RECOVERING, STATE_WARMING_UP):
                _transition(STATE_NORMAL)
                print("[REST] State: NORMAL", flush=True)
                _persist()

    _warm_task = loop.create_task(_warm(), name="cloudbreaker:warmup")


# --- Classification of a 429 ----------------------------------------------

def _retry_after_seconds(exc) -> float:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    raw = headers.get("Retry-After")
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(raw)
        return max(0.0, dt.timestamp() - time.time())
    except Exception:
        return 0.0


def _cf_ray(exc) -> str | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    return headers.get("CF-RAY")


def _has_rate_limit_headers(exc) -> bool:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return any(str(k).lower().startswith("x-ratelimit-") for k in headers)
    except Exception:
        return False


def _maybe_report_edge_ban(exc) -> None:
    """Classify a 429: HTML/1015 or long Retry-After WITHOUT X-RateLimit
    headers = edge ban (suppress). Anything else = normal route limit."""
    if getattr(exc, "status", None) != 429:
        return
    wait = _retry_after_seconds(exc)
    ray = _cf_ray(exc)
    body = str(getattr(exc, "text", "") or "")
    lowered = body.lower()
    looks_html = "1015" in body or "<!doctype" in lowered or "<html" in lowered
    if looks_html:
        report_ban(wait if wait > 0 else BAN_COOLDOWN,
                   status=429, cf_ray=ray, classification="cloudflare_1015")
    elif wait >= EDGE_BAN_MIN_RETRY_AFTER and not _has_rate_limit_headers(exc):
        report_ban(wait, status=429, cf_ray=ray, classification="edge_429")
    else:
        report_suspected_limit(429, wait, ray)


# --- Persistence -----------------------------------------------------------

def _persist() -> None:
    """Best-effort durable recovery metadata (never tokens/headers). On
    Render Free the filesystem is ephemeral — a miss is not an error."""
    try:
        payload = {
            "state": _state,
            "detected_at": _detected_at_wall,
            "retry_after": _retry_after,
            "next_probe_eta": _detected_at_wall + _retry_after,
            "last_http_status": _last_status,
            "last_cf_ray": _last_cf_ray,
            "classification": _classification,
            "written_at": time.time(),
        }
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, _STATE_FILE)
    except Exception:
        pass


def _load_persisted() -> None:
    """Restore an active edge-blocked window across process restarts so a
    redeploy during a ban does not immediately re-attempt login."""
    global _blocked_until_mono, _detected_at_wall, _retry_after
    global _last_status, _last_cf_ray, _classification
    try:
        if not os.path.exists(_STATE_FILE):
            return
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        detected = float(data.get("detected_at") or 0)
        retry_after = float(data.get("retry_after") or 0)
        # Stale-record guard: discard anything that should have expired
        # long ago (clock skew, old container, ...).
        if not detected or not retry_after:
            return
        remaining = (detected + retry_after) - time.time()
        if remaining <= 0 or remaining > retry_after * 1.5 + 600:
            try:
                os.remove(_STATE_FILE)
            except OSError:
                pass
            return
        _blocked_until_mono = time.monotonic() + remaining
        _detected_at_wall = detected
        _retry_after = retry_after
        _last_status = data.get("last_http_status")
        _last_cf_ray = data.get("last_cf_ray")
        _classification = data.get("classification") or "restored"
        _transition(STATE_EDGE_BLOCKED)
        print(
            f"[REST] Restored persisted ban state — {remaining:.0f}s remaining "
            f"({(_classification or '?')})",
            flush=True,
        )
    except Exception:
        pass


def _clear_persisted() -> None:
    try:
        if os.path.exists(_STATE_FILE):
            os.remove(_STATE_FILE)
    except OSError:
        pass


# --- Recovery probe loop ---------------------------------------------------

def start_probe(token: str) -> None:
    """Start the background recovery probe (call once, from on_ready).

    While EDGE_BLOCKED mid-session, no normal REST call can succeed, so
    nothing would call report_ok(). This loop probes the exempt
    users/@me route at the adaptive cadence and clears state the moment
    Discord answers, bounding outages to the probe interval instead of
    the full ban duration.
    """
    global _probe_task, _probe_token
    _probe_token = token or ""
    if not RECOVERY_ENABLED or not _probe_token:
        return
    if _probe_task is not None and not _probe_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _probe_task = loop.create_task(_probe_loop(), name="cloudbreaker:probe")
    print("[REST] Recovery probe started (adaptive interval)", flush=True)


async def _probe_loop() -> None:
    import aiohttp
    global _probing
    while True:
        await asyncio.sleep(10)
        if not is_banned() or not _probe_token:
            continue
        wait = suggested_wait()
        await asyncio.sleep(wait)
        if not is_banned():
            continue
        lock = _get_probe_lock()
        if lock.locked():
            continue  # one outstanding probe at a time
        async with lock:
            _probing = True
            _transition(STATE_PROBING)
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        "https://discord.com/api/v10/users/@me",
                        headers={"Authorization": f"Bot {_probe_token}"},
                    ) as resp:
                        if resp.status == 200:
                            report_ok()
                        else:
                            _transition(STATE_EDGE_BLOCKED)
            except asyncio.CancelledError:
                raise
            except Exception:
                if _state == STATE_PROBING:
                    _transition(STATE_EDGE_BLOCKED)
            finally:
                _probing = False


def _get_probe_lock() -> asyncio.Lock:
    global _probe_lock
    if _probe_lock is None:
        _probe_lock = asyncio.Lock()
    return _probe_lock


# --- Login concurrency guard ----------------------------------------------

_login_locked = False


def begin_login() -> bool:
    """Claim the single-login-attempt slot. False if one is in flight."""
    global _login_locked
    if _login_locked:
        return False
    _login_locked = True
    return True


def end_login() -> None:
    global _login_locked
    _login_locked = False


# --- HTTPClient patch ------------------------------------------------------

def install() -> None:
    """Patch discord.http.HTTPClient.request with the circuit breaker."""
    import discord
    import discord.http

    _orig = discord.http.HTTPClient.request

    async def patched(self, route, **kwargs):
        # Login and gateway bootstrap must never be suppressed — the bot
        # needs them to connect. Only suppress post-login REST calls.
        route_url = getattr(route, "url", "") or ""
        is_login = "users/@me" in route_url and getattr(route, "method", "") == "GET"
        if is_login:
            try:
                result = await _orig(self, route, **kwargs)
            except discord.HTTPException as exc:
                _maybe_report_edge_ban(exc)
                raise
            report_ok()
            return result
        if is_banned():
            raise CloudflareBanError(
                f"Discord REST call suppressed: {STATE_EDGE_BLOCKED} "
                f"({seconds_left():.0f}s remaining)"
            )
        try:
            result = await _orig(self, route, **kwargs)
        except discord.HTTPException as exc:
            _maybe_report_edge_ban(exc)
            raise
        report_ok()
        return result

    discord.http.HTTPClient.request = patched
    _load_persisted()
    print("[REST] Circuit breaker installed", flush=True)


# --- Test support ----------------------------------------------------------

def _reset_for_tests() -> None:
    global _state, _blocked_until_mono, _detected_at_wall, _last_status
    global _last_cf_ray, _classification, _retry_after, _last_ok_wall
    global _recovered_at_mono, _probing, _login_locked, _probe_token
    global _probe_task, _warm_task, _probe_lock, _last_log
    _state = STATE_NORMAL
    _blocked_until_mono = 0.0
    _detected_at_wall = 0.0
    _last_status = None
    _last_cf_ray = None
    _classification = None
    _retry_after = 0.0
    _last_ok_wall = 0.0
    _recovered_at_mono = 0.0
    _probing = False
    _login_locked = False
    _probe_token = ""
    _probe_task = None
    _warm_task = None
    _probe_lock = None
    _last_log = 0.0
