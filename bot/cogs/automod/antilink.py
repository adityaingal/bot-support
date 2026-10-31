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
from utils.emoji import TICK
from discord.ext import commands
import aiosqlite
import asyncio
from datetime import timedelta
import re
from utils import automod_cache

class AntiLink(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.link_pattern = re.compile(r'http[s]?://\S+')
        self.invite_pattern = re.compile(r'(https?://)?(www\.)?(discord\.(gg|io|me|li)|discordapp\.com/invite)/\S+')
        self.gif_pattern = re.compile(r'(\.gif$|^https://(tenor\.com|giphy\.com/gifs|cdn\.discordapp\.com|media\.discordapp\.net))')
        self.spotify_pattern = re.compile(r'^https://open\.spotify\.com/track/\S+')

    async def is_automod_enabled(self, guild_id):
        return await automod_cache.is_automod_enabled(guild_id)

    async def is_anti_link_enabled(self, guild_id):
        return await automod_cache.is_module_enabled(guild_id, 'Anti link')

    async def get_ignored_channels(self, guild_id):
        return await automod_cache.get_ignored_channels(guild_id)

    async def get_ignored_roles(self, guild_id):
        return await automod_cache.get_ignored_roles(guild_id)

    async def get_punishment(self, guild_id):
        return await automod_cache.get_punishment(guild_id, 'Anti link')

    async def log_action(self, guild, user, channel, action, reason):
        async with aiosqlite.connect("db/automod.db") as db:
            cursor = await db.execute("SELECT log_channel FROM automod_logging WHERE guild_id = ?", (guild.id,))
            log_channel_id = await cursor.fetchone()

        if log_channel_id and log_channel_id[0]:
            log_channel = guild.get_channel(log_channel_id[0])
            if log_channel:
                embed = discord.Embed(title="Automod Log: Anti-Link", color=0xFF0000)
                embed.add_field(name="User", value=user.mention, inline=False)
                embed.add_field(name="Action", value=action, inline=False)
                embed.add_field(name="Channel", value=channel.mention, inline=False)
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.set_footer(text=f"User ID: {user.id}")
                avatar_url = user.avatar.url if user.avatar else user.default_avatar.url
                embed.set_thumbnail(url=avatar_url)
                embed.timestamp=discord.utils.utcnow()
                await log_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return

        guild = message.guild
        user = message.author
        channel = message.channel
        guild_id = guild.id

        if not await self.is_automod_enabled(guild_id) or not await self.is_anti_link_enabled(guild_id):
            return

        if user == guild.owner or user == self.bot.user:
            return

        ignored_channels = await self.get_ignored_channels(guild_id)
        if channel.id in ignored_channels:
            return

        ignored_roles = await self.get_ignored_roles(guild_id)
        if any(role.id in ignored_roles for role in user.roles):
            return

        if self.link_pattern.search(message.content):
            if self.invite_pattern.search(message.content):
                return
            if self.gif_pattern.search(message.content): 
                return
            if self.spotify_pattern.search(message.content):
                return

            punishment = await self.get_punishment(guild_id)
            action_taken = None
            reason = "Posted a link"

            try:
                if punishment == "Mute":
                    timeout_duration = discord.utils.utcnow() + timedelta(minutes=7)
                    await user.edit(timed_out_until=timeout_duration, reason=reason)
                    action_taken = "Muted for 7 minutes"
                elif punishment == "Kick":
                    await user.kick(reason=reason)
                    action_taken = "Kicked"
                elif punishment == "Ban":
                    await user.ban(reason=reason)
                    action_taken = "Banned"
                await message.delete()

                simple_embed = discord.Embed(title="Automod Anti-Link", color=0xFF0000)
                simple_embed.description = f"{TICK} | {user.mention} has been successfully **{action_taken}** for **Posting a link.**"
                
                simple_embed.set_footer(text="Use the “automod logging” command to get automod logs if it is not enabled.", icon_url=self.bot.user.avatar.url)
                await channel.send(embed=simple_embed, delete_after=30)

                await self.log_action(guild, user, channel, action_taken, reason)

            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_rate_limit(self, message):
        await asyncio.sleep(10)
