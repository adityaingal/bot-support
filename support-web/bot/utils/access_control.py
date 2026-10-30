# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 OGADI — All Rights Reserved                    ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/UVRWygSpJq                    ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

"""Bot-wide command access control.

Policy (chosen by the bot owner):
  - Bot-global / developer commands keep their own ``@commands.is_owner()``
    checks — only people in OWNER_IDS may run them.
  - Server commands that require access run ONLY for: the bot developer,
    the server owner, or a member with the Administrator permission.
  - Everything else (fun, info, utility) stays open to every member.

The privileged set is detected from the command's own
``has_permissions(...)`` declaration, so moderation and config commands are
covered automatically without maintaining a giant name list. Config
commands that forgot a permission check are listed in EXTRA_PRIVILEGED
below (edit that set to extend the policy).
"""

from __future__ import annotations

import discord
from discord.ext import commands

from utils.config import OWNER_IDS
from utils.emoji import DENIED

# Qualified names of config/toggle commands that require access but do not
# declare has_permissions(...). Keep in sync when adding new setup commands.
EXTRA_PRIVILEGED = frozenset({
    "automod", "automod ignore", "automod unignore",
    "autoresponder",
    "counting",
    "filter", "filter enable", "filter disable",
    "ai activate", "ai deactivate", "ai database-clear",
    "ai conversation-clear", "ai roleplay-enable", "ai roleplay-disable",
    "leveling blacklist", "leveling blacklist add",
    "leveling blacklist remove", "leveling blacklist list",
    "setnotif", "notify reset",
    "topcheck enable", "topcheck disable",
    "vanityroles", "vanityroles setup", "vanityroles reset",
    "voice mute", "voice unmute", "voice deafen", "voice undeafen",
    "greet", "blacklistword", "ticket", "extraowner", "log",
    "emergency enable", "emergency disable", "emergency authorise",
    "emergency add", "emergency remove", "emergency list",
    "emergency role add", "emergency role remove", "emergency role list",
    "emergencysituation", "emergencyrestore",
    "customrole staff", "customrole girl", "customrole vip",
    "customrole guest", "customrole friend",
})


def is_bot_dev(user) -> bool:
    return getattr(user, "id", None) in OWNER_IDS


# Per-(channel, user, command) throttle for the deny embed. Without it a user
# spamming a gated command gets one Access Denied reply per message and floods
# the channel; repeated denials inside the window are silently dropped (the
# command still never runs).
_DENY_COOLDOWN = 10.0
_last_denied: dict = {}
_MAX_DENIED_KEYS = 5000


def _deny_throttled(channel_id, user_id, command_name: str) -> bool:
    import time
    key = (channel_id, user_id, command_name)
    now = time.monotonic()
    if len(_last_denied) > _MAX_DENIED_KEYS:
        _last_denied.clear()
    last = _last_denied.get(key)
    if last is not None and now - last < _DENY_COOLDOWN:
        return True
    _last_denied[key] = now
    return False


def _permission_requirements(cmd) -> dict | None:
    """Return the has_permissions(...) dict captured by a command's checks."""
    for check in getattr(cmd, "checks", ()):  # empty for groups without checks
        for cell in getattr(check, "__closure__", None) or ():
            value = cell.cell_contents
            if (
                isinstance(value, dict)
                and value
                and all(isinstance(flag, bool) for flag in value.values())
            ):
                return value
    return None


async def _deny(ctx: commands.Context, description: str) -> None:
    embed = discord.Embed(
        title=f"{DENIED} Access Denied",
        description=description,
        color=0x000000,
    )
    embed.set_footer(
        text=f"“{ctx.command.qualified_name}” requested by {ctx.author}",
        icon_url=ctx.author.avatar.url if getattr(ctx.author, "avatar", None)
        else ctx.author.default_avatar.url,
    )
    try:
        await ctx.send(embed=embed)
    except discord.HTTPException:
        pass


async def check_command_access(ctx: commands.Context) -> bool:
    """Global access gate. Returns True when the command may run."""
    cmd = ctx.command
    if cmd is None:
        return True

    if is_bot_dev(ctx.author):
        return True

    requirements = None
    # Walk the command and its parents: a subcommand inherits the group gate.
    current = cmd
    while current is not None and requirements is None:
        requirements = _permission_requirements(current)
        current = getattr(current, "parent", None)

    privileged = (
        requirements is not None and not requirements.get("administrator")
    ) or cmd.qualified_name in EXTRA_PRIVILEGED

    if not privileged:
        return True

    if ctx.guild is None:
        if not _deny_throttled(None, ctx.author.id, cmd.qualified_name):
            await _deny(ctx, "**This is a server command** — it can only be used inside a server.")
        return False

    author = ctx.author
    if ctx.guild.owner_id == author.id or author == getattr(ctx.guild, "owner", None):
        return True

    guild_permissions = getattr(author, "guild_permissions", None)
    if guild_permissions is not None and getattr(guild_permissions, "administrator", False):
        return True

    if not _deny_throttled(ctx.channel.id, author.id, cmd.qualified_name):
        await _deny(
            ctx,
            f"{author.mention} **Administrator or the server owner** is required "
            f"to use `{ctx.command.qualified_name}`.",
        )
    return False
