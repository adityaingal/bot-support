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
from discord.ext import commands
import urllib.parse
import urllib.request
import re
import asyncio

class Youtube(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @commands.command(name='yt', aliases=['youtube'])
    async def search_youtube(self, ctx, *, search_query):
        query_string = urllib.parse.urlencode({'search_query': search_query})
        html_content = await asyncio.to_thread(
            urllib.request.urlopen, 'http://www.youtube.com/results?' + query_string
        )
        raw_html = await asyncio.to_thread(html_content.read)
        search_results = re.findall(r"watch\?v=(\S{11})", raw_html.decode())
        if len(search_results) > 0:
            result_message = f"**▶ | Here are your search results:- https://www.youtube.com/watch?v={search_results[0]} **"
            await ctx.send(result_message)
        else:
            await ctx.send('No search results found.')