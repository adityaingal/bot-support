# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 OGADI — All Rights Reserved                    ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/UVRWygSpJq                    ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

"""Transparent persistent-connection pool for aiosqlite.

Every ``aiosqlite.connect()`` normally spawns a dedicated worker thread and
opens the SQLite file. This bot ran ~40-60 of those per message (get_prefix,
automod listeners, blacklist checks, ...), which dominated response latency.

``install()`` swaps ``aiosqlite.connect`` for a factory that returns a thin
proxy. The first ``await`` / ``async with`` acquires a long-lived worker
connection from a per-(database, kwargs) pool; ``close()`` (or leaving the
``async with`` block) returns it to the pool instead of destroying it.
Semantics match the original close-on-exit behaviour: any open transaction is
rolled back and mutated per-connection defaults (row_factory, ...) are
restored before the connection is reused.

Pooled connections are created through the tracking ``connect`` installed by
CodeX.py, so shutdown still closes every worker thread. ``:memory:`` databases
are never pooled (each connect must see a fresh database).
"""

import asyncio
import threading
from collections import deque

import aiosqlite

# Hard cap on simultaneous open connections per pool key. Long-lived holders
# (antinuke cogs, API DatabaseManager, ...) each pin one; the rest are reused
# round-robin by every short-lived ``async with aiosqlite.connect(...)`` block.
MAX_OPEN_PER_DB = 16

_pools_lock = threading.Lock()
_pools: dict = {}
_installed = False


def _is_healthy(conn) -> bool:
    """True while the aiosqlite worker thread and sqlite3 handle are alive."""
    try:
        return bool(conn._running) and conn._connection is not None
    except Exception:
        return False


def _poolable(database, kwargs) -> bool:
    try:
        path = database if isinstance(database, str) else str(database)
    except Exception:
        return False
    if path == ":memory:" or path.startswith("file::memory:"):
        return False
    if kwargs.get("uri") and "mode=memory" in path:
        return False
    return True


class _ConnectionPool:
    def __init__(self, factory, default_isolation):
        self._factory = factory
        self._default_isolation = default_isolation
        self._idle = deque()
        self._open = 0
        self._waiters = deque()

    async def acquire(self):
        loop = asyncio.get_running_loop()
        while True:
            with self._lock():
                while self._idle:
                    conn = self._idle.pop()
                    if _is_healthy(conn):
                        return conn
                    self._open -= 1
                if self._open < MAX_OPEN_PER_DB:
                    self._open += 1
                    create = True
                else:
                    create = False
                    fut = loop.create_future()
                    self._waiters.append((loop, fut))
            if create:
                try:
                    return await self._factory()
                except BaseException:
                    with self._lock():
                        self._open -= 1
                    raise
            try:
                await fut
            except asyncio.CancelledError:
                with self._lock():
                    self._waiters = deque(w for w in self._waiters if w[1] is not fut)
                raise

    async def release(self, conn):
        try:
            if _is_healthy(conn):
                # Mirror the old close-on-exit semantics: an abandoned
                # transaction must not leak into the next user of this
                # connection (close() would have rolled it back).
                try:
                    if conn._connection.in_transaction:
                        await conn.rollback()
                except Exception:
                    pass
                # Callers may have mutated per-connection defaults; a fresh
                # connect() would have started clean, so restore them.
                try:
                    if conn.row_factory is not None:
                        conn.row_factory = None
                    if conn.text_factory is not str:
                        conn.text_factory = str
                    if conn.isolation_level != self._default_isolation:
                        conn.isolation_level = self._default_isolation
                except Exception:
                    pass
        finally:
            healthy = _is_healthy(conn)
            waiter_loop = waiter_fut = None
            with self._lock():
                if healthy:
                    self._idle.append(conn)
                else:
                    self._open -= 1
                while self._waiters:
                    wloop, wfut = self._waiters.popleft()
                    if wfut.done():
                        continue
                    waiter_loop, waiter_fut = wloop, wfut
                    break
            if waiter_fut is not None:
                try:
                    if waiter_loop is asyncio.get_running_loop():
                        waiter_fut.set_result(None)
                    else:
                        waiter_loop.call_soon_threadsafe(waiter_fut.set_result, None)
                except RuntimeError:
                    pass  # the waiter's loop is already closed

    def _lock(self):
        return _pools_lock


class _PooledConnection:
    """Stand-in for an aiosqlite Connection backed by a pooled connection."""

    __slots__ = ("_pool", "_real")

    def __init__(self, pool):
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_real", None)

    def _require(self):
        real = object.__getattribute__(self, "_real")
        if real is None:
            raise ValueError("Connection closed")
        return real

    def __await__(self):
        return self._acquire().__await__()

    async def _acquire(self):
        if object.__getattribute__(self, "_real") is None:
            pool = object.__getattribute__(self, "_pool")
            object.__setattr__(self, "_real", await pool.acquire())
        return self

    async def __aenter__(self):
        return await self._acquire()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._release()
        return False

    async def _release(self):
        real = object.__getattribute__(self, "_real")
        if real is not None:
            object.__setattr__(self, "_real", None)
            await object.__getattribute__(self, "_pool").release(real)

    async def close(self):
        """Return the connection to the pool (matches ``async with`` exit)."""
        await self._release()

    def __getattr__(self, name):
        return getattr(self._require(), name)

    def __setattr__(self, name, value):
        if name in ("_pool", "_real"):
            object.__setattr__(self, name, value)
            return
        setattr(self._require(), name, value)


def install(aiosqlite_module, max_open_per_db: int = MAX_OPEN_PER_DB) -> None:
    """Replace ``aiosqlite_module.connect`` with the pooled factory.

    Must be called AFTER CodeX.py's connection-tracking patch so every
    underlying worker connection is still registered for shutdown.
    """
    global _installed, MAX_OPEN_PER_DB
    if _installed:
        return
    _installed = True
    MAX_OPEN_PER_DB = max_open_per_db
    real_connect = aiosqlite_module.connect

    def _make_factory(database, iter_chunk_size, kwargs):
        async def factory():
            conn = real_connect(database, iter_chunk_size=iter_chunk_size, **kwargs)
            conn = await conn
            # Speed + reliability for every pooled connection:
            #   WAL           — readers/writers stop blocking each other, commits
            #                   no longer rewrite the whole journal (the default
            #                   rollback journal made every messages/leveling
            #                   write do a full fsync and stall the bot).
            #   NORMAL        — WAL only fsyncs on checkpoint, not per commit.
            #   busy_timeout  — wait instead of instantly raising
            #                   "database is locked" when two writers collide
            #                   (that error used to kill command replies).
            for pragma in (
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA busy_timeout=5000",
            ):
                try:
                    await conn.execute(pragma)
                except Exception:
                    pass
            return conn

        return factory

    def connect(database, *, iter_chunk_size=64, loop=None, **kwargs):
        if (
            loop is not None
            or "factory" in kwargs
            or not _poolable(database, kwargs)
        ):
            return real_connect(
                database, iter_chunk_size=iter_chunk_size, loop=loop, **kwargs
            )
        try:
            key = (str(database), iter_chunk_size, tuple(sorted(kwargs.items())))
        except TypeError:
            return real_connect(database, iter_chunk_size=iter_chunk_size, **kwargs)
        with _pools_lock:
            pool = _pools.get(key)
            if pool is None:
                pool = _ConnectionPool(
                    _make_factory(database, iter_chunk_size, kwargs),
                    kwargs.get("isolation_level", ""),
                )
                _pools[key] = pool
        return _PooledConnection(pool)

    aiosqlite_module.connect = connect
