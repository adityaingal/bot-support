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
from dotenv import load_dotenv

load_dotenv()

TOKEN      = os.environ.get("TOKEN")
BRAND_NAME = os.environ.get("brand_name", "Support Web")
NAME       = BRAND_NAME
BotName    = BRAND_NAME

server     = os.getenv("SUPPORT_SERVER_URL", "https://discord.gg/UVRWygSpJq")
serverLink = server
ch         = "https://discord.com/channels/699587669059174461/1271825678710476911"

# ── Project identity ────────────────────────────────────────────────────────
CREATOR_NAME = os.getenv("CREATOR_NAME", "OGADI")
CREATOR_ID   = os.getenv("CREATOR_ID", "").strip()
PROJECT_TYPE = "Discord Support Bot + Web Dashboard"


def creator_credit() -> str:
    """Markdown for the creator line — linked when CREATOR_ID is set."""
    if CREATOR_ID.isdigit():
        return f"[{CREATOR_NAME}](https://discord.com/users/{CREATOR_ID})"
    return f"**{CREATOR_NAME}**"


# ── Developer credit (Developer Info / Team Info embeds) ─────────────────────
DEV_NAME = os.getenv("DEV_NAME", "MD")
DEV_ID   = os.getenv("DEV_ID", "1466133502939365437").strip()

BOT_INVITE_URL = os.getenv(
    "BOT_INVITE_URL",
    "https://discord.com/oauth2/authorize?client_id=1487525013576749106&permissions=8&integration_type=0&scope=bot+applications.commands",
)


def dev_credit() -> str:
    """Markdown for the developer line — linked to the Discord profile."""
    if DEV_ID.isdigit():
        return f"[{DEV_NAME}](https://discord.com/users/{DEV_ID})"
    return f"**{DEV_NAME}**"

CMD_WEBHOOK_URL = os.getenv("CMD_WEBHOOK_URL")

# ── Owner / Staff IDs ─────────────────────────────────────────────────────────
# Edit OWNER_IDS in .env — comma-separated, no spaces needed.
# Example:  OWNER_IDS = 1365657651823771719,1466133502939365437

def _parse_ids(env_key: str, defaults: list[int]) -> list[int]:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return defaults
    ids = [int(p.strip()) for p in raw.split(",") if p.strip().isdigit()]
    return ids or defaults

OWNER_IDS:     list[int] = _parse_ids("OWNER_IDS",     [1365657651823771719, 1466133502939365437])
OWNER_IDS_STR: list[str] = [str(i) for i in OWNER_IDS]

# Aliases kept for backwards compatibility with files that import these names
BOT_OWNER_IDS     = OWNER_IDS
BOT_OWNER_IDS_STR = OWNER_IDS_STR
STAFF_IDS         = OWNER_IDS
STAFF_IDS_STR     = OWNER_IDS_STR