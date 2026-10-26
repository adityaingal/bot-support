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

import os
import sys
import signal
import subprocess
# os.system("")
import asyncio
import traceback
from threading import Thread
from datetime import datetime
import random
import socket
import time

# Logging must never be able to crash the process. Render logs are UTF-8, but
# a redirected/CI stdout can fall back to a legacy codec that cannot encode the
# symbols used in the log messages below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# --- Structured logging (Render captures stdout/stderr) ---
def _emit(text: str) -> None:
    try:
        print(text, flush=True)
    except Exception:
        try:
            sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def log_info(message: str) -> None:
    _emit(f"INFO  - {message}")


def log_warning(message: str) -> None:
    _emit(f"WARNING - {message}")


def log_error(message: str) -> None:
    _emit(f"ERROR - {message}")


def _startup_banner() -> None:
    _emit("=" * 40)
    _emit("SUPPORT BOT")
    _emit("=" * 40)


# --- Environment + TOKEN validation (fail fast, before anything else starts) ---
from dotenv import load_dotenv
load_dotenv()

_startup_banner()
log_info("Starting Support...")

if not (os.getenv("TOKEN") or "").strip():
    log_error("TOKEN environment variable is missing.")
    log_error("Configure TOKEN in Render Environment Variables.")
    log_error("Support failed to start. Reason: no Discord bot token configured.")
    raise SystemExit(1)


def _setup_persistent_db() -> None:
    """On Render, redirect the relative db/ directory onto a persistent Disk.

    Every cog opens its SQLite files via a relative path like ``db/anti.db``.
    Render's filesystem is ephemeral: anything written under the checkout is
    wiped on each deploy/restart (and on free-tier wake-from-sleep). When a
    Render Disk is mounted, setting RENDER_DISK_PATH to its mount point makes
    this swap the local ``db`` folder for a symlink onto the disk, so all 36
    SQLite files survive redeploys. No-op when RENDER_DISK_PATH is unset
    (local dev, or a plan without disks).
    """
    disk = (os.getenv("RENDER_DISK_PATH") or "").strip()
    if not disk:
        return
    import shutil

    target = os.path.join(disk, "db")
    local = os.path.join(os.getcwd(), "db")
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        log_warning(f"Persistent db: could not create {target}: {e!r}")
        return

    # Already linked to the disk?
    try:
        if os.path.islink(local) and os.path.realpath(local) == os.path.realpath(target):
            return
    except OSError:
        pass

    # First boot: seed the disk from any files already in the checkout.
    try:
        if os.path.isdir(local) and not os.path.islink(local):
            for name in os.listdir(local):
                src = os.path.join(local, name)
                dst = os.path.join(target, name)
                if os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
    except Exception as e:
        log_warning(f"Persistent db: seed failed: {e!r}")

    # Swap the ephemeral folder for a symlink onto the disk. Renames the
    # original aside first and restores it if the symlink fails (e.g. Windows
    # without Developer Mode), so a failed swap never loses the db/ folder.
    bak = local + ".__persist_bak"
    try:
        if os.path.isdir(local) and not os.path.islink(local):
            if os.path.exists(bak):
                shutil.rmtree(bak, ignore_errors=True)
            os.rename(local, bak)
        elif os.path.exists(local) and not os.path.islink(local):
            os.remove(local)
        os.symlink(target, local, target_is_directory=True)
    except Exception as e:
        # Roll the original folder back into place.
        try:
            if not os.path.exists(local) and os.path.isdir(bak):
                os.rename(bak, local)
        except OSError:
            pass
        log_warning(f"Persistent db: could not link {local} -> {target}: {e!r}")
        return

    # Success: drop the backup copy.
    try:
        if os.path.isdir(bak):
            shutil.rmtree(bak, ignore_errors=True)
    except OSError:
        pass
    log_info(f"Persistent db enabled -> {target}")


_setup_persistent_db()


def _enforce_python_version() -> None:
    """Refuse to start on untested Python versions (Render may default newest).

    discord.py 2.7.1 + aiohttp are verified on 3.11–3.13. On 3.14+ the Discord
    login fails deterministically with ``RuntimeError: Session is closed`` on
    every attempt, and retrying only earns a Cloudflare rate-limit. Fail fast
    with an actionable message instead.
    """
    v = sys.version_info
    if v >= (3, 14):
        log_error(
            f"Unsupported Python {v.major}.{v.minor}.{v.micro}. discord.py 2.7.1 + aiohttp "
            "fail login with 'Session is closed' on Python 3.14+. "
            "Set the PYTHON_VERSION env var to 3.11 and redeploy."
        )
        raise SystemExit(1)


_enforce_python_version()

log_info("Loading configuration...")

import aiohttp
import aiosqlite
import weakref
import discord
try:
    from discord import Spotify
except ImportError:
    try:
        from discord.activity import Spotify
    except ImportError:
        Spotify = getattr(discord, "Spotify", None)
from discord.ext import commands, tasks
from discord.utils import MISSING

# aiosqlite runs every query on a dedicated *non-daemon* thread that only
# stops when the connection is closed. Any connection left open (cogs, API
# routes) would keep the interpreter alive after shutdown, so every connection
# opened by this process is tracked here and closed during shutdown.
# A WeakSet keeps connections that are closed and released from piling up.
_aiosqlite_connections: weakref.WeakSet = weakref.WeakSet()
_aiosqlite_connect = aiosqlite.connect


def _tracked_aiosqlite_connect(*args, **kwargs):
    # aiosqlite.connect() returns the connection proxy synchronously (it can be
    # awaited or used with `async with`), so this wrapper must stay synchronous
    # and return that same object.
    connection = _aiosqlite_connect(*args, **kwargs)
    try:
        _aiosqlite_connections.add(connection)
    except TypeError:
        pass
    return connection


aiosqlite.connect = _tracked_aiosqlite_connect

from core import Context
from core.Cog import Cog
from core.zyrox import zyrox, ExtensionLoadError
from utils.Tools import *
from utils.config import *
from utils.emoji import SUCCESS, ERROR, TICK, CROSS, REACTION_TEST_EMOJIS
from utils.sync_emojis import run_sync
from utils import keepalive
from utils import db_backup
from utils.http import http_client, describe_http_failure, log_discord_once
from utils import cloudbreaker
from utils.cloudbreaker import CloudflareBanError

cloudbreaker.install()

# Reuse a small set of persistent aiosqlite connections instead of spawning a
# new worker thread + file open for every query. Each message used to open
# ~40-60 connections (get_prefix, automod listeners, blacklist checks, ...),
# which dominated response latency. Installed AFTER the tracking patch above so
# pooled connections are still registered and closed during shutdown. The
# `utils.dbpool` import is deferred until after core/utils are loaded to avoid
# a circular import during package bootstrap.
from utils.dbpool import install as _install_dbpool

_install_dbpool(aiosqlite)

import jishaku
import cogs


os.environ["JISHAKU_NO_DM_TRACEBACK"] = "False"
os.environ["JISHAKU_HIDE"] = "True"
os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
os.environ["JISHAKU_FORCE_PAGINATOR"] = "True"

# Always prefer the value handed out by the process environment (Render) and
# never allow a committed file to silently provide a token.
TOKEN = (os.getenv("TOKEN") or "").strip()

log_info("Loading configuration... done")

# --- Configuration ---
# IMPORTANT: Replace these with your actual channel IDs.
SERVER_COUNT_CHANNEL_ID = 1419729255977189467  # Replace with your server count channel ID
USER_COUNT_CHANNEL_ID = 1419729283861184632    # Replace with your user count channel ID
LOG_CHANNEL_ID = 1396794297386532978 # Replace with the channel ID for join/leave logs

# Bounded startup retries for *recoverable* failures only (network/DNS/rate
# limit). Fatal errors (bad token, missing intents, failed cog load) exit
# immediately so the problem stays visible instead of being retried forever.
MAX_START_ATTEMPTS = 7
# A 429/Cloudflare block during login lasts far longer than a normal connect
# failure, and every process restart renews it. For rate limits we do NOT use
# MAX_START_ATTEMPTS: we stay in this process and escalate the cooldown
# (120s -> 1800s, up to MAX_RATE_LIMIT_WAITS waits ~= 13 hours) so Render
# never restarts the service and the block has time to expire. Cloudflare IP
# blocks from repeated logins routinely last many hours — retrying faster (or
# exiting and letting Render restart us) only renews them. Beyond the last
# wait the process does NOT exit: it keeps retrying every RATE_LIMIT_MAX_WAIT
# forever (phase "blocked") because a Render restart would reset the ladder
# back to 120s and renew the block.
MAX_RATE_LIMIT_WAITS = 30
RATE_LIMIT_BASE_WAIT = 120.0
RATE_LIMIT_MAX_WAIT = 1800.0
# Ceiling for honouring a 429's Retry-After. Must exceed any real Discord/CF
# block (they routinely run 4h+); waking early renews the block, so a cap
# below Retry-After turns a 4h outage into an endless one.
RATE_LIMIT_RETRY_AFTER_CAP = 21600.0
SHUTDOWN_TIMEOUT = 20  # seconds to wait for a running shutdown before moving on

# Live startup state, published on /api/status (one HTTP GET beats digging
# through Render logs while the bot is not yet online).
startup_state = {"phase": "init", "attempt": 0, "last_error": None, "next_retry_in": None}


def _set_startup(**kwargs) -> None:
    try:
        startup_state.update(kwargs)
        startup_state["updated"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    except Exception:
        pass


def _rate_limit_headers(exc) -> dict:
    """Readable subset of a 429's response headers (never the body).

    Retry-After says exactly how long the block lasts; Via/CF-RAY tell a
    Cloudflare edge block apart from a normal Discord bucket limit.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        return {}
    out = {}
    for key in ("Retry-After", "Via", "CF-RAY", "CF-Cache-Status"):
        value = headers.get(key)
        if value:
            out[key] = value
    return out


async def _discord_blocked_over(family: int) -> bool:
    """True when discord.com cannot be usefully reached with this address family.

    Escape hatch for edge blocks: if the default (IPv4) route is blocked but
    IPv6 still answers normally, login can be forced over IPv6.
    """
    label = "IPv6" if family == socket.AF_INET6 else "IPv4"
    try:
        conn = aiohttp.TCPConnector(family=family, limit=1)
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout) as probe:
            async with probe.get(
                "https://discord.com/api/v10/users/@me",
                headers={"User-Agent": "DiscordBot (https://discord.com, 2.0) Python/3.11 aiohttp/3.9"},
            ) as resp:
                text = await resp.text()
                blocked = resp.status == 429 or "<html" in text.lower()
                log_info(f"[netcheck] discord.com over {label}: HTTP {resp.status} "
                         f"({'BLOCKED' if blocked else 'ok'})")
                return blocked
    except Exception as e:
        log_warning(f"[netcheck] discord.com over {label} unreachable: {type(e).__name__}: {e}")
        return True


client = zyrox()
tree = client.tree

# --- One-shot startup guards -------------------------------------------------
# Discord fires on_ready again after every gateway reconnect, so every startup
# side effect below must run exactly once per process (no duplicate tasks).
_ready_done = False
_stats_task = None
_sync_task = None

# --- Background Task for Stats ---
async def update_stats():
    """A background task to update server and user stats in channel names."""
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            servers = len(client.guilds)
            users = sum(guild.member_count for guild in client.guilds if guild.member_count is not None)
            
            server_channel = client.get_channel(SERVER_COUNT_CHANNEL_ID)
            user_channel = client.get_channel(USER_COUNT_CHANNEL_ID)
            
            if server_channel:
                await server_channel.edit(name=f"Servers: {servers}")
            
            if user_channel:
                await user_channel.edit(name=f"Users: {users}")
                
        except Exception as e:
            log_warning(f"Stats update skipped: {e!r}")
        
        await asyncio.sleep(1800) # Update every 30 minutes


async def sync_commands():
    """Sync the application command tree (once per process)."""
    try:
        synced = await client.tree.sync()
        all_commands = list(client.commands)
        log_info(f"Synced {len(all_commands)} prefix commands and {len(synced)} slash commands")
    except Exception as e:
        log_warning(f"Command tree sync failed: {e!r}")


# --- Event Handlers ---
@client.event
async def on_connect():
    log_info("Discord connected")


@client.event
async def on_disconnect():
    log_warning("Discord gateway disconnected; waiting for automatic reconnect...")


@client.event
async def on_resumed():
    log_info("Discord session resumed successfully.")


@client.event
async def on_error(event_method, *args, **kwargs):
    # Never let an exception inside one event handler take the bot down;
    # technical details stay in the Render logs, never in Discord.
    exc_type, exc, tb = sys.exc_info()
    log_error(f"Unhandled event exception in {event_method}: {exc!r}")
    if tb is not None:
        traceback.print_exception(exc_type, exc, tb)


@client.event
async def on_ready():
    global _ready_done, _stats_task, _sync_task

    if _ready_done:
        # Reconnect: the gateway is back, nothing to restart.
        log_info("Discord session resumed; bot is ready again.")
        return
    _ready_done = True

    print("""
        \033[1;31m
 ██████╗ ██████╗ ██████╗ ███████╗██╗  ██╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗██╔╝
██║     ██║   ██║██║  ██║█████╗   ╚███╔╝ 
██║     ██║   ██║██║  ██║██╔══╝   ██╔██╗ 
╚██████╗╚██████╔╝██████╔╝███████╗██╔╝ ██╗
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
        \033[0m
       """)

    log_info("Support is online.")
    log_info("Discord connection established.")
    log_info(f"Logged in as: {client.user}")
    log_info(f"Connected to {len(client.guilds)} guilds")
    log_info(f"Connected to {len(client.users)} users")
    _set_startup(phase="ready", last_error=None, next_retry_in=None, attempt=0)

    # Sync application emojis on startup (never let this kill on_ready)
    try:
        await run_sync(TOKEN)
    except Exception as e:
        log_warning(f"Emoji sync skipped/failed: {e!r}")

    # Started exactly once per process — on_ready can fire again on reconnect.
    _sync_task = asyncio.create_task(sync_commands(), name="support:sync_commands")
    _stats_task = asyncio.create_task(update_stats(), name="support:update_stats")
    try:
        db_backup.start(client)
    except Exception as e:
        log_warning(f"Database backup task start failed: {e!r}")
    log_info("Background tasks started.")


@client.event
async def on_guild_join(guild: discord.Guild):
    # Log when the bot joins a server
    log_channel = client.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"{BRAND_NAME} has been added to the server: **{guild.name}** (ID: `{guild.id}`)")

@client.event
async def on_command_completion(context: commands.Context) -> None:
    if context.author.id in OWNER_IDS:
        return

    full_command_name = context.command.qualified_name
    split = full_command_name.split("\n")
    executed_command = str(split[0])
    webhook_url = (CMD_WEBHOOK_URL or "").strip()
    # Skip when no real webhook is configured — a placeholder URL would raise on every command
    if not webhook_url or not webhook_url.rstrip("/").split("/")[-1].isdigit():
        return
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(webhook_url, session=session)

        embed_color = 0xFF0000
        embed = discord.Embed(color=embed_color)
        avatar_url = context.author.display_avatar.url

        embed.set_author(name=f"Cmd Executed: {executed_command}", icon_url=avatar_url)
        embed.set_thumbnail(url=avatar_url)

        if context.guild is not None:
            embed.add_field(name="User", value=f"{context.author.mention} (`{context.author.id}`)", inline=False)
            embed.add_field(name="Server", value=f"{context.guild.name} (`{context.guild.id}`)", inline=False)
            embed.add_field(name="Channel", value=f"{context.channel.mention} (`{context.channel.id}`)", inline=False)
        else:
            embed.add_field(name="User (DM)", value=f"{context.author.mention} (`{context.author.id}`)", inline=False)
        
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"{BRAND_NAME} Development™ ❤️", icon_url=client.user.display_avatar.url)
        
        try:
            await webhook.send(embed=embed)
        except discord.HTTPException as e:
            # Never dump the body (429s here can be a Cloudflare HTML page)
            # and never retry - the command already succeeded.
            log_discord_once(
                f"cmd-webhook-{getattr(e, 'status', 0)}",
                f"command-log webhook: {describe_http_failure(e)} - not retrying",
            )
        except Exception as e:
            log_discord_once(
                f"cmd-webhook-{type(e).__name__}",
                f"command-log webhook failed: {type(e).__name__}",
            )


# --- Utility Commands ---
@client.command(name='spotify')
async def spotify(ctx: Context, user: discord.Member = None):
    """Shows what a user is listening to on Spotify."""
    user = user or ctx.author
    spotify_activity = next((activity for activity in user.activities if Spotify and isinstance(activity, Spotify)), None)

    if not spotify_activity:
        return await ctx.send(f"{user.name} is not listening to Spotify.")
    
    embed = discord.Embed(
        title=f"{user.name}'s Spotify",
        description=f"**Listening to:** {spotify_activity.title}",
        color=0x1DB954 # Spotify Green
    )
    embed.set_thumbnail(url=spotify_activity.album_cover_url)
    embed.add_field(name="Artist", value=spotify_activity.artist)
    embed.add_field(name="Album", value=spotify_activity.album)
    embed.set_footer(text=f"Song started at {spotify_activity.created_at.strftime('%H:%M')}")
    await ctx.send(embed=embed)


@client.command(name='makeinvite', aliases=['createinvite', 'makeinv'])
@commands.is_owner()
async def make_invite(ctx: Context, guild_id: int = None):
    """Creates an invite for a specified server (owner only)."""
    if guild_id is None:
        return await ctx.send("Please provide a Guild ID.")
        
    guild = client.get_guild(guild_id)
    if not guild:
        return await ctx.send("Invalid Guild ID. I am not in that server.")

    if guild.system_channel and guild.system_channel.permissions_for(guild.me).create_instant_invite:
        try:
            invite = await guild.system_channel.create_invite(max_age=0, max_uses=0, unique=True, reason="Owner requested invite.")
            return await ctx.send(f"Invite for **{guild.name}**:\n{invite.url}")
        except Exception:
            pass

    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).create_instant_invite:
            try:
                invite = await channel.create_invite(max_age=0, max_uses=0, unique=True, reason="Owner requested invite.")
                return await ctx.send(f"Invite for **{guild.name}** (from #{channel.name}):\n{invite.url}")
            except Exception:
                continue
                
    await ctx.send(f"I don't have 'Create Instant Invite' permission in any channel in **{guild.name}**.")


# --- Webhook Management Commands ---
@client.command(name='create_hook', aliases=['makehook'])
@commands.has_permissions(administrator=True)
async def create_hook(ctx: Context, *, name: str = None):
    """Creates a webhook in the current channel."""
    if name is None:
        return await ctx.send("Please provide a name for the webhook.")
    
    try:
        webhook = await ctx.channel.create_webhook(name=name, reason=f"Created by {ctx.author}")
        embed = discord.Embed(
            title=f"{SUCCESS} Webhook Created",
            description=f"A webhook named **{webhook.name}** was created.",
            color=0xFF0000
        )
        try:
            await ctx.author.send(f"Webhook URL for **{webhook.name}** in **{ctx.channel.name}**:\n||{webhook.url}||", embed=embed)
            await ctx.send("Webhook created. I've sent the URL to your DMs.")
        except Exception:
            await ctx.send(f"Webhook created: **{webhook.name}**\n||{webhook.url}||\n(I could not DM you the URL.)")
    except discord.Forbidden:
        await ctx.send("I don't have permission to create webhooks here.")
    except Exception as e:
        await ctx.send(f"{ERROR} Failed to create webhook: `{e}`")


@client.command(name='delete_hook', aliases=['delhook'])
@commands.has_permissions(administrator=True)
async def delete_hook(ctx: Context, webhook_url: str = None):
    """Deletes a webhook using its URL."""
    if webhook_url is None:
        return await ctx.send("Please provide the webhook URL to delete.")

    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(webhook_url, session=session)
            await webhook.delete(reason=f"Deleted by {ctx.author}")
        await ctx.send(f"{SUCCESS} Webhook deleted successfully.")
    except (discord.NotFound, ValueError):
        await ctx.send(f"{ERROR} Webhook not found or URL is invalid.")


@client.command(name='list_hooks', aliases=['hooks'])
@commands.has_permissions(administrator=True)
async def list_hooks(ctx: Context):
    """Lists all webhooks in the current channel."""
    try:
        webhooks = await ctx.channel.webhooks()
        if not webhooks:
            return await ctx.send("No webhooks found in this channel.")

        embed = discord.Embed(title=f"Webhooks in #{ctx.channel.name}", color=0xFF0000)
        description = "\n".join([f"**Name:** {wh.name} | **ID:** `{wh.id}`" for wh in webhooks])
        embed.description = description
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("I don't have permission to view webhooks in this channel.")


# --- Game Command ---
@client.command()
async def reaction(ctx: Context):
    """See how fast you can react to the correct emoji."""
    emojis = ["🍪", "🎉", "🧋", "🍒", "🍑", "💸", "🌙", "💕"]
    correct_emoji = random.choice(emojis)
    random.shuffle(emojis)
    
    embed = discord.Embed(
        title="Reaction Test",
        description="I will show an emoji in a few seconds. Get ready to click it!",
        color=0xFF0000
    )
    message = await ctx.send(embed=embed)
    
    for emoji in emojis:
        await message.add_reaction(emoji)
        
    await asyncio.sleep(random.uniform(2.0, 7.0))
    
    embed.description = f"**GET THE {correct_emoji} EMOJI!**"
    await message.edit(embed=embed)
    start_time = time.time()

    def check(reaction, user):
        return (
            reaction.message.id == message.id
            and str(reaction.emoji) == correct_emoji
            and user == ctx.author
        )

    try:
        reaction, user = await client.wait_for("reaction_add", timeout=15.0, check=check)
        end_time = time.time()
        reaction_time = end_time - start_time
        
        embed.description = f"{user.mention} got the {correct_emoji} in **{reaction_time:.2f} seconds**!"
        await message.edit(embed=embed)
    except asyncio.TimeoutError:
        embed.description = "Timeout! You were too slow."
        await message.edit(embed=embed)


# ---API Server for Dashboard Backend ---
import uvicorn
from threading import Thread
from api.server import create_app
from api.dependencies import set_bot

fastapi_app = create_app()
fastapi_app.state.bot = client
fastapi_app.state.startup = startup_state
set_bot(client)

API_ENABLED = os.getenv("API_ENABLED", "true").strip().lower() == "true"
# Render assigns $PORT to every web service — it always wins when present.
API_PORT = int(os.getenv("PORT") or os.getenv("API_PORT") or "8000")
os.environ["API_PORT"] = str(API_PORT)  # keep utils.tunnel pointed at the same port

api_server = None

def run_api():
    global api_server
    config = uvicorn.Config(app=fastapi_app, host='0.0.0.0', port=API_PORT, log_level="warning")
    server = uvicorn.Server(config)
    api_server = server
    try:
        server.run()
    except Exception as e:
        log_error(f"API server stopped unexpectedly: {e!r}")

def keep_alive():
    if not API_ENABLED:
        log_warning("API server disabled via API_ENABLED=false")
        return
    log_info(f"API server starting on port {API_PORT}")
    Thread(target=run_api, daemon=True, name="support:api").start()

keep_alive()

# --- Cloudflare Tunnel (HTTPS for API) ---
from utils.tunnel import start_tunnel
start_tunnel()

# --- Graceful shutdown (Render sends SIGTERM on deploy/stop) ---
_shutdown_started = False
_shutdown_task = None

async def shutdown(reason: str) -> None:
    """Stop background work, the API server, the gateway and open DB connections.

    Safe to call from several places (signal handler, ``main``): only the first
    caller performs the cleanup, everybody else waits for it so the process
    never exits while cleanup is still running.
    """
    global _shutdown_started, _shutdown_task

    current = asyncio.current_task()
    if _shutdown_task is not None:
        if _shutdown_task is current:
            return
        try:
            await asyncio.wait_for(asyncio.shield(_shutdown_task), timeout=SHUTDOWN_TIMEOUT)
        except asyncio.TimeoutError:
            log_warning("Timed out waiting for the running shutdown to finish.")
        except Exception as e:
            log_warning(f"Waiting for the running shutdown failed: {e!r}")
        return

    _shutdown_task = current
    _shutdown_started = True
    log_info(f"Shutting down: {reason}")

    for task in (_stats_task, _sync_task):
        if task is not None and not task.done():
            task.cancel()

    # Final database backup before closing connections
    try:
        db_backup.stop()
        if db_backup.is_enabled():
            await db_backup.backup_now(reason=f"shutdown ({reason})")
    except Exception as e:
        log_warning(f"Final database backup on shutdown failed: {e!r}")

    if api_server is not None:
        try:
            api_server.should_exit = True
        except Exception as e:
            log_warning(f"Could not stop API server cleanly: {e!r}")

    try:
        if not client.is_closed():
            await client.close()
    except Exception as e:
        log_error(f"Error while closing Discord connection: {e!r}")

    # Every aiosqlite connection owns a non-daemon worker thread; leaving any
    # of them open would hang the process after the gateway is gone.
    open_connections = list(_aiosqlite_connections)
    for connection in open_connections:
        try:
            await connection.close()
        except Exception as e:
            log_warning(f"Could not close a database connection: {e!r}")
    _aiosqlite_connections.clear()
    if open_connections:
        log_info(f"Closed {len(open_connections)} database connection(s).")

    # Stop the health checker first, then close every aiohttp session
    # (shared client, cogs that registered theirs, owner.py's client.session)
    # so the process never logs "Unclosed client session".
    try:
        await keepalive.stop()
    except Exception as e:
        log_warning(f"Could not stop KeepAlive cleanly: {e!r}")

    extra_session = getattr(client, "session", None)
    if extra_session is not None and hasattr(extra_session, "close") \
            and not getattr(extra_session, "closed", True):
        try:
            await extra_session.close()
        except Exception:
            pass

    # Lavalink: Pool.close() tears down websockets/players but leaves each
    # Node's aiohttp session open, so close those sessions too.
    try:
        import wavelink
        pool_nodes = list(wavelink.Pool.nodes.values())
        await wavelink.Pool.close()
        lavalink_node = getattr(client, "lavalink_node", None)
        if lavalink_node is not None and lavalink_node not in pool_nodes:
            pool_nodes.append(lavalink_node)
        for _node in pool_nodes:
            _session = getattr(_node, "_session", None)
            if _session is not None and not _session.closed:
                await _session.close()
    except Exception as e:
        log_warning(f"Could not close Lavalink cleanly: {e!r}")

    try:
        await http_client.close()
    except Exception as e:
        log_warning(f"Could not close HTTP sessions: {e!r}")

    log_info("Support shut down cleanly.")


def _install_signal_handlers(loop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.ensure_future(shutdown(f"received signal {s.name}")),
            )
            continue
        except (NotImplementedError, RuntimeError, ValueError):
            pass
        # Windows (and some embeds) cannot use loop.add_signal_handler.
        try:
            def _handler(s, _f, _loop=loop):
                try:
                    _loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(
                            shutdown(f"received signal {signal.Signals(s).name}")
                        )
                    )
                except RuntimeError:
                    # The loop is already closed - the process is exiting.
                    pass

            signal.signal(sig, _handler)
        except (OSError, ValueError, RuntimeError):
            log_warning(f"Signal handler for {sig.name} is unavailable on this platform.")


# --- Main Bot Execution ---
exit_code = 0

async def main():
    global exit_code
    _install_signal_handlers(asyncio.get_running_loop())
    # ONE health checker for the whole process (never started from on_ready,
    # so reconnects/reloads cannot create duplicate timers).
    keepalive.start()

    # Auto-restore databases from Discord backup if on a fresh Render container
    try:
        await db_backup.restore_if_needed(bot_token=TOKEN)
    except Exception as e:
        log_warning(f"Startup database restore skipped: {e!r}")

    async with client:
        try:
            try:
                await client.load_extension("jishaku")
            except Exception as e:
                log_warning(f"jishaku load failed (continuing without it): {e!r}")

            log_info("Connecting to Discord...")

            attempt = 0
            rate_limit_waits = 0
            delay = 1.0
            non_rate_failures = 0
            using_ipv6 = False
            _set_startup(phase="connecting", attempt=0, last_error=None, next_retry_in=None)
            while True:
                try:
                    # discord.py owns the gateway: it reconnects and resumes sessions
                    # on its own, this call only returns after a clean close().
                    await client.start(TOKEN)
                    if _shutdown_started:
                        log_info("Discord client closed.")
                    else:
                        log_error("Discord client stopped unexpectedly - exiting so Render can restart the service.")
                        exit_code = 1
                    return

                except ExtensionLoadError as e:
                    # A critical part of the bot (its cogs) could not load —
                    # never pretend to be healthy.
                    log_error(f"Support failed to start. Reason: {e}")
                    _set_startup(phase="failed", last_error=str(e), next_retry_in=None)
                    exit_code = 1
                    return

                except (discord.LoginFailure, discord.PrivilegedIntentsRequired) as e:
                    log_error(f"Discord rejected the login: {e!r}")
                    log_error("Check the TOKEN environment variable in Render and the "
                              "privileged intents in the Discord Developer Portal.")
                    log_error("Support failed to start. Reason: invalid Discord credentials or intents.")
                    _set_startup(phase="failed", last_error=repr(e), next_retry_in=None)
                    exit_code = 1
                    return

                except discord.HTTPException as e:
                    if getattr(e, "status", None) == 401:
                        log_error("Discord API refused the connection (HTTP 401).")
                        log_error("Check the TOKEN environment variable in Render.")
                        log_error("Support failed to start. Reason: Discord rejected the configured token.")
                        _set_startup(phase="failed", last_error="Discord rejected the token (HTTP 401)",
                                     next_retry_in=None)
                        exit_code = 1
                        return
                    if getattr(e, "status", None) == 403:
                        body = str(e).lower()
                        if "<html" in body or "cloudflare" in body or "1015" in body:
                            # Cloudflare edge block during login - not a token
                            # verdict. Retry with cooldown instead of dying
                            # instantly (Render would restart-loop us).
                            failure = e
                        else:
                            log_error("Discord API refused the connection (HTTP 403).")
                            log_error("Check the TOKEN environment variable in Render and the "
                                      "privileged intents in the Discord Developer Portal.")
                            log_error("Support failed to start. Reason: Discord rejected the configured token.")
                            exit_code = 1
                            return
                    else:
                        failure = e

                except CloudflareBanError as e:
                    failure = e

                except (discord.GatewayNotFound, aiohttp.ClientError,
                        asyncio.TimeoutError, OSError) as e:
                    failure = e

                except Exception as e:
                    failure = e
                    log_warning(f"Unexpected error while starting: {describe_http_failure(e)}")
                    if "<html" not in str(e).lower() and "<!doctype" not in str(e).lower():
                        traceback.print_exc()

                # --- Recoverable failure: bounded exponential backoff (1→30s) ---
                if client.is_closed():
                    log_error("Discord client closed during startup - exiting so Render can restart the service.")
                    exit_code = 1
                    return

                attempt += 1

                # aiohttp 3.14+ ClientSession.close() also CLOSES the shared
                # TCPConnector, and discord.py's static_login() REUSES that
                # connector for its next session. Left as-is, every retry after
                # a close() would create a session bound to a closed connector
                # and die instantly with "RuntimeError: Session is closed".
                # Close the session (to avoid "Unclosed client session" leaks)
                # and reset the connector to MISSING so static_login() builds a
                # fresh TCPConnector(limit=0) on the next attempt.
                try:
                    await client.http.close()
                except Exception:
                    pass
                try:
                    client.http.connector = MISSING
                    setattr(client.http, "_HTTPClient__session", None)
                except Exception:
                    pass

                failure_status = getattr(failure, "status", None)
                failure_body = str(failure).lower()
                is_rate_limited = isinstance(failure, (discord.HTTPException, CloudflareBanError)) and (
                    isinstance(failure, CloudflareBanError)
                    or failure_status == 429
                    or (
                        failure_status == 403
                        and ("<html" in failure_body
                             or "cloudflare" in failure_body
                             or "1015" in failure_body)
                    )
                )

                last_error_text = describe_http_failure(failure)
                next_phase = "retrying"

                if is_rate_limited:
                    # IPv6 escape hatch: a 429 means THIS route is edge-blocked.
                    # Probe IPv6 once; when it answers cleanly, force the next
                    # attempt (REST login + gateway) over it.
                    if not using_ipv6:
                        try:
                            if not await _discord_blocked_over(socket.AF_INET6):
                                client.http.connector = aiohttp.TCPConnector(
                                    limit=0, family=socket.AF_INET6)
                                using_ipv6 = True
                                log_info("[netcheck] IPv6 route is clean - "
                                         "forcing Discord traffic over IPv6")
                        except Exception:
                            pass
                    else:
                        # This attempt already ran over IPv6 and was still
                        # blocked: fall back to the default family next round.
                        using_ipv6 = False

                    # Retry faster only renews the block: escalate the cooldown,
                    # keep the process alive (/health stays 200 so Render does
                    # not restart us) and let the block expire by itself.
                    rate_limit_waits += 1
                    headers_hint = _rate_limit_headers(failure)
                    if headers_hint:
                        last_error_text = describe_http_failure(failure) + " | " + " ".join(
                            f"{k}={v}" for k, v in headers_hint.items())
                    retry_after = 0.0
                    try:
                        retry_after = float(headers_hint.get("Retry-After") or 0.0)
                    except (TypeError, ValueError):
                        retry_after = 0.0
                    ban_left = 0.0
                    try:
                        ban_left = cloudbreaker.seconds_left()
                    except Exception:
                        pass

                    if rate_limit_waits > MAX_RATE_LIMIT_WAITS:
                        # Exiting would let Render restart the process and reset
                        # the ladder to 120s - that is exactly what kept renewing
                        # the block. Stay alive on the longest cooldown instead.
                        wait_time = max(RATE_LIMIT_MAX_WAIT, min(retry_after, RATE_LIMIT_RETRY_AFTER_CAP), ban_left)
                        next_phase = "blocked"
                        log_error(f"Login still rate-limited after {MAX_RATE_LIMIT_WAITS} "
                                  f"cooldowns - process stays up; next attempt in "
                                  f"{wait_time:.0f}s. Reason: {last_error_text}")
                    else:
                        wait_time = min(
                            RATE_LIMIT_BASE_WAIT * (2 ** (rate_limit_waits - 1)),
                            RATE_LIMIT_MAX_WAIT,
                        )
                        # Never wake up before Retry-After / an active
                        # cloudbreaker ban says the edge will answer again.
                        wait_time = max(wait_time, min(retry_after, RATE_LIMIT_RETRY_AFTER_CAP), ban_left)
                        log_discord_once(
                            f"startup-rate-limit-{rate_limit_waits}",
                            f"{describe_http_failure(failure)} during login - "
                            f"cooldown {wait_time:.0f}s "
                            f"(wait {rate_limit_waits}/{MAX_RATE_LIMIT_WAITS})"
                            + (f" | {' '.join(f'{k}={v}' for k, v in headers_hint.items())}"
                               if headers_hint else ""),
                        )
                    non_rate_failures = 0
                else:
                    using_ipv6 = False
                    non_rate_failures += 1
                    # Only CONSECUTIVE non-rate-limit failures count: a single
                    # network blip after hours of cooldown must not exit the
                    # process (a restart would reset the whole rate-limit
                    # ladder back to 120s), but a real crash loop still exits.
                    if non_rate_failures >= MAX_START_ATTEMPTS:
                        log_error(f"Support failed to start after {MAX_START_ATTEMPTS} "
                                  f"consecutive attempts.")
                        log_error(f"Reason: {describe_http_failure(failure)}")
                        _set_startup(phase="failed", last_error=describe_http_failure(failure),
                                     next_retry_in=None)
                        exit_code = 1
                        return
                    wait_time = min(delay, 30.0)
                    delay *= 2

                _set_startup(phase=next_phase, attempt=attempt,
                             last_error=last_error_text,
                             next_retry_in=int(wait_time))
                if next_phase == "retrying":
                    log_warning(f"Temporary connection failure ({describe_http_failure(failure)}) - "
                                f"retrying in {wait_time:.0f}s (attempt {attempt})")
                await asyncio.sleep(wait_time)
        finally:
            # Also runs on fatal startup errors so the API server and any
            # background work are stopped before the process exits.
            await shutdown("process exiting")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_info("Interrupted - exiting.")
    except SystemExit:
        raise
    except Exception as e:
        log_error(f"Support failed to start. Reason: {e!r}")
        traceback.print_exc()
        exit_code = 1
    sys.exit(exit_code)

