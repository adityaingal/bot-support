"""Paid-plan storage for the bot (per guild).

A plan unlocks plan-only features. Plans are managed by the bot developer
with >plan add / >plan remove and expire automatically.
"""

from __future__ import annotations

import aiosqlite
from datetime import datetime, timedelta, timezone

DB_PATH = "db/plans.db"


async def _init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS plans (
                   guild_id TEXT PRIMARY KEY,
                   plan TEXT NOT NULL,
                   expires_at TEXT NOT NULL,
                   added_by TEXT,
                   created_at TEXT NOT NULL
               )"""
        )
        await db.commit()


async def get_plan(guild_id: int) -> dict | None:
    """Return the active plan for a guild, or None (expired plans are purged)."""
    await _init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT plan, expires_at, added_by FROM plans WHERE guild_id = ?",
            (str(guild_id),),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    plan, expires_at, added_by = row
    expires = datetime.fromisoformat(expires_at)
    if expires <= datetime.now(timezone.utc):
        await remove_plan(guild_id)
        return None
    return {"plan": plan, "expires": expires, "added_by": added_by}


async def add_plan(guild_id: int, plan: str, days: int, added_by: int) -> datetime:
    await _init_db()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=max(1, days))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO plans (guild_id, plan, expires_at, added_by, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                   plan = excluded.plan,
                   expires_at = excluded.expires_at,
                   added_by = excluded.added_by,
                   created_at = excluded.created_at""",
            (str(guild_id), plan, expires.isoformat(), str(added_by), now.isoformat()),
        )
        await db.commit()
    return expires


async def remove_plan(guild_id: int) -> bool:
    await _init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM plans WHERE guild_id = ?", (str(guild_id),))
        await db.commit()
        return cursor.rowcount > 0


async def list_plans() -> list[dict]:
    await _init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT guild_id, plan, expires_at, added_by FROM plans ORDER BY expires_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
    now = datetime.now(timezone.utc)
    plans = []
    for guild_id, plan, expires_at, added_by in rows:
        expires = datetime.fromisoformat(expires_at)
        plans.append({
            "guild_id": int(guild_id),
            "plan": plan,
            "expires": expires,
            "active": expires > now,
            "added_by": added_by,
        })
    return plans
