# ╔══════════════════════════════════════════════════════════════════╗
# ║   KeepAlive — server-side HTTP health checker                    ║
# ║                                                                  ║
# ║   ONE asyncio task. Every KEEPALIVE_INTERVAL seconds it issues a  ║
# ║   single GET at KEEPALIVE_URL (our OWN service, never discord.com)║
# ║   and logs the outcome:                                          ║
# ║     200            -> healthy                                    ║
# ║     4xx / 5xx      -> unhealthy (404 = endpoint missing)         ║
# ║     timeout        -> unreachable                                ║
# ║     connection err -> unreachable                                ║
# ║                                                                  ║
# ║   It ONLY reports. It never restarts the bot, never opens a      ║
# ║   browser, and never exposes tokens or keys.                     ║
# ╚══════════════════════════════════════════════════════════════════╝

import asyncio
import datetime
import os
import time
from typing import Optional

from utils.http import http_client

def _resolve_keepalive_url() -> str:
    render_url = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
    url = (os.getenv("KEEPALIVE_URL") or "").strip()
    # If on Render, automatically use the actual active external URL if KEEPALIVE_URL is empty or pointing to an obsolete service
    if render_url and (not url or "bot-support-aauu" in url or "yourdomain" in url):
        return f"{render_url.rstrip('/')}/health"
    if url:
        return url
    if render_url:
        return f"{render_url.rstrip('/')}/health"
    port = os.getenv("PORT") or os.getenv("API_PORT") or "8000"
    return f"http://127.0.0.1:{port}/health"

KEEPALIVE_URL = _resolve_keepalive_url()
KEEPALIVE_SECONDS = max(10, int(os.getenv("KEEPALIVE_INTERVAL") or "600"))
KEEPALIVE_ENABLED = (os.getenv("KEEPALIVE_ENABLED") or "true").strip().lower() == "true"
KEEPALIVE_NAME = (os.getenv("KEEPALIVE_NAME") or "Support").strip()

_STATE = {
    "url": KEEPALIVE_URL,
    "name": KEEPALIVE_NAME,
    "enabled": KEEPALIVE_ENABLED,
    "interval_s": KEEPALIVE_SECONDS,
    "running": False,
    "result": None,            # healthy | unhealthy | unreachable | None
    "http_status": None,
    "response_ms": None,
    "last_checked": None,      # "HH:MM:SS"
    "last_checked_epoch": None,
    "next_check_epoch": None,
    "message": None,
}

_task: Optional[asyncio.Task] = None


def snapshot() -> dict:
    """Point-in-time view for /api/status (safe: no secrets)."""
    data = dict(_STATE)
    next_epoch = data.get("next_check_epoch")
    now = time.time()
    data["next_check_in_s"] = max(0, int(next_epoch - now)) if next_epoch else None
    return data


def _stamp() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _log(ok: bool, message: str) -> None:
    print(f"[{_stamp()}] {'✓' if ok else '✖'} KeepAlive: {message}", flush=True)


async def check_once() -> str:
    """Perform exactly one health request, record + log the outcome."""
    _STATE["last_checked"] = _stamp()
    _STATE["last_checked_epoch"] = time.time()
    _STATE["next_check_epoch"] = time.time() + KEEPALIVE_SECONDS

    status, reason, _body, elapsed_ms = await http_client.get(KEEPALIVE_URL)
    _STATE["http_status"] = status
    _STATE["response_ms"] = elapsed_ms

    if status is None:
        _STATE.update(result="unreachable", message=f"connection failed: {reason}")
        _log(False, f"connection failed ({reason}) — {KEEPALIVE_NAME} is unreachable ({elapsed_ms}ms)")
        return "unreachable"

    if status == 200:
        _STATE.update(result="healthy", message="200 OK")
        _log(True, f"200 OK — {KEEPALIVE_NAME} is reachable ({elapsed_ms}ms)")
        return "healthy"

    if status == 404:
        _STATE.update(result="unhealthy", message="404 Not Found")
        _log(False, f"404 Not Found — {KEEPALIVE_NAME} is unreachable ({elapsed_ms}ms)")
        return "unhealthy"

    _STATE.update(result="unhealthy", message=f"{status} {reason or ''}".strip())
    _log(False, f"{status} {reason or ''} — {KEEPALIVE_NAME} is unreachable ({elapsed_ms}ms)")
    return "unhealthy"


async def _run() -> None:
    """The single KeepAlive loop: wait one interval, check, wait, check…"""
    _STATE["running"] = True
    try:
        await http_client.start()
        _log(True, f"pinging {KEEPALIVE_URL} every {KEEPALIVE_SECONDS}s")
        # Flow: timer starts -> wait one interval -> first GET.
        await asyncio.sleep(KEEPALIVE_SECONDS)
        while True:
            await check_once()
            await asyncio.sleep(KEEPALIVE_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # the checker must never take the bot down
        _log(False, f"checker stopped ({type(exc).__name__})")
    finally:
        _STATE["running"] = False


def start() -> Optional[asyncio.Task]:
    """Start the checker exactly once (safe to call again after reloads)."""
    global _task
    if not KEEPALIVE_ENABLED:
        _log(False, "disabled via KEEPALIVE_ENABLED=false")
        return None
    if _task is not None and not _task.done():
        return _task
    _task = asyncio.create_task(_run(), name="support:keepalive")
    return _task


async def stop() -> None:
    """Cancel the checker cleanly during shutdown."""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    _task = None
    _STATE["running"] = False
