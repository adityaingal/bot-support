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

from __future__ import annotations
import os
import traceback
from discord.ext import commands, tasks
import discord
import aiohttp
import json
import jishaku
import asyncio
import typing
from typing import List
import aiosqlite
from utils.config import OWNER_IDS, BotName
from utils.Tools import getConfig, updateConfig
from utils.cache import cached_or_fetch
from .Context import Context
from colorama import Fore, Style, init
import importlib
import inspect

init(autoreset=True)

# Corrected the extensions list
extensions: List[str] = [
    "cogs"
]


class ExtensionLoadError(RuntimeError):
    """Raised when the main cog package fails to load.

    This is a *fatal* startup error: the bot must not pretend to be healthy
    when none of its commands can work.
    """


class zyrox(commands.AutoShardedBot):
    def __init__(self, *arg, **kwargs):
        intents = discord.Intents.all()
        intents.presences = True
        intents.members = True
        # Optional outbound proxy for Discord HTTP + gateway traffic.
        # Render's shared IPs are frequently Cloudflare-blocked (Error 1015);
        # set DISCORD_PROXY (e.g. http://user:pass@host:port) to route around it.
        proxy = (os.getenv("DISCORD_PROXY") or "").strip() or None
        proxy_auth = None
        if proxy and "@" in proxy and "://" in proxy:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(proxy)
                if parsed.username or parsed.password:
                    from aiohttp import BasicAuth
                    proxy_auth = BasicAuth(parsed.username or "", parsed.password or "")
                    proxy = parsed._replace(netloc=parsed.hostname + (f":{parsed.port}" if parsed.port else "")).geturl()
            except Exception:
                pass
        if proxy:
            kwargs.setdefault("proxy", proxy)
            if proxy_auth is not None:
                kwargs.setdefault("proxy_auth", proxy_auth)
        super().__init__(command_prefix=self.get_prefix,
                         case_insensitive=True,
                         intents=intents,
                         status=self._discord_status(),
                         strip_after_prefix=True,
                         owner_ids=OWNER_IDS,
                         allowed_mentions=discord.AllowedMentions(
                             everyone=False, replied_user=False, roles=False),
                         sync_commands_debug=True,
                         sync_commands=True,
                         shard_count=1)
        self.status_index = 0
        self.status_list = []
        self._cogs_loaded = False
        # Bot-wide access gate: privileged server commands run only for the
        # bot developer, the server owner, or an Administrator.
        self.add_check(self._access_control)

    async def _access_control(self, ctx: commands.Context) -> bool:
        from utils.access_control import check_command_access
        return await check_command_access(ctx)

    @staticmethod
    def _discord_status() -> discord.Status:
        """Read the initial Discord presence from the environment."""
        value = os.getenv("DISCORD_STATUS", "online").strip().lower()
        return getattr(discord.Status, value, discord.Status.online)

    async def setup_hook(self):
        # login() runs setup_hook again whenever start() is retried after a
        # temporary network failure — loading twice would crash on duplicate
        # cogs and on an already-running task loop.
        if not self._cogs_loaded:
            print("INFO  - Loading cogs...", flush=True)
            await self.load_extensions()
            self._cogs_loaded = True
        if not self.status_task.is_running():
            self.status_task.start()

    async def load_extensions(self):
        for extension in extensions:
            try:
                await self.load_extension(extension)
                print(Fore.GREEN + Style.BRIGHT + f"Loaded extension: {extension}")
            except Exception as e:
                print(f"{Fore.RED}{Style.BRIGHT}Failed to load extension {extension}. {e}", flush=True)
                traceback.print_exc()
                raise ExtensionLoadError(f"failed to load extension '{extension}': {e}") from e
        print(Fore.GREEN + Style.BRIGHT + "*" * 20)

    async def close(self) -> None:
        # Stop our own loops before closing the gateway so shutdown is clean.
        try:
            if self.status_task.is_running():
                self.status_task.cancel()
        except Exception:
            pass
        # Close the shared aiohttp session created by the Badges/owner cog.
        session = getattr(self, "session", None)
        if session is not None:
            try:
                await session.close()
            except Exception:
                pass
            self.session = None
        await super().close()

    @tasks.loop(seconds=120)
    async def status_task(self):
        # Any exception here would silently stop the presence rotation forever,
        # so the whole loop body is guarded.
        try:
            await self.wait_until_ready()
            if not self.guilds:
                return

            guild = self.guilds[0]  # Use first available guild for prefix
            try:
                config = await getConfig(guild.id)
                prefix = config.get("prefix", ">")
            except Exception:
                prefix = ">"

            user_count = sum(g.member_count or 0 for g in self.guilds)
            guild_count = len(self.guilds)

            configured_activity = os.getenv("BOT_ACTIVITY", "").strip()
            self.status_list = [
                (discord.ActivityType.playing, configured_activity or f"{prefix}help | {BotName}"),
                (discord.ActivityType.watching, f"{user_count} users"),
                (discord.ActivityType.watching, f"{guild_count} servers"),
                (discord.ActivityType.listening, "support requests"),
                (discord.ActivityType.playing, f"Protecting with {BotName}"),
            ]

            current = self.status_list[self.status_index % len(self.status_list)]
            # Keep the configured online/idle/dnd status while rotating the activity.
            try:
                await self.change_presence(
                    status=self._discord_status(),
                    activity=discord.Activity(type=current[0], name=current[1]),
                )
            except discord.HTTPException as e:
                # A failed presence update must never kill the rotation loop.
                print(f"WARNING - presence update skipped: {e!r}", flush=True)
            self.status_index += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"WARNING - status rotation skipped: {e!r}", flush=True)

    async def send_raw(self, channel_id: int, content: str, **kwargs) -> typing.Optional[discord.Message]:
        await self.http.send_message(channel_id, content, **kwargs)

    async def invoke_help_command(self, ctx: Context) -> None:
        return await ctx.send_help(ctx.command)

    async def fetch_message_by_channel(self, channel: discord.TextChannel, messageID: int) -> typing.Optional[discord.Message]:
        async for msg in channel.history(limit=1, before=discord.Object(messageID + 1), after=discord.Object(messageID - 1)):
            return msg

    async def _is_np(self, user_id: int) -> bool:
        async def _fetch():
            async with aiosqlite.connect('db/np.db') as db:
                async with db.execute("SELECT id FROM np WHERE id = ?", (user_id,)) as cursor:
                    row = await cursor.fetchone()
                    return row is not None
        return await cached_or_fetch("np", _fetch, user_id, ttl=60.0)

    async def get_prefix(self, message: discord.Message):
        if message.guild:
            guild_id = message.guild.id
            is_np = await self._is_np(message.author.id)
            data = await getConfig(guild_id)
            prefix = data["prefix"]
            if is_np:
                return commands.when_mentioned_or(prefix, '')(self, message)
            else:
                return commands.when_mentioned_or(prefix)(self, message)
        else:
            is_np = await self._is_np(message.author.id)
            if is_np:
                return commands.when_mentioned_or('?', '')(self, message)
            else:
                return commands.when_mentioned_or('')(self, message)

    async def on_message_edit(self, before, after):
        ctx: Context = await self.get_context(after, cls=Context)
        if before.content != after.content:
            if after.guild is None or after.author.bot:
                return
            if ctx.command is None:
                return
            if isinstance(ctx.channel, discord.Thread):
                return
            await self.invoke(ctx)

def setup_bot():
    intents = discord.Intents.all()
    bot = zyrox(intents=intents)
    return bot
