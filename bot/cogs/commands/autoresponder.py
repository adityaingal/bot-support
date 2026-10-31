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
from utils.emoji import CROSS, TICK
from discord.ext import commands
from discord.ui import LayoutView, TextDisplay, Separator, Container
import aiosqlite
import os
from utils.Tools import *
from utils.cache import cached_or_fetch, invalidate
from utils.cv2 import CV2, build_container





DB_PATH = "db/autoresponder.db"

class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.initialize_db())

    async def initialize_db(self):
        if not os.path.exists(os.path.dirname(DB_PATH)):
            os.makedirs(os.path.dirname(DB_PATH))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS autoresponses (
                    guild_id INTEGER,
                    name TEXT,
                    message TEXT,
                    PRIMARY KEY (guild_id, name)
                )
            ''')
            await db.commit()

    async def get_responses(self, guild_id):
        # One cached read per guild instead of a query on EVERY message.
        async def _fetch():
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT LOWER(name), message FROM autoresponses WHERE guild_id = ?",
                    (guild_id,),
                ) as cursor:
                    return dict(await cursor.fetchall())
        return await cached_or_fetch("autoresp", _fetch, guild_id, ttl=30.0)

    @commands.group(name="autoresponder", invoke_without_command=True, aliases=['ar'], help="Manage autoresponders in the server.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def _ar(self, ctx):
        if ctx.subcommand_passed is None:
            await ctx.send_help(ctx.command)
            ctx.command.reset_cooldown(ctx)

    @_ar.command(name="create", help="Create a new autoresponder.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_permissions(administrator=True)
    async def _create(self, ctx, name, *, message):
        name_lower = name.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM autoresponses WHERE guild_id = ?", (ctx.guild.id,)) as cursor:
                count = (await cursor.fetchone())[0]
                if count >= 20:
                    view = CV2(f"{CROSS} Error!", f"You can't add more than 20 autoresponses in {ctx.guild.name}")
                    return await ctx.reply(view=view)

            async with db.execute("SELECT 1 FROM autoresponses WHERE guild_id = ? AND LOWER(name) = ?", (ctx.guild.id, name_lower)) as cursor:
                if await cursor.fetchone():
                    view = CV2(f"{CROSS} Error!", f"The autoresponse with the name `{name}` already exists in {ctx.guild.name}")
                    return await ctx.reply(view=view)

            await db.execute("INSERT INTO autoresponses (guild_id, name, message) VALUES (?, ?, ?)", (ctx.guild.id, name_lower, message))
            await db.commit()
            invalidate("autoresp", ctx.guild.id)
            view = CV2(f"{TICK} Success", f"Created autoresponder `{name}` in {ctx.guild.name}")
            await ctx.reply(view=view)

    @_ar.command(name="delete", help="Delete an existing autoresponder.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_permissions(administrator=True)
    async def _delete(self, ctx, name):
        name_lower = name.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT 1 FROM autoresponses WHERE guild_id = ? AND LOWER(name) = ?", (ctx.guild.id, name_lower)) as cursor:
                if not await cursor.fetchone():
                    view = CV2(f"{CROSS} Error!", f"No autoresponder found with the name `{name}` in {ctx.guild.name}")
                    return await ctx.reply(view=view)

            await db.execute("DELETE FROM autoresponses WHERE guild_id = ? AND LOWER(name) = ?", (ctx.guild.id, name_lower))
            await db.commit()
            invalidate("autoresp", ctx.guild.id)
            view = CV2(f"{TICK} Success", f"Deleted autoresponder `{name}` in {ctx.guild.name}")
            await ctx.reply(view=view)

    @_ar.command(name="edit", help="Edit an existing autoresponder.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_permissions(administrator=True)
    async def _edit(self, ctx, name, *, message):
        name_lower = name.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT 1 FROM autoresponses WHERE guild_id = ? AND LOWER(name) = ?", (ctx.guild.id, name_lower)) as cursor:
                if not await cursor.fetchone():
                    view = CV2(f"{CROSS} Error!", f"No autoresponder found with the name `{name}` in {ctx.guild.name}")
                    return await ctx.reply(view=view)

            await db.execute("UPDATE autoresponses SET message = ? WHERE guild_id = ? AND LOWER(name) = ?", (message, ctx.guild.id, name_lower))
            await db.commit()
            invalidate("autoresp", ctx.guild.id)
            view = CV2(f"{TICK} Success", f"Edited autoresponder `{name}` in {ctx.guild.name}")
            await ctx.reply(view=view)

    @_ar.command(name="config", help="List all autoresponders in the server.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_permissions(administrator=True)
    async def _config(self, ctx):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name FROM autoresponses WHERE guild_id = ?", (ctx.guild.id,)) as cursor:
                autoresponses = await cursor.fetchall()

        if not autoresponses:
            view = CV2("No Autoresponders", f"There are no autoresponders in {ctx.guild.name}")
            return await ctx.reply(view=view)

        ar_list = "\n".join([f"**[{i}]** {name}" for i, (name,) in enumerate(autoresponses, start=1)])
        view = CV2(f"Autoresponders in {ctx.guild.name}", ar_list)
        await ctx.send(view=view)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return

        # Cached lookup: previously a DB query on EVERY message from EVERY
        # author (including other bots), in every guild.
        responses = await self.get_responses(message.guild.id)
        if not responses:
            return

        reply = responses.get(message.content.lower())
        if reply:
            await message.channel.send(reply)

async def setup(bot):
    await bot.add_cog(AutoResponder(bot))
