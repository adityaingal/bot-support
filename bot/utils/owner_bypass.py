# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                      ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 OGADI — All Rights Reserved                    ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/UVRWygSpJq                    ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

"""Bot-developer command bypass.

Anyone in ``OWNER_IDS`` may run **every** command in **every** guild, no
matter what permission checks the command declares.

Two layers are involved:

1. ``utils.access_control`` already lets developers through the bot-wide
   access gate — that gate is *not* touched here.
2. This module covers the rest: the ``@commands.has_permissions(...)`` /
   ``@app_commands.checks.*`` predicates attached to each command (326
   permission decorators in this codebase), which otherwise raise
   ``MissingPermissions`` for a developer standing in a guild where they
   hold no role.

Every predicate is wrapped once and marked, so installing twice is a
no-op. Checks that describe the *bot's* own capabilities or the validity
of the invocation are deliberately **never** bypassed:

- ``bot_has_*``        — the bot really lacks the permission; bypassing it
                         only turns a clear error into an API failure.
- ``guild_only`` / ``dm_only`` / ``is_nsfw`` — the command cannot legally
  run in that context for anyone.
- ``cooldown`` / ``dynamic_cooldown`` — rate limits still protect the
  Discord API; a developer bypassing them would only earn a 429.

Command bodies that hardcode "only the server owner" gate themselves with
:func:`dev_bypass` instead of duplicating the OWNER_IDS comparison.
"""

from __future__ import annotations

import inspect
from typing import Any, Iterator

from utils.config import OWNER_IDS

# Marks a predicate as already wrapped (or deliberately left alone).
_MARK = "__support_owner_bypass__"

# ``__qualname__`` roots that must keep running for developers too.
_NEVER_BYPASS = frozenset({
    "bot_has_permissions",
    "bot_has_guild_permissions",
    "bot_has_role",
    "bot_has_any_role",
    "guild_only",
    "dm_only",
    "is_nsfw",
    "is_not_nsfw",
    "cooldown",
    "dynamic_cooldown",
    "_create_cooldown_decorator",
})


def is_bot_dev(user: Any) -> bool:
    """True when ``user`` is listed in the OWNER_IDS environment variable."""
    return getattr(user, "id", None) in OWNER_IDS


def actor_of(obj: Any) -> Any:
    """The user behind a :class:`~discord.ext.commands.Context` or
    :class:`~discord.Interaction` — whichever the object carries."""
    actor = getattr(obj, "author", None)
    if actor is None:
        actor = getattr(obj, "user", None)
    return actor


def dev_bypass(obj: Any) -> bool:
    """Inline-gate helper: ``if not dev_bypass(ctx): return``.

    Use it in command bodies that hardcode a server-owner-only rule so the
    bot developer is accepted alongside the guild owner.
    """
    return is_bot_dev(actor_of(obj))


def _qual_root(pred: Any) -> str:
    """``has_permissions.<locals>.predicate`` → ``has_permissions``."""
    name = getattr(pred, "__qualname__", None) or getattr(pred, "__name__", "") or ""
    return name.split(".<locals>")[0]


def _wrap(pred: Any):
    if getattr(pred, _MARK, False):
        return pred

    async def bypass(*args: Any, **kwargs: Any):
        # ctx / interaction is always the first positional argument of a
        # check, for both prefix and application commands.
        if args and is_bot_dev(actor_of(args[0])):
            return True
        result = pred(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    bypass.__name__ = getattr(pred, "__name__", "check")
    bypass.__qualname__ = getattr(pred, "__qualname__", bypass.__name__)
    bypass.__doc__ = getattr(pred, "__doc__", None)
    bypass.__dict__[_MARK] = True
    return bypass


def _wrap_command(cmd: Any) -> int:
    """Wrap one command's own checks. Returns how many were touched."""
    checks = getattr(cmd, "checks", None)
    if not checks:
        return 0

    changed = False
    wrapped: list = []
    for pred in checks:
        if getattr(pred, _MARK, False) or _qual_root(pred) in _NEVER_BYPASS:
            wrapped.append(pred)
        else:
            wrapped.append(_wrap(pred))
            changed = True

    if changed:
        # Rebind instead of mutating: Command.checks may alias the
        # callback's __commands_checks__ list shared with sibling commands.
        cmd.checks = wrapped
        return 1
    return 0


def _iter_subcommands(cmd: Any) -> Iterator[Any]:
    yield cmd
    walk = getattr(cmd, "walk_commands", None)
    if walk is not None:
        yield from walk()


def wrap_command(cmd: Any) -> int:
    """Wrap ``cmd``, its subcommands and its application-command twin."""
    total = 0
    for node in _iter_subcommands(cmd):
        total += _wrap_command(node)
    app = getattr(cmd, "app_command", None)
    if app is not None:
        total += _wrap_command(app)
        for node in _iter_subcommands(app):
            total += _wrap_command(node)
    return total


def install_owner_bypass(bot: Any) -> int:
    """Wrap every check currently registered on ``bot``.

    Idempotent: already-wrapped predicates are skipped, so calling this
    again after a cog load or a reload is cheap and safe.
    """
    total = 0
    for cmd in bot.walk_commands():
        total += _wrap_command(cmd)
    try:
        for cmd in bot.tree.walk_commands():
            total += _wrap_command(cmd)
    except Exception:
        # A tree that is not walkable yet must never block startup.
        pass
    return total
