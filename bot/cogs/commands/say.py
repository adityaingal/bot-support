# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 OGADI — All Rights Reserved                    ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/UVRWygSpJq                    ║
# ╚══════════════════════════════════════════════════════════════════╝

import discord
from discord.ext import commands
from utils.Tools import *
from utils.emoji import TICK, ERROR, CROSS

class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="msg", aliases=["say", "announce", "send"], help="Send a message to a channel or user.")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 6, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def msg(self, ctx, target: discord.TextChannel | discord.Member | discord.User = None, *, message: str = None):
        if target is None:
            target = ctx.channel

        if message is None:
            error = discord.Embed(description=f"{CROSS} Usage: `!msg <#channel/@user> <your message>`", color=0xFF0000)
            return await ctx.send(embed=error)

        embed = discord.Embed(description=message, color=0xFF0000, timestamp=discord.utils.utcnow())
        embed.set_author(name=f"Message from {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)

        try:
            if isinstance(target, (discord.Member, discord.User)):
                await target.send(embed=embed)
                dest = f"{target.name} ({target.id})'s DMs"
            else:
                await target.send(embed=embed)
                dest = f"#{target.name} ({target.id})"

            success = discord.Embed(description=f"{TICK} Message sent to {dest}.", color=0xFF0000)
            await ctx.send(embed=success)
        except discord.Forbidden:
            error = discord.Embed(description=f"{ERROR} Cannot send to {target.name} ({target.id}) — DMs may be closed or no channel permission.", color=0xFF0000)
            await ctx.send(embed=error)
        except Exception as e:
            error = discord.Embed(description=f"{ERROR} Failed to send: `{e}`", color=0xFF0000)
            await ctx.send(embed=error)

async def setup(bot):
    await bot.add_cog(Say(bot))
