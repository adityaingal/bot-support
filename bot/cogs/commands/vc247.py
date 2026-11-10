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

"""24/7 Voice — keep the bot in a voice channel around the clock.

Hybrid commands (slash + prefix):
  >vc247 enable   — join & stay in your voice channel 24/7
  >vc247 disable  — leave & stop auto-rejoin
  >vc247 status   — show current 24/7 voice status
"""

from __future__ import annotations

import asyncio
import aiosqlite
import discord
from discord.ext import commands

from utils.Tools import blacklist_check, ignore_check
from utils.emoji import CROSS, TICK, ZWARNING
from utils.cv2 import CV2
from utils.config import *


class Vc247(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.color = 0xFF0000
        self.db_path = "db/vc247.db"
        self._join_locks: dict[int, asyncio.Lock] = {}
        self.bot.loop.create_task(self.create_table())

    # ── database ──────────────────────────────────────────────────
    async def create_table(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS vc247 (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL
                )
                """
            )
            await db.commit()

    async def _get_channel(self, guild_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT channel_id FROM vc247 WHERE guild_id = ?", (guild_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def _set_channel(self, guild_id: int, channel_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO vc247 (guild_id, channel_id) VALUES (?, ?)",
                (guild_id, channel_id),
            )
            await db.commit()

    async def _remove(self, guild_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM vc247 WHERE guild_id = ?", (guild_id,))
            await db.commit()

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        lock = self._join_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._join_locks[guild_id] = lock
        return lock

    # ── helpers ───────────────────────────────────────────────────
    async def _join_channel(self, channel: discord.VoiceChannel) -> bool:
        try:
            if channel.guild.voice_client is not None:
                if channel.guild.voice_client.channel.id == channel.id:
                    return True
                await channel.guild.voice_client.move_to(channel)
            else:
                await channel.connect(reconnect=True, timeout=30.0)
            return True
        except Exception:
            return False

    async def _leave_guild(self, guild: discord.Guild) -> None:
        vc = guild.voice_client
        if vc is not None:
            await vc.disconnect(force=True)

    # ── command group ─────────────────────────────────────────────
    @commands.hybrid_group(name="vc247", invoke_without_command=True,
                           help="Keep the bot in a voice channel 24/7")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def vc247(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            channel_id = await self._get_channel(ctx.guild.id)
            if channel_id is None:
                await ctx.send(
                    view=CV2(
                        f"{ZWARNING} 24/7 Voice",
                        "24/7 voice is not enabled in this server.\n"
                        f"Use `/vc247 enable` while in a voice channel.",
                    )
                )
            else:
                channel = ctx.guild.get_channel(channel_id)
                await ctx.send(
                    view=CV2(
                        f"{TICK} 24/7 Voice",
                        f"Enabled in {channel.mention if channel else 'Unknown channel'}.",
                    )
                )
            ctx.command.reset_cooldown(ctx)

    @vc247.command(name="enable", help="Join & stay in your voice channel 24/7")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(connect=True, speak=True)
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def enable(self, ctx: commands.Context):
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            return await ctx.send(
                view=CV2(f"{CROSS} Error", "You must be in a voice channel first.")
            )

        channel = ctx.author.voice.channel

        # Disable any existing 24/7 in this guild first
        old_id = await self._get_channel(ctx.guild.id)
        if old_id is not None:
            await self._remove(ctx.guild.id)
            await self._leave_guild(ctx.guild)

        await self._set_channel(ctx.guild.id, channel.id)

        async with self._lock_for(ctx.guild.id):
            ok = await self._join_channel(channel)

        if not ok:
            await self._remove(ctx.guild.id)
            return await ctx.send(
                view=CV2(f"{CROSS} Error", "Failed to join the voice channel.")
            )

        await ctx.send(
            view=CV2(
                f"{TICK} 24/7 Voice Enabled",
                f"The bot will now stay in {channel.mention} 24/7 and rejoin if disconnected.",
            )
        )

    @vc247.command(name="disable", help="Stop 24/7 voice & leave the channel")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    async def disable(self, ctx: commands.Context):
        channel_id = await self._get_channel(ctx.guild.id)
        if channel_id is None:
            return await ctx.send(
                view=CV2(f"{ZWARNING} 24/7 Voice", "24/7 voice is not enabled here.")
            )

        await self._remove(ctx.guild.id)
        await self._leave_guild(ctx.guild)

        await ctx.send(
            view=CV2(f"{TICK} 24/7 Voice Disabled", "The bot left the voice channel.")
        )

    @vc247.command(name="status", help="Show current 24/7 voice status")
    @blacklist_check()
    @ignore_check()
    async def status(self, ctx: commands.Context):
        channel_id = await self._get_channel(ctx.guild.id)
        if channel_id is None:
            return await ctx.send(
                view=CV2(f"{ZWARNING} 24/7 Voice", "Not enabled in this server.")
            )
        channel = ctx.guild.get_channel(channel_id)
        vc = ctx.guild.voice_client
        in_channel = vc is not None and vc.channel.id == channel.id
        await ctx.send(
            view=CV2(
                f"{TICK if in_channel else CROSS} 24/7 Voice",
                f"Channel: {channel.mention if channel else 'Unknown'}\n"
                f"Bot connected: {'Yes' if in_channel else 'No (will rejoin)'}",
            )
        )

    # ── auto-rejoin listener ──────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Only care when the bot itself is moved/disconnected
        if member.id != self.bot.user.id:
            return

        channel_id = await self._get_channel(member.guild.id)
        if channel_id is None:
            return

        target = member.guild.get_channel(channel_id)
        if target is None:
            return

        # If already in the target channel, nothing to do
        vc = member.guild.voice_client
        if vc is not None and vc.channel.id == channel_id:
            return

        # Rejoin after a short delay so transient disconnects don't loop
        await asyncio.sleep(5)
        channel_id2 = await self._get_channel(member.guild.id)
        if channel_id2 is None or channel_id2 != channel_id:
            return
        vc2 = member.guild.voice_client
        if vc2 is not None and vc2.channel.id == channel_id:
            return
        async with self._lock_for(member.guild.id):
            await self._join_channel(target)

    async def cog_unload(self) -> None:
        pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Vc247(bot))
