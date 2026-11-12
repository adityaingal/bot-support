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

    @commands.hybrid_command(name="msg", aliases=["say", "announce", "send"], help="Send a normal message to a channel.")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 6, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def msg(self, ctx, channel: discord.TextChannel = None, *, message: str = None):
        if message is None:
            if channel is not None:
                message = channel
                channel = None
            else:
                error = discord.Embed(description=f"{CROSS} Usage: `!say <#channel> <message>`", color=0xFF0000)
                return await ctx.send(embed=error)

        if channel is None:
            channel = ctx.channel

        try:
            await channel.send(message)
            dest = f"#{channel.name} ({channel.id})"
            success = discord.Embed(description=f"{TICK} Message sent to {dest}.", color=0xFF0000)
            await ctx.send(embed=success)
        except discord.Forbidden:
            error = discord.Embed(description=f"{ERROR} Cannot send to {dest} — no permission in that channel.", color=0xFF0000)
            await ctx.send(embed=error)
        except Exception as e:
            error = discord.Embed(description=f"{ERROR} Failed to send: `{e}`", color=0xFF0000)
            await ctx.send(embed=error)

async def setup(bot):
    await bot.add_cog(Say(bot))
