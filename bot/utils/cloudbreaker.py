# ╔══════════════════════════════════════════════════════════════════╗
# ║   Cloudflare 1015 circuit breaker                                ║
# ║                                                                  ║
# ║   When Discord's Cloudflare edge bans the IP (Error 1015),      ║
# ║   every outbound REST call renews the ban. This breaker          ║
# ║   detects the ban and suppresses ALL outgoing Discord API        ║
# ║   calls until it expires, so the ban can lift naturally.         ║
# ╚══════════════════════════════════════════════════════════════════╝

import time

_banned_until = 0.0
_last_log = 0.0
_LOG_GAP = 300

BAN_COOLDOWN = 1800.0


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
    if _banned_until > 0 and time.time() >= _banned_until:
        _banned_until = 0.0
        print("[cloudbreaker] Ban expired — resuming Discord REST calls", flush=True)


def install() -> None:
    """Patch discord.http.HTTPClient.request with the circuit breaker."""
    import discord
    import discord.http

    _orig = discord.http.HTTPClient.request

    async def patched(self, method, url, **kwargs):
        if is_banned():
            raise CloudflareBanError(
                f"Discord REST call suppressed: Cloudflare 1015 ban active "
                f"({seconds_left():.0f}s remaining)"
            )
        try:
            result = await _orig(self, method, url, **kwargs)
        except discord.HTTPException as exc:
            status = getattr(exc, "status", None)
            body = str(getattr(exc, "text", "") or "")
            lowered = body.lower()
            if status == 429 and ("1015" in body or "<!doctype" in lowered or "<html" in lowered):
                report_ban()
            raise
        report_ok()
        return result

    discord.http.HTTPClient.request = patched
    print("[cloudbreaker] Installed Cloudflare 1015 circuit breaker", flush=True)
