"""Simple TTL cache for hot-path DB reads.

Every on_message listener hits SQLite per guild per message. These values
(prefix, ignore lists, blacklist, automod config) change rarely (admin runs
a command) but are read constantly. A short TTL makes them effectively free.
"""
import time
import asyncio

_DEFAULT_TTL = 30.0
_store: dict = {}
_expiry: dict = {}
_locks: dict = {}


def _key(namespace: str, *parts) -> str:
    return namespace + ":" + ":".join(str(p) for p in parts)


async def cached(namespace: str, *parts, ttl: float = _DEFAULT_TTL):
    """Return cached value or None if absent/expired."""
    k = _key(namespace, *parts)
    exp = _expiry.get(k)
    if exp is not None and time.monotonic() < exp:
        return _store.get(k)
    return None


def set_cached(namespace: str, value, *parts, ttl: float = _DEFAULT_TTL):
    k = _key(namespace, *parts)
    _store[k] = value
    _expiry[k] = time.monotonic() + ttl


def invalidate(namespace: str = None, *parts):
    """Invalidate one key, all keys for a namespace, or everything."""
    if parts:
        k = _key(namespace, *parts)
        _store.pop(k, None)
        _expiry.pop(k, None)
    elif namespace:
        prefix = namespace + ":"
        for k in list(_store):
            if k.startswith(prefix):
                _store.pop(k, None)
                _expiry.pop(k, None)
    else:
        _store.clear()
        _expiry.clear()


async def cached_or_fetch(namespace: str, fetch_fn, *parts, ttl: float = _DEFAULT_TTL):
    """Cache-aside: return cached value or await fetch_fn() and cache it.

    A per-key asyncio.Lock prevents a thundering herd of identical queries
    when many messages arrive at once before the first fetch resolves.
    """
    k = _key(namespace, *parts)
    exp = _expiry.get(k)
    if exp is not None and time.monotonic() < exp:
        return _store.get(k)

    lock = _locks.get(k)
    if lock is None:
        lock = _locks[k] = asyncio.Lock()

    async with lock:
        # double-check after acquiring lock
        exp = _expiry.get(k)
        if exp is not None and time.monotonic() < exp:
            return _store.get(k)
        value = await fetch_fn()
        _store[k] = value
        _expiry[k] = time.monotonic() + ttl
        return value
