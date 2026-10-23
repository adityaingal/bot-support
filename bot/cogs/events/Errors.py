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

import discord
import json
import sys
import traceback
import aiosqlite
from discord.ext import commands
from utils.config import serverLink
from core import zyrox, Cog, Context
from utils.Tools import get_ignore_data
from utils.cloudbreaker import CloudflareBanError

class Errors(Cog):
  def __init__(self, client: zyrox):
    self.client = client

  @commands.Cog.listener()
  async def on_error(self, event_method, *args, **kwargs):
    exc = sys.exc_info()[1]
    if isinstance(exc, CloudflareBanError):
      return
    print(f"[ERROR] Unhandled event exception in {event_method}: {exc!r}", flush=True)

  @commands.Cog.listener()
  async def on_command_error(self, ctx: Context, error):
    # Centralised handler: one failing command (or one failing branch of this
    # handler) must never take the bot down, and users must never see a
    # stack trace — technical detail stays in the Render logs.
    try:
      await self._handle_error(ctx, error)
    except Exception as exc:
      print(f"ERROR - error handler failed for "
            f"{getattr(ctx.command, 'qualified_name', '<unknown>')} : {exc!r}", flush=True)
      traceback.print_exc()

  async def _handle_error(self, ctx: Context, error):
    if ctx.command is None:
      return

    if isinstance(error, commands.CommandNotFound):
      return

    if isinstance(error, CloudflareBanError):
      print(f"[cloudbreaker] Command {ctx.command} suppressed: {error}", flush=True)
      return

    if isinstance(error, commands.MissingRequiredArgument):
      await ctx.send_help(ctx.command)
      ctx.command.reset_cooldown(ctx)
      return

    # Checked before the generic CheckFailure branch: NoPrivateMessage is a
    # CheckFailure subclass and ctx.guild is None in DMs.
    if isinstance(error, commands.NoPrivateMessage):
      embed = discord.Embed(color=0xFF0000, description="You can't use my commands in DMs.")
      embed.set_author(name=ctx.author, icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
      embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
      await ctx.reply(embed=embed, delete_after=20)
      return

    if isinstance(error, commands.CheckFailure):
      if ctx.guild is not None:
        try:
          data = await get_ignore_data(ctx.guild.id)
        except Exception:
          data = None
        if data:
          ch = data["channel"]
          iuser = data["user"]
          cmd = data["command"]
          buser = data["bypassuser"]

          if str(ctx.author.id) in buser:
            return

          if str(ctx.channel.id) in ch:
            await ctx.reply(f"{ctx.author.mention} **This channel was in ignored list try my commands on other channel**.",
                            delete_after=8)
            return

          if str(ctx.author.id) in iuser:
            await ctx.reply(f"{ctx.author.mention} **You are set as an ignored user for this guild. Please try my commands in a different guild.**", delete_after=8)
            return

          if ctx.command.name in cmd or any(alias in cmd for alias in ctx.command.aliases):
            await ctx.reply(f"{ctx.author.mention} **This command is ignored in this guild. Please use other commands or try this command in a different guild**", delete_after=8)
            return
      return

    if isinstance(error, commands.TooManyArguments):
      await ctx.send_help(ctx.command)
      ctx.command.reset_cooldown(ctx)
      return

    if isinstance(error, commands.CommandOnCooldown):
      embed = discord.Embed(color=0xFF0000, description=f"**{ctx.author.mention} Couldown is here Bro Tryy commands in {error.retry_after:.2f} seconds**.")
      embed.set_author(name="Cooldown", icon_url=self._bot_icon())

      embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
      await ctx.reply(embed=embed, delete_after=10)
      return

    if isinstance(error, commands.MaxConcurrencyReached):
      embed = discord.Embed(color=0xFF0000, description=f"{ctx.author.mention} This command is already in progress. Please let it finish and try again afterward.")
      embed.set_author(name="Command in Progress.", icon_url=self._bot_icon())

      embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
      await ctx.reply(embed=embed, delete_after=10)
      ctx.command.reset_cooldown(ctx)
      return

    if isinstance(error, commands.MissingPermissions):
      missing = [perm.replace("_", " ").replace("guild", "server").title() for perm in error.missing_permissions]
      fmt = "{}, and {}".format(", ".join(missing[:-1]), missing[-1]) if len(missing) > 2 else " and ".join(missing)
      embed = discord.Embed(color=0xFF0000, description=f"**Ops! You don't have {fmt} Permission to run the {ctx.command.name} command!**")
      embed.set_author(name="Missing Permissions", icon_url=self._bot_icon())

      embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
      await ctx.reply(embed=embed, delete_after=7)
      ctx.command.reset_cooldown(ctx)
      return

    if isinstance(error, commands.BadArgument):
      await ctx.send_help(ctx.command)
      ctx.command.reset_cooldown(ctx)
      return

    if isinstance(error, commands.BotMissingPermissions):
      missing = ", ".join(error.missing_permissions)
      await ctx.reply(f'** Huh! I need {missing} Permission to run the {ctx.command.qualified_name}command! Give me {missing} Permission**', delete_after=7)
      return

    if isinstance(error, commands.CommandInvokeError):
      original = error.original
      print(f"[ERROR] CommandInvokeError in {ctx.command}: {original!r}", flush=True)
      if isinstance(original, (discord.Forbidden, discord.NotFound, discord.HTTPException)):
        traceback.print_exception(type(original), original, original.__traceback__)
      await self._send_generic(ctx, original)
      return

    if isinstance(error, discord.HTTPException):
      print(f"[ERROR] HTTPException in {ctx.command}: {error!r}", flush=True)
      await self._send_generic(ctx, error)
      return

    # Unknown error type: log it, keep the user-facing message clean.
    print(f"[ERROR] Unhandled command error in {ctx.command}: {error!r}", flush=True)
    if getattr(error, "__traceback__", None) is not None:
      traceback.print_exception(type(error), error, error.__traceback__)
    await self._send_generic(ctx, error)

  def _bot_icon(self):
    # discord.utils.MISSING means "omit the icon" — safe even before the
    # gateway has finished identifying.
    user = self.client.user
    if user is None:
      return discord.utils.MISSING
    if user.avatar:
      return user.avatar.url
    return user.default_avatar.url

  async def _send_generic(self, ctx: Context, original) -> None:
    """Clean, non-technical message for the user; details are already logged."""
    try:
      if isinstance(original, discord.Forbidden):
        text = "I don't have permission to do that here."
      elif isinstance(original, discord.NotFound):
        text = "I couldn't find that. It may have been deleted."
      elif isinstance(original, discord.HTTPException):
        text = "Discord is having trouble right now — please try again in a moment."
      else:
        text = "Something went wrong while running that command. It has been logged."
      await ctx.reply(text, delete_after=10)
    except Exception:
      pass
