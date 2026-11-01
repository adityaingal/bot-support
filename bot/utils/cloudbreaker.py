# ╔══════════════════════════════════════════════════════════════════╗
# ║   Cloudflare 1015 circuit breaker                                ║
# ║                                                                  ║
# ║   When Discord's Cloudflare edge bans the IP (Error 1015),      ║
# ║   every outbound REST call renews the ban. This breaker          ║
# ║   detects the ban and suppresses ALL outgoing Discord API        ║
# ║   calls until it expires, so the ban can lift naturally.         ║
# ╚══════════════════════════════════════════════════════════════════╝

import time
import asyncio

_banned_until = 0.0
_last_log = 0.0
_LOG_GAP = 300

BAN_COOLDOWN = 300.0
# Cloudflare edge bans come as JSON 429s with a huge Retry-After (observed
# 1958s, 55333s). Normal Discord route rate limits stay under a few minutes,
# so only treat a 429 as an edge ban when Retry-After is at least this long.
EDGE_BAN_MIN_RETRY_AFTER = 600.0

_probe_task: "asyncio.Task | None" = None
_probe_token: str = ""


class CloudflareBanError(RuntimeError):
    """Raised when a Discord REST call is suppressed due to an active Cloudflare 1015 ban."""


def is_banned() -> bool:
    return time.time() < _banned_until


def seconds_left() -> float:
    return max(0.0, _banned_until - time.time())


def report_ban(duration: float = BAN_COOLDOWN) -> None:
    global _banned_until, _last_log
    now = time.time()
    if duration > (_banned_until - now):
        _banned_until = now + duration
    if now - _last_log >= _LOG_GAP:
        _last_log = now
        print(
            f"[cloudbreaker] Cloudflare ban detected — suppressing Discord REST "
            f"calls for {duration:.0f}s",
            flush=True,
        )


def report_ok() -> None:
    global _banned_until
    # Any successful Discord REST response proves the edge is serving us
    # again — clear immediately, even if the ban timer hasn't fully elapsed.
    if _banned_until > 0:
        _banned_until = 0.0
        print("[cloudbreaker] Discord responding again — resuming REST calls", flush=True)


def start_probe(token: str) -> None:
    """Start the mid-session recovery probe (call once, from on_ready).

    While the breaker is tripped mid-session, no normal REST call can
    succeed — so nothing would ever call report_ok() and commands would
    stay dead for the full ban duration. This loop probes the exempt
    users/@me route every 30s and clears the state the moment Discord
    answers, bounding the outage to ~30-60s instead of tens of minutes.
    """
    global _probe_task, _probe_token
    _probe_token = token
    if _probe_task is not None and not _probe_task.done():
        return
    _probe_task = asyncio.create_task(_probe_loop(), name="cloudbreaker:probe")
    print("[cloudbreaker] Mid-session recovery probe started (30s interval)", flush=True)


async def _probe_loop() -> None:
    import aiohttp
    while True:
        await asyncio.sleep(30)
        if not is_banned() or not _probe_token:
            continue
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {_probe_token}"},
                ) as resp:
                    if resp.status == 200:
                        report_ok()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


def _retry_after_seconds(exc) -> float:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    raw = headers.get("Retry-After")
    if not raw:
        return 0.0
    try:
        value = float(raw)
        return max(0.0, value)
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(raw)
        return max(0.0, dt.timestamp() - time.time())
    except Exception:
        return 0.0


def _maybe_report_edge_ban(exc) -> None:
    """Trip the breaker on Cloudflare edge 429s (HTML body or huge Retry-After)."""
    if getattr(exc, "status", None) != 429:
        return
    wait = _retry_after_seconds(exc)
    body = str(getattr(exc, "text", "") or "")
    lowered = body.lower()
    looks_html = "1015" in body or "<!doctype" in lowered or "<html" in lowered
    if looks_html or (wait >= EDGE_BAN_MIN_RETRY_AFTER):
        report_ban(wait if wait > 0 else BAN_COOLDOWN)


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
            # Login probe must never be suppressed — it's how we detect
            # that the ban has lifted. Its success also clears the state.
            try:
                result = await _orig(self, route, **kwargs)
            except discord.HTTPException as exc:
                _maybe_report_edge_ban(exc)
                raise
            report_ok()
            return result
        if is_banned():
            raise CloudflareBanError(
                f"Discord REST call suppressed: Cloudflare ban active "
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
    print("[cloudbreaker] Installed Cloudflare 1015 circuit breaker", flush=True)
