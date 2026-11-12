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
import aiosqlite
import json
from discord.ext import commands
from discord.ui import View, Button, Select
from utils.Tools import *
from utils.emoji import TICK, ZTICK

class Rules(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self._create_table())

    async def _create_table(self):
        async with aiosqlite.connect("db/rules.db") as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                rules_text TEXT
            )
            """)
            await db.commit()

    @commands.hybrid_group(invoke_without_command=True, name="rules", help="Server rules management.")
    @blacklist_check()
    @ignore_check()
    async def rules(self, ctx: commands.Context):
        if ctx.subcommand_passed is None:
            await ctx.send_help(ctx.command)
            ctx.command.reset_cooldown(ctx)

    @rules.command(name="set", aliases=["setup", "config"], help="Set the rules text for this server.")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 6, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def rules_set(self, ctx, *, rules_text: str = None):
        if rules_text is None:
            await ctx.send("Please provide the rules text.")
            return

        async with aiosqlite.connect("db/rules.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO rules (guild_id, channel_id, rules_text) VALUES (?, COALESCE((SELECT channel_id FROM rules WHERE guild_id = ?), NULL), ?)",
                (ctx.guild.id, ctx.guild.id, rules_text)
            )
            await db.commit()

        embed = discord.Embed(title=f"{TICK}> Rules Set", description="Server rules have been saved.", color=0xFF0000)
        embed.add_field(name="Rules", value=rules_text[:1024] or "None", inline=False)
        await ctx.send(embed=embed)

    @rules.command(name="channel", aliases=["setchannel"], help="Set the channel where rules will be posted.")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 6, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def rules_channel(self, ctx, channel: discord.TextChannel = None):
        if channel is None:
            channel = ctx.channel

        async with aiosqlite.connect("db/rules.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO rules (guild_id, channel_id, rules_text) VALUES (?, COALESCE((SELECT rules_text FROM rules WHERE guild_id = ?), NULL), NULL)",
                (ctx.guild.id, ctx.guild.id)
            )
            await db.execute("UPDATE rules SET channel_id = ? WHERE guild_id = ?", (channel.id, ctx.guild.id))
            await db.commit()

        embed = discord.Embed(title=f"{TICK}> Rules Channel Set", description=f"Rules will be posted in {channel.mention}.", color=0xFF0000)
        await ctx.send(embed=embed)

    @rules.command(name="post", aliases=["send"], help="Post the configured rules to the rules channel.")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 6, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def rules_post(self, ctx):
        async with aiosqlite.connect("db/rules.db") as db:
            async with db.execute("SELECT channel_id, rules_text FROM rules WHERE guild_id = ?", (ctx.guild.id,)) as cursor:
                row = await cursor.fetchone()

        if not row:
            error = discord.Embed(description="No rules configured. Use `rules set <text>` to set the rules first.", color=0xFF0000)
            return await ctx.send(embed=error)

        channel_id, rules_text = row
        channel = ctx.guild.get_channel(channel_id) if channel_id else None

        if not channel:
            error = discord.Embed(description="Rules channel not set. Use `rules channel <#channel>` to set one.", color=0xFF0000)
            return await ctx.send(embed=error)

        if not rules_text:
            error = discord.Embed(description="Rules text not set. Use `rules set <text>` to set the rules first.", color=0xFF0000)
            return await ctx.send(embed=error)

        embed = discord.Embed(title=f"{ctx.guild.name} — Server Rules", description=rules_text, color=0xFF0000, timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"Rules for {ctx.guild.name} | Set by {ctx.author.display_name}", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)

        try:
            await channel.send(embed=embed)
            await ctx.send(f"{ZTICK}> Rules posted to {channel.mention}.")
        except discord.Forbidden:
            await ctx.send(f"I don't have permission to send messages in {channel.mention}.")
        except Exception as e:
            await ctx.send(f"Failed to post rules: {e}")

    @rules.command(name="view", aliases=["show"], help="View the current rules configuration.")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 6, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def rules_view(self, ctx):
        async with aiosqlite.connect("db/rules.db") as db:
            async with db.execute("SELECT channel_id, rules_text FROM rules WHERE guild_id = ?", (ctx.guild.id,)) as cursor:
                row = await cursor.fetchone()

        if not row:
            error = discord.Embed(description="No rules configured for this server.", color=0xFF0000)
            return await ctx.send(embed=error)

        channel_id, rules_text = row
        channel = ctx.guild.get_channel(channel_id) if channel_id else None

        embed = discord.Embed(title=f"Rules Configuration — {ctx.guild.name}", color=0xFF0000)
        embed.add_field(name="Rules Channel", value=channel.mention if channel else "None", inline=False)
        embed.add_field(name="Rules Text", value=rules_text or "None", inline=False)
        await ctx.send(embed=embed)

    @rules.command(name="reset", aliases=["delete", "remove", "disable"], help="Reset and delete the rules configuration.")
    @blacklist_check()
    @ignore_check()
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 6, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def rules_reset(self, ctx):
        async with aiosqlite.connect("db/rules.db") as db:
            cursor = await db.execute("SELECT 1 FROM rules WHERE guild_id = ?", (ctx.guild.id,))
            exists = await cursor.fetchone()

        if not exists:
            error = discord.Embed(description="No rules configuration found for this server.", color=0xFF0000)
            return await ctx.send(embed=error)

        embed = discord.Embed(title="Are you sure?", description="This will delete all rules configuration for this server!", color=0xFF0000)

        yes_button = Button(label="Confirm", style=discord.ButtonStyle.danger)
        no_button = Button(label="Cancel", style=discord.ButtonStyle.secondary)

        async def yes_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("Only the command author can confirm this.", ephemeral=True)
                return
            async with aiosqlite.connect("db/rules.db") as db:
                await db.execute("DELETE FROM rules WHERE guild_id = ?", (ctx.guild.id,))
                await db.commit()
            embed.title = f"{TICK}> Rules Reset"
            embed.description = "Rules configuration has been deleted."
            await interaction.message.edit(embed=embed, view=None)

        async def no_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("Only the command author can cancel this.", ephemeral=True)
                return
            embed.title = "Cancelled"
            embed.description = "Rules reset cancelled."
            await interaction.message.edit(embed=embed, view=None)

        yes_button.callback = yes_callback
        no_button.callback = no_callback
        view = View()
        view.add_item(yes_button)
        view.add_item(no_button)
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Rules(bot))
