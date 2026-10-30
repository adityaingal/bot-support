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

from fastapi import FastAPI, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import socket
import time
import json
import logging
import aiohttp
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from utils.config import *


from api.routes import bot, guilds, admin
from api.dependencies import verify_api_key, limiter
from api.db_manager import db_manager
from utils.keepalive import snapshot as keepalive_snapshot

# Configure logging
logger = logging.getLogger("api_request_logs")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)

# --- Netcheck (?netcheck=1 on /api/status) ---------------------------------
# On-demand outbound diagnosis from inside the instance: is THIS box's
# egress IP blocked by Discord's Cloudflare edge, and does IPv6 work?
# Cached so repeated polling can never turn into a request storm.
_NETCHECK_CACHE = {"at": 0.0, "data": None}
_NETCHECK_TTL = 300.0
_PROBE_HEADERS = {"User-Agent": "DiscordBot (https://discord.com, 2.0) Python/3.11 aiohttp/3.9"}


async def _probe_discord(family: int) -> dict:
    """GET /users/@me over one address family; 429/HTML = edge-blocked."""
    out = {}
    connector = aiohttp.TCPConnector(family=family, limit=1)
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get("https://discord.com/api/v10/users/@me",
                                   headers=_PROBE_HEADERS) as resp:
                out["status"] = resp.status
                out["via"] = resp.headers.get("Via")
                if resp.status == 429:
                    out["retry_after_s"] = resp.headers.get("Retry-After")
                    out["cf_ray"] = resp.headers.get("CF-RAY")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


async def _netcheck() -> dict:
    """Outbound reachability report (Discord login diagnosis, no secrets)."""
    now = time.time()
    cached = _NETCHECK_CACHE["data"]
    if cached and now - _NETCHECK_CACHE["at"] < _NETCHECK_TTL:
        return {**cached, "cached_for_s": int(_NETCHECK_TTL - (now - _NETCHECK_CACHE["at"]))}
    data = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        infos = socket.getaddrinfo("discord.com", 443)
        data["discord_dns_families"] = sorted({info[0] for info in infos})  # 2=IPv4, 10=IPv6
    except Exception as e:
        data["discord_dns_error"] = f"{type(e).__name__}: {e}"
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("https://api.ipify.org") as resp:
                data["egress_ipv4"] = (await resp.text()).strip()[:64]
    except Exception as e:
        data["egress_ipv4_error"] = f"{type(e).__name__}: {e}"
    data["discord_ipv4"] = await _probe_discord(socket.AF_INET)
    data["discord_ipv6"] = await _probe_discord(socket.AF_INET6)
    _NETCHECK_CACHE.update(at=now, data=data)
    print(f"[netcheck] egress={data.get('egress_ipv4', '?')} "
          f"discord/IPv4={data['discord_ipv4'].get('status', data['discord_ipv4'].get('error'))} "
          f"discord/IPv6={data['discord_ipv6'].get('status', data['discord_ipv6'].get('error'))}",
          flush=True)
    return data

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup: Nothing special needed for now
    yield
    # Shutdown: Close all shared database connections
    await db_manager.close_all()

def create_app() -> FastAPI:
    """
    Initializes the FastAPI application for the CodeX Bot Dashboard.
    The bot instance will be attached to app.state.bot in CodeX.py at runtime.
    """
    app = FastAPI(
        title=f"{BRAND_NAME} Bot API",
        description=f"REST API to manage the {BRAND_NAME} Discord Bot features",
        version="1.0",
        lifespan=lifespan
    )

    # Structured Logging Middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        log_data = {
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(process_time * 1000, 2),
            "client_ip": request.client.host if request.client else "unknown"
        }
        
        logger.info(json.dumps(log_data))
        return response

    # Attach limiter and handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Build allowed origins from env + hardcoded fallbacks
    _extra_origins = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "").split(",")
        if o.strip()
    ]
    _allowed_origins = list(dict.fromkeys([
        "http://localhost:3000",
        "https://localhost:3000",
        "https://your-vercel-url-here.vercel.app",
        "https://dashboard-qlf5.onrender.com",
        "https://support-web-dashboard.onrender.com",
        *_extra_origins,
    ]))

    # Enable CORS for Next.js dashboard (supports localhost, configured origins, and all *.onrender.com subdomains)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_origin_regex=r"https://.*\.onrender\.com",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register Routers
    # Keep health checks public for Render; protect all dashboard data routes.
    protected = [Depends(verify_api_key)]
    app.include_router(bot.router, prefix="/api/v1/bot", tags=["Bot"], dependencies=protected)
    app.include_router(guilds.router, prefix="/api/v1/guilds", tags=["Guilds"], dependencies=protected)
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"], dependencies=protected)

    @app.get("/", summary="API Root", description="Returns basic API information and online status.")
    async def root():
        return {
            "status": "online",
            "bot_name": BRAND_NAME,
            "api_version": "1.0"
        }

    @app.head("/", summary="API Root (HEAD)", include_in_schema=False)
    async def root_head():
        # Uptime monitors and CDNs often probe with HEAD; FastAPI does not map
        # HEAD to GET automatically, so answer it explicitly (body-less).
        return Response(status_code=200)

    @app.get("/api/status", summary="Service status",
             description="Web service status vs Discord gateway status. Public, lightweight, no secrets. "
                         "Add ?netcheck=1 for an on-demand outbound connectivity report (cached 5 min).")
    async def api_status(netcheck: str | None = None):
        """Honest split between the HTTP service and the Discord connection.

        Web ONLINE does NOT imply Discord ONLINE - the two are reported
        separately and guild/user counts are only included when the gateway
        is actually ready (never invented).
        """
        bot = getattr(app.state, "bot", None)
        state = _discord_state(bot)

        payload = {
            "service": BRAND_NAME,
            "web": {"status": "online"},
            "discord": {
                "status": {"connected": "online", "connecting": "starting"}.get(state, "offline"),
                "connected": state == "connected",
            },
            "keepalive": keepalive_snapshot(),
        }

        # Startup diagnostics (no secrets): lets you see WHY the bot is not
        # online from a single GET instead of digging through Render logs.
        startup = getattr(app.state, "startup", None)
        if isinstance(startup, dict) and startup.get("phase") not in (None, "init"):
            payload["discord"]["phase"] = startup.get("phase")
            for key in ("attempt", "last_error", "next_retry_in",
                        "synced_commands", "sync_attempts", "sync_error"):
                if startup.get(key) is not None:
                    payload["discord"][key if key != "next_retry_in" else "next_retry_in_s"] = startup[key]
            if startup.get("updated"):
                payload["discord"]["updated"] = startup["updated"]
        if state == "connected" and bot is not None:
            try:
                payload["guilds"] = len(bot.guilds)
                payload["users"] = sum(g.member_count or 0 for g in bot.guilds)
            except Exception:
                pass
        if netcheck == "1":
            try:
                payload["netcheck"] = await _netcheck()
            except Exception as e:
                payload["netcheck"] = {"error": f"{type(e).__name__}: {e}"}
        return payload

    @app.head("/api/status", summary="Service status (HEAD)", include_in_schema=False)
    async def api_status_head():
        return Response(status_code=200)

    @app.get("/health", summary="Health Check", description="Performs a health check for container orchestration and uptime monitoring.")
    async def health():
        """Honest health report for Render.

        Always answers HTTP 200 while the process is alive (a transient
        Discord outage must not make Render restart a working service), but
        never claims the Discord side is healthy when it is not.
        """
        bot = getattr(app.state, "bot", None)
        discord_state = _discord_state(bot)

        return {
            "status": "ok" if discord_state == "connected" else "degraded",
            "service": BRAND_NAME,
            "discord": discord_state,
        }

    @app.head("/health", summary="Health Check (HEAD)", include_in_schema=False)
    async def health_head():
        # Same contract as GET /health: 200 whenever the process answers.
        return Response(status_code=200)

    return app


def _discord_state(bot) -> str:
    """Report gateway state for plain and auto-sharded clients.

    ``AutoShardedClient`` never populates ``client.ws`` (sockets live on the
    per-shard objects), so checking ``ws`` alone would wrongly report
    ``disconnected`` for a healthy sharded bot.
    """
    if bot is None:
        return "disconnected"
    try:
        if bot.is_closed():
            return "disconnected"

        ws = getattr(bot, "ws", None)
        if ws is not None:
            return "connected" if getattr(ws, "open", False) else "disconnected"

        shards = getattr(bot, "shards", None)
        if isinstance(shards, dict):
            if not shards:
                return "connecting"
            open_shards = 0
            for info in shards.values():
                try:
                    closed = info.is_closed()
                except Exception:
                    closed = True
                if not closed:
                    open_shards += 1
            if open_shards == len(shards):
                return "connected"
            return "connecting" if open_shards else "disconnected"

        return "connected" if bot.is_ready() else "connecting"
    except Exception:
        return "disconnected"
