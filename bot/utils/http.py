# ╔══════════════════════════════════════════════════════════════════╗
# ║   Shared HTTP client — ONE session, safe retries, 429 handling   ║
# ║                                                                  ║
# ║   Rules enforced here:                                           ║
# ║     • one ClientSession for the whole process (no per-request    ║
# ║       sessions)                                                  ║
# ║     • connect timeout 10s, total timeout 30s                     ║
# ║     • max 3 attempts, exponential backoff + jitter               ║
# ║     • HTTP 429 honours Retry-After, then ONE retry, then backs   ║
# ║       off and gives up (never an infinite loop)                  ║
# ║     • rate-limit events are logged once, not spammed             ║
# ║     • extra sessions registered by cogs are closed on shutdown   ║
# ╚══════════════════════════════════════════════════════════════════╝

import asyncio
import random
import time
from typing import List, Optional, Tuple

import aiohttp

CONNECT_TIMEOUT = 10
TOTAL_TIMEOUT = 30
MAX_RETRIES = 3
RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
_RATE_LIMIT_LOG_GAP = 60  # seconds between "rate limited" log lines

_last_discord_log: dict = {}


def describe_http_failure(exc: BaseException) -> str:
    """One-line failure description for logs.

    Never dumps the exception's payload: Discord/Cloudflare 429 bodies are
    HTML pages and must not end up in Render's log stream.
    """
    status = getattr(exc, "status", None)
    text = str(exc)
    lowered = text.lower()
    cloudflare = "1015" in text or "cloudflare" in lowered
    if status is not None:
        label = "429 rate limited" if status == 429 else f"HTTP {status}"
        if cloudflare:
            return f"{label} / cloudflare block ({type(exc).__name__}, body suppressed)"
        return f"{label} ({type(exc).__name__}, body suppressed)"
    if "<html" in lowered or "<!doctype" in lowered:
        return f"{type(exc).__name__} (html body suppressed)"
    snippet = " ".join(text.split())
    return f"{type(exc).__name__}: {snippet[:160]}"


def log_discord_once(key: str, message: str, gap: float = _RATE_LIMIT_LOG_GAP) -> None:
    """Print [DiscordHTTP] <message> at most once per key per gap seconds."""
    now = time.time()
    if now - _last_discord_log.get(key, 0.0) >= gap:
        _last_discord_log[key] = now
        print(f"[DiscordHTTP] {message}", flush=True)


class HTTPClient:
    """Process-wide HTTP client (see module docstring for the rules)."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._foreign: List[aiohttp.ClientSession] = []
        self._lock = asyncio.Lock()
        self._last_rate_limit_log = 0.0

    @property
    def session(self) -> Optional[aiohttp.ClientSession]:
        return self._session

    async def start(self) -> aiohttp.ClientSession:
        """Create the shared session once (safe to call repeatedly)."""
        async with self._lock:
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=TOTAL_TIMEOUT,
                                                connect=CONNECT_TIMEOUT)
                # Brotli is advertised by default, but the installed `Brotli`
                # package's Decompressor only accepts a single argument while
                # aiohttp passes max_length — every br response then blows up
                # with ClientPayloadError. Stick to gzip/deflate.
                self._session = aiohttp.ClientSession(
                    timeout=timeout,
                    headers={"Accept-Encoding": "gzip, deflate"},
                )
            return self._session

    def register(self, session: Optional[aiohttp.ClientSession]) -> None:
        """Track a long-lived session created elsewhere so shutdown closes it."""
        if session is not None and session not in self._foreign:
            self._foreign.append(session)

    def _log_rate_limit(self, message: str) -> None:
        now = time.time()
        if now - self._last_rate_limit_log >= _RATE_LIMIT_LOG_GAP:
            self._last_rate_limit_log = now
            print(f"[HTTP] {message}", flush=True)

    @staticmethod
    def _retry_after(response: aiohttp.ClientResponse) -> float:
        header = response.headers.get("Retry-After")
        try:
            if header is not None:
                return max(0.0, float(header))
        except (TypeError, ValueError):
            pass
        return 5.0

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        data: Optional[object] = None,
        max_retries: int = MAX_RETRIES,
    ) -> Tuple[Optional[int], Optional[str], bytes, int]:
        """Perform an HTTP request with bounded, rate-limit-aware retries.

        Returns ``(status, reason, body, elapsed_ms)``. ``status`` is ``None``
        only when every attempt failed at transport level (timeout/DNS/…).
        """
        session = await self.start()
        attempts = max(1, min(max_retries, MAX_RETRIES))
        started = time.perf_counter()

        for attempt in range(attempts):
            try:
                async with session.request(
                    method, url, headers=headers, params=params, json=json, data=data
                ) as response:
                    elapsed_ms = int((time.perf_counter() - started) * 1000)

                    if response.status == 429 and attempt < attempts - 1:
                        wait = self._retry_after(response)
                        self._log_rate_limit(
                            f"Discord web request rate limited — Retry-After: {wait:g}s"
                        )
                        await asyncio.sleep(wait + random.uniform(0.1, 1.0))
                        continue

                    if response.status in RETRYABLE_STATUSES and attempt < attempts - 1:
                        backoff = min(2 ** attempt, 30) + random.uniform(0.2, 1.5)
                        self._log_rate_limit(
                            f"{response.status} {response.reason or ''} from {url} — "
                            f"backing off {backoff:.1f}s"
                        )
                        await asyncio.sleep(backoff)
                        continue

                    body = await response.read()
                    return (response.status, response.reason, body, elapsed_ms)

            except asyncio.TimeoutError:
                if attempt < attempts - 1:
                    await asyncio.sleep(min(2 ** attempt, 30) + random.uniform(0.2, 1.5))
                    continue
                self._log_rate_limit(f"request timed out — {url}")
                return (None, "timeout", b"", int((time.perf_counter() - started) * 1000))

            except aiohttp.ClientError as exc:
                if attempt < attempts - 1:
                    await asyncio.sleep(min(2 ** attempt, 30) + random.uniform(0.2, 1.5))
                    continue
                self._log_rate_limit(f"connection failed ({type(exc).__name__}) — {url}")
                return (None, type(exc).__name__, b"", int((time.perf_counter() - started) * 1000))

        return (None, "retries_exhausted", b"", int((time.perf_counter() - started) * 1000))

    async def get(self, url: str, **kwargs) -> Tuple[Optional[int], Optional[str], bytes, int]:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> Tuple[Optional[int], Optional[str], bytes, int]:
        return await self.request("POST", url, **kwargs)

    async def close(self) -> None:
        """Close the shared session and every session registered by cogs."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            print("[HTTP] Client session closed", flush=True)
        self._session = None

        for session in list(self._foreign):
            try:
                if session is not None and not session.closed:
                    await session.close()
                    print("[HTTP] Client session closed", flush=True)
            except Exception:
                pass
        self._foreign.clear()


http_client = HTTPClient()
