"""Cached automod DB reads.

All 6 automod cogs (antilink, anticaps, anti_invites, anti_mass_mention,
anti_emoji_spam, antispam) ran 4 identical uncached SELECTs on EVERY guild
message. These wrappers cut that to ~0 queries per message via a 30s TTL.
"""
import aiosqlite
from utils.cache import cached_or_fetch

_DB = "db/automod.db"


async def is_automod_enabled(guild_id: int) -> bool:
    async def _fetch():
        async with aiosqlite.connect(_DB) as db:
            cursor = await db.execute("SELECT enabled FROM automod WHERE guild_id = ?", (guild_id,))
            result = await cursor.fetchone()
            return result is not None and result[0] == 1
    return await cached_or_fetch("am_enabled", _fetch, guild_id, ttl=30.0)


async def is_module_enabled(guild_id: int, event: str) -> bool:
    async def _fetch():
        async with aiosqlite.connect(_DB) as db:
            cursor = await db.execute(
                "SELECT punishment FROM automod_punishments WHERE guild_id = ? AND event = ?",
                (guild_id, event),
            )
            result = await cursor.fetchone()
            return result is not None
    return await cached_or_fetch("am_module", _fetch, guild_id, event, ttl=30.0)


async def get_ignored_channels(guild_id: int) -> list:
    async def _fetch():
        async with aiosqlite.connect(_DB) as db:
            cursor = await db.execute(
                "SELECT id FROM automod_ignored WHERE guild_id = ? AND type = 'channel'",
                (guild_id,),
            )
            return [row[0] for row in await cursor.fetchall()]
    return await cached_or_fetch("am_ich", _fetch, guild_id, ttl=30.0)


async def get_ignored_roles(guild_id: int) -> list:
    async def _fetch():
        async with aiosqlite.connect(_DB) as db:
            cursor = await db.execute(
                "SELECT id FROM automod_ignored WHERE guild_id = ? AND type = 'role'",
                (guild_id,),
            )
            return [row[0] for row in await cursor.fetchall()]
    return await cached_or_fetch("am_iro", _fetch, guild_id, ttl=30.0)


async def get_punishment(guild_id: int, event: str):
    async def _fetch():
        async with aiosqlite.connect(_DB) as db:
            cursor = await db.execute(
                "SELECT punishment FROM automod_punishments WHERE guild_id = ? AND event = ?",
                (guild_id, event),
            )
            result = await cursor.fetchone()
            return result[0] if result else None
    return await cached_or_fetch("am_pun", _fetch, guild_id, event, ttl=30.0)


def invalidate_guild(guild_id: int):
    from utils.cache import invalidate
    invalidate("am_enabled", guild_id)
    for ns in ("am_module", "am_ich", "am_iro", "am_pun"):
        # invalidate all keys in the namespace (event names vary)
        invalidate(ns)
