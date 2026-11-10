"""Automated tests for utils.owner_bypass (developer bypass of command checks)."""

import os
import sys
import asyncio
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord
from discord.ext import commands

from utils import owner_bypass
from utils.owner_bypass import dev_bypass, install_owner_bypass

DEV_ID = 111111111111111111
USER_ID = 222222222222222222
OWNER_ID = 333333333333333333


class FakeCtx:
    """Minimal Context stand-in: only the attributes checks actually read."""

    def __init__(self, bot, *, user_id, guild=True, permissions=(), bot_permissions=()):
        self.bot = bot
        self.command = None
        self.author = SimpleNamespace(id=user_id)
        self.guild = FakeGuild() if guild else None
        self.channel = SimpleNamespace(id=4242)
        self.invoked_with = "cmd"
        self.permissions = discord.Permissions(**dict(permissions))
        self.bot_permissions = discord.Permissions(**dict(bot_permissions))
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeGuild:
    id = 1
    owner_id = OWNER_ID


def _run(coro):
    return asyncio.run(coro)


class OwnerBypassTests(unittest.TestCase):
    def setUp(self):
        self._old_owner_ids = owner_bypass.OWNER_IDS
        owner_bypass.OWNER_IDS = {DEV_ID}
        self.bot = commands.Bot(command_prefix=">", owner_ids=set(),
                                intents=discord.Intents.default())

    def tearDown(self):
        owner_bypass.OWNER_IDS = self._old_owner_ids
        _run(self.bot.close())

    # -- helpers -------------------------------------------------------
    def _admin_command(self, name="admincmd"):
        @commands.command(name=name)
        @commands.has_permissions(administrator=True)
        async def cmd(ctx):
            pass

        self.bot.add_command(cmd)
        return cmd

    def _ctx(self, user_id, *, bot=None, **kwargs):
        return FakeCtx(bot or self.bot, user_id=user_id, **kwargs)

    # -- tests ---------------------------------------------------------
    def test_developer_runs_permission_gated_command_without_admin(self):
        cmd = self._admin_command()
        install_owner_bypass(self.bot)
        ctx = self._ctx(DEV_ID, permissions={})
        self.assertTrue(_run(cmd.can_run(ctx)))

    def test_non_developer_still_denied_without_admin(self):
        cmd = self._admin_command()
        install_owner_bypass(self.bot)
        ctx = self._ctx(USER_ID, permissions={})
        with self.assertRaises(commands.MissingPermissions):
            _run(cmd.can_run(ctx))

    def test_non_developer_with_admin_runs(self):
        cmd = self._admin_command()
        install_owner_bypass(self.bot)
        ctx = self._ctx(USER_ID, permissions={"administrator": True})
        self.assertTrue(_run(cmd.can_run(ctx)))

    def test_bot_capability_check_is_never_bypassed(self):
        @commands.command(name="botcap")
        @commands.bot_has_permissions(administrator=True)
        async def cmd(ctx):
            pass

        self.bot.add_command(cmd)
        install_owner_bypass(self.bot)
        ctx = self._ctx(DEV_ID, bot_permissions={})
        with self.assertRaises(commands.BotMissingPermissions):
            _run(cmd.can_run(ctx))

    def test_guild_only_is_never_bypassed(self):
        @commands.command(name="servercmd")
        @commands.guild_only()
        async def cmd(ctx):
            pass

        self.bot.add_command(cmd)
        install_owner_bypass(self.bot)
        ctx = self._ctx(DEV_ID, guild=False)
        with self.assertRaises(commands.NoPrivateMessage):
            _run(cmd.can_run(ctx))

    def test_subcommands_are_wrapped_too(self):
        @commands.group(name="grouped")
        async def grouped(ctx):
            pass

        @grouped.command(name="sub")
        @commands.has_permissions(administrator=True)
        async def sub(ctx):
            pass

        self.bot.add_command(grouped)
        install_owner_bypass(self.bot)
        sub_cmd = grouped.get_command("sub")
        self.assertTrue(_run(sub_cmd.can_run(self._ctx(DEV_ID, permissions={}))))

    def test_install_is_idempotent(self):
        cmd = self._admin_command()
        before = len(cmd.checks)
        install_owner_bypass(self.bot)
        after_first = len(cmd.checks)
        install_owner_bypass(self.bot)
        self.assertEqual(after_first, len(cmd.checks))
        self.assertEqual(before, after_first)

    def test_add_command_wraps_immediately(self):
        # The real bot class must install the bypass at registration time,
        # so a command never runs unwrapped while waiting for the next
        # full install.
        from core.zyrox import zyrox as zyrox_cls

        self.assertIsNot(zyrox_cls.add_command, commands.Bot.add_command)

        bot = zyrox_cls()

        @commands.command(name="late")
        @commands.has_permissions(administrator=True)
        async def cmd(ctx):
            pass

        bot.add_command(cmd)
        # No explicit install: add_command alone must have wrapped it.
        ctx = self._ctx(DEV_ID, bot=bot, permissions={})
        self.assertTrue(_run(cmd.can_run(ctx)))
        # Never started, so close() has no shard queue to drain — release
        # nothing here on purpose.

    def test_dev_bypass_helper(self):
        ctx = self._ctx(DEV_ID)
        self.assertTrue(dev_bypass(ctx))
        self.assertFalse(dev_bypass(self._ctx(USER_ID)))
        self.assertFalse(dev_bypass(SimpleNamespace(user=SimpleNamespace(id=USER_ID))))
        self.assertTrue(dev_bypass(SimpleNamespace(user=SimpleNamespace(id=DEV_ID))))


if __name__ == "__main__":
    unittest.main()
