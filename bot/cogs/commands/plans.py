# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░░░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 OGADI — All Rights Reserved                    ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/UVRWygSpJq                    ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.cv2 import CV2
from utils.plans import add_plan, get_plan, list_plans, remove_plan


async def guild_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    """Suggest the bot's guilds so the dev never has to type a raw ID."""
    query = (current or "").lower().strip()
    choices: list[app_commands.Choice[int]] = []
    for guild in sorted(interaction.client.guilds, key=lambda g: g.name.lower()):
        if query in guild.name.lower() or query in str(guild.id):
            choices.append(app_commands.Choice(name=f"{guild.name}  ({guild.id})", value=guild.id))
        if len(choices) >= 25:
            break
    return choices


class Plans(commands.Cog):
    """Paid plans — per-server premium subscription management."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name="plan", invoke_without_command=True)
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def plan(self, ctx: commands.Context):
        """Show this server's plan status."""
        if ctx.guild is None:
            return await ctx.send(view=CV2("💎 Plans", "Plans are **per server** — run this inside a server."))
        info = await get_plan(ctx.guild.id)
        if info:
            await ctx.send(view=CV2(
                "💎 Plan Active",
                f"**Server:** {ctx.guild.name}\n"
                f"**Plan:** {info['plan'].title()}\n"
                f"**Expires:** <t:{int(info['expires'].timestamp())}:R>"
            ))
        else:
            await ctx.send(view=CV2(
                "💎 No Plan",
                f"**{ctx.guild.name}** has no active plan.\n"
                f"Plan-only features are locked. Contact the bot owner to buy a plan."
            ))

    @plan.command(name="add")
    @commands.is_owner()
    @app_commands.describe(guild_id="Pick the server from the list", plan="Plan name", days="Days until it expires")
    @app_commands.autocomplete(guild_id=guild_autocomplete)
    @app_commands.rename(guild_id="guild")
    async def plan_add(self, ctx, guild_id: int, plan: str = "standard", days: int = 30):
        """Add/extend a plan: >plan add <guild_id> [plan] [days]"""
        if days < 1:
            return await ctx.send(view=CV2("😒 Error", "**Days** must be at least 1."))
        expires = await add_plan(guild_id, plan.lower(), days, ctx.author.id)
        await ctx.send(view=CV2(
            "💎 Plan Added",
            f"**Guild ID:** `{guild_id}`\n**Plan:** {plan.lower()}\n"
            f"**Days:** {days}\n**Expires:** <t:{int(expires.timestamp())}:R>"
        ))

    @plan.command(name="remove")
    @commands.is_owner()
    @app_commands.describe(guild_id="Pick the server from the list")
    @app_commands.autocomplete(guild_id=guild_autocomplete)
    @app_commands.rename(guild_id="guild")
    async def plan_remove(self, ctx, guild_id: int):
        """Remove a plan: >plan remove <guild_id>"""
        removed = await remove_plan(guild_id)
        text = f"**Guild ID:** `{guild_id}`\nPlan removed." if removed else "No plan found for that guild."
        await ctx.send(view=CV2("💎 Plan Removed" if removed else "😒 Not Found", text))

    @plan.command(name="info")
    @commands.is_owner()
    @app_commands.describe(guild_id="Pick the server from the list")
    @app_commands.autocomplete(guild_id=guild_autocomplete)
    @app_commands.rename(guild_id="guild")
    async def plan_info(self, ctx, guild_id: int):
        """Show a guild's plan: >plan info <guild_id>"""
        info = await get_plan(guild_id)
        if not info:
            return await ctx.send(view=CV2("😒 Not Found", f"No active plan for `{guild_id}`."))
        await ctx.send(view=CV2(
            "💎 Plan Info",
            f"**Guild ID:** `{guild_id}`\n**Plan:** {info['plan'].title()}\n"
            f"**Expires:** <t:{int(info['expires'].timestamp())}:R>\n"
            f"**Added by:** <@{info['added_by']}>"
        ))

    @plan.command(name="list")
    @commands.is_owner()
    async def plan_list(self, ctx):
        """List every plan."""
        plans = await list_plans()
        if not plans:
            return await ctx.send(view=CV2("💎 Plans", "No plans yet. Use `>plan add <guild_id> [plan] [days]`."))
        lines = []
        for entry in plans[:25]:
            state = "✅" if entry["active"] else "❌"
            lines.append(
                f"{state} `{entry['guild_id']}` — **{entry['plan'].title()}** "
                f"until <t:{int(entry['expires'].timestamp())}:R>"
            )
        await ctx.send(view=CV2(f"💎 Plans [{len(plans)}]", "\n".join(lines)))


async def setup(bot):
    await bot.add_cog(Plans(bot))
