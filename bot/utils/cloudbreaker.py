# ╔══════════════════════════════════════════════════════════════════╗
# ║   Discord REST circuit breaker & recovery controller             ║
# ║                                                                  ║
# ║   Lifecycle / REST states:                                       ║
# ║     STARTING      — process booting, before first login attempt  ║
# ║     CONNECTING    — client.start() in flight                     ║
# ║     CONNECTED     — gateway up, REST healthy                     ║
# ║     RATE_LIMITED  — short route/global 429 (no REST suppression) ║
# ║     EDGE_BLOCKED  — Cloudflare edge ban; REST suppressed         ║
# ║     RECOVERING    — probe succeeded, verifying normal traffic    ║
# ║     DEGRADED      — running with a known problem (e.g. DB)       ║
# ║     FAILED        — fatal login error (bad token/intents)        ║
# ║                                                                  ║
# ║   Cooldown rules:                                                ║
# ║     • Retry-After is read from BOTH the header AND the JSON      ║
# ║       body; the longest valid value wins.                        ║
# ║     • Deadlines use the monotonic clock (immune to wall jumps).  ║
# ║     • While EDGE_BLOCKED there are NO identity probes: the       ║
# ║       login loop / probe loop sleep until the cooldown expires,  ║
# ║       then make ONE controlled recovery attempt. Mid-ban polls  ║
# ║       renew the Cloudflare block (production bug this replaces). ║
# ║     • A second 429 updates the cooldown (extend-only).           ║
# ║   Only the login probe (GET /users/@me) is allowed while         ║
# ║   EDGE_BLOCKED, so the ban can expire naturally.                 ║
# ╚══════════════════════════════════════════════════════════════════╝

import os
import json
import time
import asyncio

# --- Tunables (env-overridable) -------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


BAN_COOLDOWN = 300.0
# A Discord route rate-limit returns Retry-After in seconds. A Cloudflare
# EDGE block returns minutes/hours (observed 1958s, 55333s). Only treat a
# 429 at/above this wait without X-RateLimit headers as an edge ban
# worth full REST suppression.
EDGE_BAN_MIN_RETRY_AFTER = _env_float("DISCORD_EDGE_BAN_MIN_RETRY_AFTER", 600.0)
# Hard ceiling for honouring a 429's Retry-After (~48h; observed max 55333s).
RETRY_AFTER_CAP = 172800.0
# How long RECOVERING -> CONNECTED takes after a successful probe.
WARMUP_HOLD = _env_float("DISCORD_WARMUP_HOLD", 45.0)
# Recovery probes are disabled entirely when false (manual mode).
RECOVERY_ENABLED = (os.getenv("REST_RECOVERY_ENABLED", "true").strip().lower() == "true")
# Minimum gap between recovery probes even after failures (anti-storm).
PROBE_MIN_GAP = _env_float("DISCORD_PROBE_MIN_GAP", 120.0)

# --- Module state ----------------------------------------------------------

STATE_STARTING = "STARTING"
STATE_CONNECTING = "CONNECTING"
STATE_CONNECTED = "CONNECTED"
STATE_RATE_LIMITED = "RATE_LIMITED"
STATE_EDGE_BLOCKED = "EDGE_BLOCKED"
STATE_RECOVERING = "RECOVERING"
STATE_DEGRADED = "DEGRADED"
STATE_FAILED = "FAILED"

# Back-compat aliases (older logs, tests, dashboard caches).
STATE_NORMAL = STATE_CONNECTED
STATE_SUSPECTED_LIMIT = STATE_RATE_LIMITED
STATE_PROBING = STATE_EDGE_BLOCKED      # probing is EDGE_BLOCKED + _probing flag
STATE_WARMING_UP = STATE_RECOVERING

_state = STATE_STARTING
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
_last_detail = ""
_last_body_kind = None

_probe_lock: asyncio.Lock | None = None
_probe_task: asyncio.Task | None = None
_probe_token = ""
_probing = False
_warm_task: asyncio.Task | None = None
_next_probe_mono = 0.0

_last_log = 0.0
_LOG_GAP = 300

_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".rest_state.json"
)

STATES = (
    STATE_STARTING, STATE_CONNECTING, STATE_CONNECTED, STATE_RATE_LIMITED,
    STATE_EDGE_BLOCKED, STATE_RECOVERING, STATE_DEGRADED, STATE_FAILED,
)


class CloudflareBanError(RuntimeError):
    """Raised when a Discord REST call is suppressed due to an active edge ban."""


# --- Core state queries ----------------------------------------------------

def state() -> str:
    return _state


def is_banned() -> bool:
    return _state == STATE_EDGE_BLOCKED and time.monotonic() < _blocked_until_mono


def seconds_left() -> float:
    if _state != STATE_EDGE_BLOCKED:
        return 0.0
    return max(0.0, _blocked_until_mono - time.monotonic())


def next_attempt_utc() -> str | None:
    """Wall-clock UTC time of the next permitted login/recovery attempt."""
    remaining = seconds_left()
    if remaining <= 0:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(time.time() + remaining))


def snapshot() -> dict:
    """Status payload for /api/status and the dashboard. No secrets."""
    remaining = seconds_left()
    return {
        "state": _state,
        "banned": remaining > 0,
        "retry_after_s": round(_retry_after, 1) if _retry_after else None,
        "remaining_s": round(remaining, 1),
        "cooldown_remaining_s": round(remaining, 1),
        "next_attempt_utc": next_attempt_utc(),
        "http_status": _last_status,
        "cf_ray": _last_cf_ray,
        "classification": _classification,
        "last_ok": _last_ok_wall or None,
        "probing": _probing,
        "login_in_flight": _login_locked,
        "detail": _last_detail or None,
        "body_kind": _last_body_kind,
    }


# --- Adaptive scheduling ---------------------------------------------------

def suggested_wait() -> float:
    """Delay until the next login/recovery attempt while an edge ban is active.

    Honours the FULL server-mandated cooldown: we sleep until (almost) the
    expiry, then make ONE controlled attempt. Polling login mid-ban renews
    the Cloudflare block — this is the production bug the old 60s/300s
    polling cadence caused.
    """
    remaining = seconds_left()
    if remaining <= 0:
        return 0.0
    # Wake ~1s before expiry so the request lands right at the boundary.
    return max(1.0, remaining - 1.0)


# --- Transitions (centralized) --------------------------------------------

def _log(msg: str) -> None:
    global _last_log
    now = time.time()
    print(f"[REST] {msg}", flush=True)
    _last_log = now


def _transition(new_state: str, *, force: bool = False) -> None:
    global _state
    if _state != new_state or force:
        _state = new_state


def report_starting() -> None:
    _transition(STATE_STARTING)


def report_connecting() -> None:
    _transition(STATE_CONNECTING)


def report_connected() -> None:
    """Gateway ready. Never overrides an active edge ban (REST health is
    tracked separately). Releases the login slot — the login finished."""
    end_login()
    if is_banned():
        return
    if _state != STATE_CONNECTED:
        _transition(STATE_CONNECTED)


def report_failed(detail: str = "") -> None:
    global _last_detail
    _last_detail = detail[:200]
    _transition(STATE_FAILED)
    _log(f"State: FAILED{_last_detail and f' — {_last_detail}' or ''}")


def report_degraded(detail: str = "") -> None:
    """Running with a known problem (e.g. database degraded mode). Never
    overrides an active edge ban or a FAILED verdict."""
    global _last_detail
    if is_banned() or _state == STATE_FAILED:
        return
    _last_detail = detail[:200]
    _transition(STATE_DEGRADED)
    _log(f"State: DEGRADED{_last_detail and f' — {_last_detail}' or ''}")


def report_ban(duration: float = BAN_COOLDOWN, *, status: int | None = 429,
               cf_ray: str | None = None, classification: str = "edge") -> None:
    """Trip (or extend — only forward) the edge-blocked state. Wall-clock
    duration only sets a monotonic deadline; safe against clock jumps."""
    global _blocked_until_mono, _detected_at_wall, _last_status
    global _last_cf_ray, _classification, _retry_after, _last_log
    duration = min(max(5.0, float(duration or BAN_COOLDOWN)), RETRY_AFTER_CAP)
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
    remaining_now = max(0.0, _blocked_until_mono - now_mono)
    if now_wall - _last_log >= _LOG_GAP or _state != STATE_EDGE_BLOCKED:
        _last_log = now_wall
        print(
            f"[REST] State: EDGE_BLOCKED ({classification}) — suppressing Discord "
            f"REST for {remaining_now:.0f}s; next permitted attempt "
            f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(now_wall + remaining_now))}"
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
    if _state == STATE_EDGE_BLOCKED or _blocked_until_mono > time.monotonic():
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
    if _state in (STATE_CONNECTED, STATE_STARTING, STATE_CONNECTING):
        _transition(STATE_RATE_LIMITED)


def _schedule_warmup() -> None:
    """RECOVERING -> CONNECTED after a short hold. Fire-and-forget;
    falls back to CONNECTED immediately when no loop is running (tests)."""
    global _warm_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _transition(STATE_CONNECTED)
        return
    if _warm_task is not None and not _warm_task.done():
        return

    async def _warm():
        try:
            await asyncio.sleep(WARMUP_HOLD)
        except asyncio.CancelledError:
            pass
        finally:
            if _state in (STATE_RECOVERING,):
                _transition(STATE_CONNECTED)
                print("[REST] State: CONNECTED", flush=True)
                _persist()

    _warm_task = loop.create_task(_warm(), name="cloudbreaker:warmup")


# --- Retry-After parsing (header + JSON body) ------------------------------

def _header_retry_after(exc) -> float:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    return _ra_from_headers(headers)


def _ra_from_headers(headers) -> float:
    try:
        raw = headers.get("Retry-After")
    except Exception:
        return 0.0
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


def _json_retry_after(exc) -> float:
    """Discord 429 JSON bodies carry {"retry_after": N} — parse it too."""
    body = getattr(exc, "text", "") or ""
    if not body or body.lstrip()[:1] == "<":  # empty or HTML — nothing to parse
        return 0.0
    try:
        data = json.loads(body)
    except Exception:
        return 0.0
    if not isinstance(data, dict):
        return 0.0
    try:
        return max(0.0, float(data.get("retry_after") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def parse_retry_after(exc) -> float:
    """Longest applicable cooldown from BOTH the Retry-After header and the
    JSON body. Malformed values yield 0 (never raise)."""
    return max(_header_retry_after(exc), _json_retry_after(exc))


def _cf_ray(exc) -> str | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return headers.get("CF-RAY")
    except Exception:
        return None


def _has_rate_limit_headers(exc) -> bool:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return any(str(k).lower().startswith("x-ratelimit-") for k in headers)
    except Exception:
        return False


def _body_kind_of(exc) -> str:
    """Sanitized classification of a 429's body: 'html', 'json', 'empty'
    or 'other'. Used to tell Cloudflare edge pages apart from Discord API
    JSON rate-limit responses. Never logs body content."""
    body = getattr(exc, "text", "") or ""
    if not body:
        return "empty"
    stripped = body.lstrip()
    if stripped[:1] == "<":
        return "html"
    try:
        json.loads(body)
        return "json"
    except Exception:
        return "other"


def _maybe_report_edge_ban(exc) -> None:
    """Classify a 429 and update breaker state.

    Distinguishes (using headers + body, never assuming every 429 is a
    Cloudflare ban):
      • HTML/1015 body           -> cloudflare_1015 edge ban (suppress)
      • JSON "global": true      -> global_limit (record, no suppression)
      • X-RateLimit-* headers    -> route_limit (record, no suppression)
      • long Retry-After w/o RL  -> edge_429 ban (suppress)
      • CF-RAY, no RL, short RA  -> cf_unclassified (record, no suppression)
    """
    global _last_body_kind
    if getattr(exc, "status", None) != 429:
        return
    wait = parse_retry_after(exc)
    ray = _cf_ray(exc)
    body = str(getattr(exc, "text", "") or "")
    lowered = body.lower()
    _last_body_kind = _body_kind_of(exc)
    looks_html = "1015" in body or "<!doctype" in lowered or "<html" in lowered
    if looks_html:
        report_ban(wait if wait > 0 else BAN_COOLDOWN,
                   status=429, cf_ray=ray, classification="cloudflare_1015")
        return
    if _has_rate_limit_headers(exc):
        report_suspected_limit(429, wait, ray)
        return
    # No X-RateLimit headers at all: could be global, shared or edge.
    if _last_body_kind == "json":
        try:
            data = json.loads(body)
            if isinstance(data, dict) and data.get("global"):
                report_suspected_limit(429, wait, ray)
                _set_classification("global_limit")
                return
        except Exception:
            pass
    if wait >= EDGE_BAN_MIN_RETRY_AFTER:
        report_ban(wait, status=429, cf_ray=ray, classification="edge_429")
    else:
        # Short/absent Retry-After without rate-limit headers: ambiguous.
        # Record it (dashboard/logs) but do not suppress REST.
        report_suspected_limit(429, wait, ray)
        _set_classification("cf_unclassified" if ray else "route_limit")


def _set_classification(value: str) -> None:
    global _classification
    _classification = value


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
            f"[REST] Restored persisted ban state — {remaining:.0f}s remaining, "
            f"next permitted attempt {next_attempt_utc()} ({_classification})",
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
    nothing would call report_ok(). This loop sleeps out the FULL cooldown,
    then makes ONE controlled users/@me probe: 200 clears state, 429
    updates the cooldown safely. No mid-ban probes — they renew the block.
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
    print("[REST] Recovery probe started (sleeps out full cooldowns)", flush=True)


async def _probe_loop() -> None:
    import aiohttp
    global _probing, _next_probe_mono
    while True:
        await asyncio.sleep(5)
        if not _probe_token or not RECOVERY_ENABLED:
            continue
        if is_banned():
            # NO probes during an active cooldown: sleep until it expires.
            await asyncio.sleep(max(1.0, seconds_left()))
            continue
        now = time.monotonic()
        if now < _next_probe_mono:
            continue
        # Cooldown expired (or none): ONE controlled recovery probe.
        lock = _get_probe_lock()
        if lock.locked():
            continue  # one outstanding probe at a time
        async with lock:
            _probing = True
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        "https://discord.com/api/v10/users/@me",
                        headers={"Authorization": f"Bot {_probe_token}"},
                    ) as resp:
                        if resp.status == 200:
                            report_ok()
                        elif resp.status == 429:
                            # Another 429: update the cooldown safely and
                            # wait it out — no further probes until expiry.
                            try:
                                wait = _ra_from_headers(resp.headers)
                                if wait <= 0:
                                    data = json.loads(await resp.text())
                                    if isinstance(data, dict):
                                        wait = max(0.0, float(data.get("retry_after") or 0.0))
                            except Exception:
                                wait = 0.0
                            report_ban(wait if wait > 0 else BAN_COOLDOWN,
                                       status=429,
                                       cf_ray=resp.headers.get("CF-RAY"),
                                       classification="edge_429")
                        else:
                            # Transient failure (5xx etc.): back off before
                            # the next attempt instead of storming.
                            _next_probe_mono = time.monotonic() + PROBE_MIN_GAP
            except asyncio.CancelledError:
                raise
            except Exception:
                _next_probe_mono = time.monotonic() + PROBE_MIN_GAP
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
    global _probe_task, _warm_task, _probe_lock, _last_log, _last_detail
    global _next_probe_mono, _last_body_kind
    _state = STATE_CONNECTED
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
    _last_detail = ""
    _next_probe_mono = 0.0
    _last_body_kind = None
