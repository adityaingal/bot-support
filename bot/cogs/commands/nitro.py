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
from discord.ui import Button, View


class Nitro(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Removed the on_message get_context()+invoke() here: the bot's default
    # process_commands already parses every message (mention is a valid
    # prefix), so this was executing the nitro command a SECOND time.

    @commands.command(name="nitro")
    async def nitro(self, ctx):
        embed = discord.Embed(color=0x2B2D31)
        embed.add_field(
            name="A WILD NITRO GIFT APPEARS?",
            value="Expires in 12 hours\n\nClick the claim button for claiming Nitro",
            inline=False,
        )
        embed.set_image(
            url="https://media.tenor.com/ltVe8iMhgXcAAAAS/nitro-discord.gif"
        )

        claim_button = Button(
            style=discord.ButtonStyle.primary,
            label="Click me!",
            url="https://discord.gg/UVRWygSpJq",
            disabled=False,
        )

        view = View()
        view.add_item(claim_button)

        await ctx.send(embed=embed, view=view)
