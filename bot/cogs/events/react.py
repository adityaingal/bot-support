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
from utils.emoji import ACTIVE_DEVELOPER, BLACKCROWN, MINGLE, STAFF
from discord.ext import commands
from utils.config import OWNER_IDS
import asyncio

class React(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        for owner in self.bot.owner_ids:
            if f"<@{owner}>" in message.content:
                try:
                    # Primary owner (first in OWNER_IDS) gets an extra emoji
                    if owner == OWNER_IDS[0]:
                        emojis = [
                            BLACKCROWN,
                            ACTIVE_DEVELOPER,
                            STAFF,
                            MINGLE,
                        ]
                    else:
                        emojis = [
                            BLACKCROWN,
                            ACTIVE_DEVELOPER,
                            STAFF,
                        ]

                    # Adding several reactions back-to-back hits Discord's
                    # per-route limit (429 spam in the logs), so pace them.
                    for index, emoji in enumerate(emojis):
                        try:
                            await message.add_reaction(emoji)
                        except discord.errors.RateLimited as e:
                            await asyncio.sleep(e.retry_after + 0.5)
                        except discord.HTTPException:
                            pass  # ignore if emoji is invalid or not accessible
                        if index != len(emojis) - 1:
                            await asyncio.sleep(0.75)

                except discord.errors.RateLimited as e:
                    await asyncio.sleep(e.retry_after)
                except Exception as e:
                    print(f"An unexpected error occurred Auto react owner mention: {e}")