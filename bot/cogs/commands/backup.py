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
from core import Cog, zyrox, Context
from utils.emoji import SUCCESS, ERROR, TICK, CROSS, DENIED
from utils.config import OWNER_IDS, DEV_ID
from utils import db_backup


def developer_only():
    """Custom check that strictly allows only the bot developer/owners."""
    async def predicate(ctx: Context):
        allowed_ids = set(OWNER_IDS)
        if DEV_ID and str(DEV_ID).strip().isdigit():
            allowed_ids.add(int(DEV_ID))
        if ctx.author.id not in allowed_ids:
            embed = discord.Embed(
                title=f"{DENIED} Access Denied",
                description="❌ This command is strictly reserved for the **Bot Developer**.",
                color=0xFF0000
            )
            embed.set_footer(text=f"“{ctx.command.qualified_name}” attempted by {ctx.author}",
                             icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)
            return False
        return True
    return commands.check(predicate)


class Backup(Cog):
    """Commands to manage automated SQLite backups to Discord Webhook."""

    def __init__(self, bot: zyrox):
        self.bot = bot

    @commands.group(name="backup", invoke_without_command=True)
    @developer_only()
    async def backup_group(self, ctx: Context):
        """Shows current database backup status and available commands."""
        status = db_backup.get_status()
        embed = discord.Embed(
            title="📦 Database Backup & Persistence",
            color=0x2ECC71 if status["enabled"] else 0xE74C3C
        )

        status_text = "🟢 **Enabled**" if status["enabled"] else "🔴 **Disabled** (Set `DB_BACKUP_WEBHOOK_URL` in .env)"
        embed.add_field(name="Status", value=status_text, inline=False)
        embed.add_field(name="Interval", value=f"`{status['interval_seconds'] // 60}` minutes", inline=True)
        embed.add_field(name="Last Status", value=f"`{status['last_backup_status']}`", inline=True)

        if status.get("last_backup_time"):
            embed.add_field(
                name="Last Backup",
                value=f"{status['last_backup_time']} ({status['last_backup_files']} files, {status['last_backup_size_kb']} KB)",
                inline=False
            )

        if status.get("last_restore_time"):
            embed.add_field(
                name="Last Restore",
                value=f"{status['last_restore_time']} ({status['last_restore_files']} files restored)",
                inline=False
            )

        embed.add_field(
            name="Available Commands",
            value=(
                "`>backup now` — Force immediate database backup upload\n"
                "`>backup restore` — Download and restore latest backup\n"
                "`>backup status` — Detailed status of webhook channel"
            ),
            inline=False
        )
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @backup_group.command(name="now", aliases=["save", "create"])
    @developer_only()
    async def backup_now_cmd(self, ctx: Context):
        """Immediately captures and uploads a database backup archive to Discord."""
        msg = await ctx.send(f"⏳ Creating and uploading database snapshot...")
        result = await db_backup.backup_now(reason=f"Manual (>backup now by {ctx.author})", force=True)

        if result.get("success"):
            embed = discord.Embed(
                title=f"{SUCCESS} Backup Completed",
                description="Database files safely compressed and stored via Webhook.",
                color=0x2ECC71
            )
            embed.add_field(name="Archive", value=f"`{result.get('filename')}`", inline=True)
            embed.add_field(name="Files", value=f"`{result.get('files')} files`", inline=True)
            embed.add_field(name="Size", value=f"`{result.get('size_kb')} KB`", inline=True)
            embed.add_field(name="Hash", value=f"`{result.get('hash')}`", inline=True)
            await msg.edit(content=None, embed=embed)
        else:
            await msg.edit(content=f"{ERROR} Backup failed: `{result.get('reason')}`")

    @backup_group.command(name="restore", aliases=["load"])
    @developer_only()
    async def backup_restore_cmd(self, ctx: Context):
        """Downloads and restores the latest database backup from the Discord channel."""
        from utils.config import TOKEN
        msg = await ctx.send("⏳ Fetching latest backup from Discord and extracting...")
        result = await db_backup.restore_from_discord(bot_token=TOKEN, force=True)

        if result.get("success"):
            embed = discord.Embed(
                title=f"{SUCCESS} Database Restored",
                description=f"Successfully extracted `{result.get('files')}` database files from `{result.get('filename')}`.",
                color=0x2ECC71
            )
            await msg.edit(content=None, embed=embed)
        else:
            await msg.edit(content=f"{ERROR} Restore failed: `{result.get('reason')}`")

    @backup_group.command(name="status", aliases=["info"])
    @developer_only()
    async def backup_status_cmd(self, ctx: Context):
        """Shows detailed diagnostic information about the backup service."""
        status = db_backup.get_status()
        embed = discord.Embed(title="⚙️ Database Backup Diagnostics", color=0x3498DB)
        for k, v in status.items():
            embed.add_field(name=k, value=f"`{v}`", inline=True)
        await ctx.send(embed=embed)


async def setup(bot: zyrox):
    await bot.add_cog(Backup(bot))
