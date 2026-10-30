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
from utils.emoji import BLOBPART
from discord.ext import commands
from utils.cv2 import CV2
from utils.jsonio import load_json, save_json

class joindm(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.joindm_messages = {}
        self.load_joindm_messages()

    def load_joindm_messages(self):
        # Load the join DM messages from file
        self.joindm_messages = load_json('jsondb/joindm_messages.json')

    def save_joindm_messages(self):
        # Save the join DM messages to file
        save_json('jsondb/joindm_messages.json', self.joindm_messages)

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def joindm(self, ctx):
        # Display the current join DM message
        guild_id = str(ctx.guild.id)
        if guild_id in self.joindm_messages:
            await ctx.send(view=CV2("✅ Join DM Status", f"The current join DM message is:\n`{self.joindm_messages[guild_id]}`"))
        else:
            await ctx.send(view=CV2("❌ Error", "No custom join DM message has been set for this server."))

    @joindm.command()
    @commands.has_permissions(administrator=True)
    async def message(self, ctx, *, message=None):
        # Set the custom join DM message
        if message is None:
            await ctx.send(view=CV2("❌ Error", "Please provide a custom join DM message."))
        else:
            self.joindm_messages[str(ctx.guild.id)] = message
            self.save_joindm_messages()
            await ctx.send(view=CV2("✅ Success", "Custom join DM message set successfully."))

    @joindm.command()
    @commands.has_permissions(administrator=True)
    async def enable(self, ctx):
        # Enable the join DM module
        self.bot.add_listener(self.on_member_join, 'on_member_join')
        await ctx.send(view=CV2("✅ Success", "Join DM module enabled. Custom DM will be sent to new members."))

    @joindm.command()
    @commands.has_permissions(administrator=True)
    async def disable(self, ctx):
        # Disable the join DM module
        self.bot.remove_listener(self.on_member_join)
        await ctx.send(view=CV2("✅ Success", "Join DM module disabled. Custom DM will not be sent to new members."))

    @joindm.command()
    async def test(self, ctx):
        # Send a test join DM to the author of the command
        guild_id = str(ctx.guild.id)
        if guild_id in self.joindm_messages:
            message = self.joindm_messages[guild_id]
            server_name = ctx.guild.name
            join_dm_message = f"{message}\n\n ``Sent from {server_name} `` "
            await ctx.send(view=CV2("✅ Test Sent", "Test Join DM Sent To Your Dm"))
            await ctx.message.add_reaction(BLOBPART)
            await ctx.author.send(view=CV2("👋 Welcome", join_dm_message))
        else:
            await ctx.send(view=CV2("❌ Error", "No custom join DM message has been set for this server."))

    async def on_member_join(self, member):
        
        guild_id = str(member.guild.id)
        if guild_id in self.joindm_messages:
            message = self.joindm_messages[guild_id]
            dm_channel = await member.create_dm()
            server_name = member.guild.name
            join_dm_message = f"{message}\n\n``Sent from {server_name} ``"
            await dm_channel.send(view=CV2("👋 Welcome", join_dm_message))

async def setup(bot):
    await bot.add_cog(joindm(bot))
