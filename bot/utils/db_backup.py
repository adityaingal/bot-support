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

"""
Automated SQLite Database Backup & Restore via Discord Webhook.

Purpose:
  Provides persistent data storage on Render Free tier without paying for Render Disks.
  - Automatically archives and uploads all SQLite databases & config files to a private Discord channel via Webhook.
  - Automatically restores the latest database backup from Discord on startup if local files are missing/fresh.
  - Performs an immediate final backup on shutdown (SIGTERM / SIGINT on deploy).
  - Offers manual commands for bot owners: `>backup now`, `>backup restore`, `>backup status`.
"""

import os
import io
import sys
import json
import time
import sqlite3
import zipfile
import hashlib
import asyncio
import shutil
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

import aiohttp
import discord

try:
    from utils import cloudbreaker
except Exception:  # pragma: no cover - fall back to a no-op shim
    class _NoopBreaker:
        def is_banned(self) -> bool:
            return False

        def report_ban(self, *args, **kwargs) -> None:
            pass

    cloudbreaker = _NoopBreaker()

try:
    from utils import dbhealth
except Exception:  # pragma: no cover
    dbhealth = None

# Treat a 429 this long as a Cloudflare edge ban (same threshold as cloudbreaker).
EDGE_BAN_MIN_RETRY_AFTER = 600.0

# Base directory of the bot (where CodeX.py resides)
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files and directories to back up
INCLUDE_DIRS = ["db", "jsondb"]
INCLUDE_ROOT_FILES = ["j2c_data.db", "rr.db"]

# Configuration defaults
DEFAULT_INTERVAL = 1800  # 30 minutes
MARKER_FILE = os.path.join(BOT_DIR, ".db_restored")

# Internal state tracking
_backup_task: Optional[asyncio.Task] = None
_last_backup_hash: Optional[str] = None
# One backup/restore operation at a time — a restore during a backup (or
# vice versa) could interleave partial writes.
_op_lock = asyncio.Lock()
_state: Dict[str, Any] = {
    "last_backup_time": None,
    "last_backup_files": 0,
    "last_backup_size_kb": 0,
    "last_backup_status": "none",
    "last_restore_time": None,
    "last_restore_files": 0,
    "channel_id": None,
    "op_in_progress": None,
}


def _emit(msg: str) -> None:
    try:
        print(f"INFO  - [DB-Backup] {msg}", flush=True)
    except Exception:
        pass


def _warn(msg: str) -> None:
    try:
        print(f"WARNING - [DB-Backup] {msg}", flush=True)
    except Exception:
        pass


def _err(msg: str) -> None:
    try:
        print(f"ERROR - [DB-Backup] {msg}", flush=True)
    except Exception:
        pass


def _maybe_report_edge_ban(resp) -> None:
    """If a raw webhook/message call hit a Cloudflare edge ban, trip the breaker."""
    if resp.status != 429:
        return
    try:
        retry_after = float(resp.headers.get("Retry-After") or 0.0)
    except (TypeError, ValueError):
        retry_after = 0.0
    if retry_after >= EDGE_BAN_MIN_RETRY_AFTER:
        _warn(f"Cloudflare edge ban detected (Retry-After {retry_after:.0f}s) — "
              f"suppressing Discord REST until it lifts")
        try:
            cloudbreaker.report_ban(retry_after)
        except Exception:
            pass


def get_webhook_url() -> str:
    """Retrieve configured webhook URL from environment."""
    url = (os.getenv("DB_BACKUP_WEBHOOK_URL") or os.getenv("WEBHOOK_URL") or "").strip()
    return url


def is_valid_webhook_url(url: str) -> bool:
    """Validate that the string matches Discord's webhook format."""
    if not url:
        return False
    parts = url.rstrip("/").split("/")
    if len(parts) < 2:
        return False
    is_discord = "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url
    return is_discord and parts[-2].isdigit() and len(parts[-1]) >= 15


def is_enabled() -> bool:
    """Check if automated database backup via webhook is enabled."""
    enabled_env = os.getenv("DB_BACKUP_ENABLED", "true").strip().lower() == "true"
    return enabled_env and is_valid_webhook_url(get_webhook_url())


def get_backup_interval() -> int:
    """Get the backup interval in seconds (default 1800 = 30m)."""
    try:
        return max(300, int(os.getenv("DB_BACKUP_INTERVAL", str(DEFAULT_INTERVAL))))
    except ValueError:
        return DEFAULT_INTERVAL


async def _resolve_channel_id(session: aiohttp.ClientSession, webhook_url: str) -> Optional[int]:
    """Fetch webhook details from Discord to discover its target channel_id."""
    if _state.get("channel_id"):
        return _state["channel_id"]

    override_id = (os.getenv("DB_BACKUP_CHANNEL_ID") or "").strip()
    if override_id.isdigit():
        _state["channel_id"] = int(override_id)
        return _state["channel_id"]

    try:
        async with session.get(webhook_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                cid = data.get("channel_id")
                if cid and str(cid).isdigit():
                    _state["channel_id"] = int(cid)
                    return int(cid)
            else:
                _warn(f"Failed to resolve channel_id from webhook: HTTP {resp.status}")
    except Exception as e:
        _warn(f"Could not resolve channel_id from webhook: {e!r}")

    return None


def _collect_files_to_backup() -> list[Tuple[str, str]]:
    """
    Collect all SQLite databases and config JSON files.
    Returns list of (absolute_path, relative_arcname).
    """
    files = []

    # 1. Directories (db, jsondb)
    for dir_name in INCLUDE_DIRS:
        full_dir = os.path.join(BOT_DIR, dir_name)
        if os.path.exists(full_dir) and os.path.isdir(full_dir):
            for root, _, filenames in os.walk(full_dir):
                for filename in filenames:
                    # Ignore temporary/journal/wal lockfiles that are transient
                    if filename.endswith(("-journal", ".tmp", ".temp")):
                        continue
                    abs_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(abs_path, BOT_DIR)
                    files.append((abs_path, rel_path))

    # 2. Specific root-level db files
    for root_file in INCLUDE_ROOT_FILES:
        abs_path = os.path.join(BOT_DIR, root_file)
        if os.path.exists(abs_path) and os.path.isfile(abs_path):
            files.append((abs_path, root_file))

    return files


def _read_db_consistent(abs_path: str) -> bytes:
    """Snapshot one SQLite file with the online backup API.

    Copying a live WAL database with a plain read can capture a torn
    mid-write state. sqlite3.Connection.backup() produces a consistent
    snapshot regardless of concurrent writers.
    """
    src = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True, timeout=10)
    try:
        dst = sqlite3.connect(":memory:")
        try:
            src.backup(dst)
            return sqlite3.serialize(dst)
        finally:
            dst.close()
    finally:
        src.close()


def build_backup_archive() -> Tuple[bytes, str, int, str]:
    """
    Compresses target files into an in-memory zip archive.
    Returns (zip_bytes, sha256_hash, file_count, timestamp_str).
    """
    files = _collect_files_to_backup()
    buf = io.BytesIO()
    hasher = hashlib.sha256()

    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for abs_path, rel_path in sorted(files, key=lambda x: x[1]):
            try:
                if abs_path.endswith(".db"):
                    try:
                        content = _read_db_consistent(abs_path)
                    except Exception as e:
                        _warn(f"Consistent snapshot failed for {rel_path} ({e!r}); "
                              f"falling back to raw read")
                        with open(abs_path, "rb") as f:
                            content = f.read()
                else:
                    with open(abs_path, "rb") as f:
                        content = f.read()
                hasher.update(rel_path.encode("utf-8"))
                hasher.update(content)
                zf.writestr(rel_path, content)
            except Exception as e:
                _warn(f"Could not read {rel_path} for backup: {e!r}")

    zip_bytes = buf.getvalue()
    zip_hash = hasher.hexdigest()
    return zip_bytes, zip_hash, len(files), timestamp_str


async def backup_now(reason: str = "periodic", force: bool = False) -> Dict[str, Any]:
    """
    Packs local databases and uploads the archive to Discord Webhook.
    Skips if content has not changed unless force=True.
    """
    global _last_backup_hash

    webhook_url = get_webhook_url()
    if not is_valid_webhook_url(webhook_url):
        return {"success": False, "reason": "No valid DB_BACKUP_WEBHOOK_URL configured"}

    # Raw aiohttp call — bypasses cloudbreaker's HTTPClient patch. Posting
    # to a webhooks URL during an edge ban renews the block, so skip.
    if cloudbreaker.is_banned():
        _warn("Cloudflare ban active — skipping backup upload this cycle")
        _state["last_backup_status"] = "skipped (cloudflare ban)"
        return {"success": False, "reason": "Cloudflare ban active"}

    if _op_lock.locked():
        _emit("Another backup/restore operation is running — skipping this cycle.")
        return {"success": False, "reason": "another operation in progress"}

    async with _op_lock:
        _state["op_in_progress"] = "backup"
        try:
            return await _backup_now_locked(reason, force, webhook_url)
        finally:
            _state["op_in_progress"] = None


async def _backup_now_locked(reason: str, force: bool, webhook_url: str) -> Dict[str, Any]:
    global _last_backup_hash

    try:
        # Compressing ~38 databases takes seconds of CPU — running it inline
        # froze the entire event loop (gateway + every command reply) each
        # backup cycle. Keep it on a worker thread.
        zip_bytes, zip_hash, file_count, ts = await asyncio.to_thread(build_backup_archive)
    except Exception as e:
        _err(f"Archive build failed: {e!r}")
        return {"success": False, "reason": f"Archive failed: {e}"}

    if file_count == 0:
        return {"success": False, "reason": "No database files found to back up"}

    # Avoid duplicate uploads if databases have not changed
    if not force and _last_backup_hash == zip_hash:
        _emit(f"Databases unchanged (hash: {zip_hash[:10]}...). Backup skipped.")
        return {"success": True, "skipped": True, "files": file_count}

    zip_filename = f"db_backup_{ts}.zip"
    size_kb = round(len(zip_bytes) / 1024, 2)

    embed = {
        "title": "📦 Database Backup Created",
        "color": 0x2ECC71,  # Green
        "description": f"Automated snapshot of bot databases stored successfully.",
        "fields": [
            {"name": "Trigger Reason", "value": f"`{reason}`", "inline": True},
            {"name": "Total Files", "value": f"`{file_count} files`", "inline": True},
            {"name": "Archive Size", "value": f"`{size_kb} KB`", "inline": True},
            {"name": "Timestamp", "value": f"<t:{int(time.time())}:F>", "inline": True},
            {"name": "Checksum", "value": f"`sha256:{zip_hash[:16]}`", "inline": True},
        ],
        "footer": {
            "text": "Support Web Database Persistence • Render Free Tier Recovery"
        },
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    payload = {
        "username": "Database Backup Service",
        "avatar_url": "https://cdn.discordapp.com/emojis/1057630713739989073.webp",
        "embeds": [embed]
    }

    form = aiohttp.FormData()
    form.add_field("payload_json", json.dumps(payload))
    form.add_field(
        "files[0]",
        zip_bytes,
        filename=zip_filename,
        content_type="application/zip"
    )

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Cache channel ID while we have the webhook URL
        await _resolve_channel_id(session, webhook_url)

        try:
            async with session.post(webhook_url, data=form) as resp:
                if resp.status in (200, 204):
                    _last_backup_hash = zip_hash
                    _state["last_backup_time"] = datetime.utcnow().isoformat()
                    _state["last_backup_files"] = file_count
                    _state["last_backup_size_kb"] = size_kb
                    _state["last_backup_status"] = "success"
                    _emit(f"Backup uploaded successfully: {zip_filename} ({size_kb} KB, {file_count} files)")
                    return {
                        "success": True,
                        "filename": zip_filename,
                        "size_kb": size_kb,
                        "files": file_count,
                        "hash": zip_hash[:16],
                    }
                elif resp.status == 429:
                    _maybe_report_edge_ban(resp)
                    _warn("Webhook rate limited (429) — skipping backup upload this cycle")
                    _state["last_backup_status"] = "rate_limited"
                    return {"success": False, "reason": "rate limited (429)"}
                else:
                    text = await resp.text()
                    _err(f"Webhook upload failed (HTTP {resp.status}): {text[:200]}")
                    _state["last_backup_status"] = f"HTTP {resp.status}"
                    return {"success": False, "reason": f"HTTP {resp.status}"}
        except Exception as e:
            _err(f"Webhook request exception: {e!r}")
            _state["last_backup_status"] = f"error: {type(e).__name__}"
            return {"success": False, "reason": str(e)}


async def _fetch_latest_backup_zip(bot_token: str) -> Dict[str, Any]:
    """Locate and download the newest backup zip from the webhook channel.
    Returns {success, data?, filename?, reason?}."""
    webhook_url = get_webhook_url()
    if not is_valid_webhook_url(webhook_url):
        return {"success": False, "reason": "No valid DB_BACKUP_WEBHOOK_URL configured"}

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        channel_id = await _resolve_channel_id(session, webhook_url)
        if not channel_id:
            return {"success": False, "reason": "Could not determine backup channel_id"}

        headers = {
            "Authorization": f"Bot {bot_token}",
            "User-Agent": "DiscordBot (https://discord.com, 2.0) Python/3.11 aiohttp/3.9",
        }
        messages_url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=20"
        try:
            async with session.get(messages_url, headers=headers) as resp:
                if resp.status == 429:
                    _maybe_report_edge_ban(resp)
                    return {"success": False, "reason": "HTTP 429 fetching messages"}
                if resp.status != 200:
                    return {"success": False, "reason": f"HTTP {resp.status} fetching messages"}
                messages = await resp.json()
        except Exception as e:
            return {"success": False, "reason": str(e)}

        target_attachment = None
        for msg in messages:
            for att in msg.get("attachments", []):
                fname = att.get("filename", "")
                if fname.endswith(".zip") and ("db_backup" in fname or "backup" in fname):
                    target_attachment = att
                    break
            if target_attachment:
                break

        if not target_attachment:
            return {"success": False, "reason": "No backup archive found in channel"}

        download_url = target_attachment.get("url")
        fname = target_attachment.get("filename")
        try:
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    return {"success": False, "reason": f"HTTP {resp.status} downloading backup"}
                data = await resp.read()
        except Exception as e:
            return {"success": False, "reason": f"Download failed: {e}"}
        return {"success": True, "data": data, "filename": fname}


def _safe_member_path(member_name: str) -> str | None:
    """Sanitized target path for a zip member, or None to skip."""
    clean = os.path.normpath(member_name)
    if clean.startswith("..") or os.path.isabs(clean):
        return None
    return os.path.join(BOT_DIR, clean)


def _extract_validated(archive: bytes, only_file: str | None = None) -> Dict[str, Any]:
    """Extract to a temp dir, validate every .db with quick_check, then
    atomically move validated files into place. On ANY validation failure
    the originals are left untouched.

    Returns {restored: int, reason?: str}. Runs on a worker thread.
    """
    staging = os.path.join(BOT_DIR, ".restore_tmp")
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            corrupt_member = zf.testzip()
            if corrupt_member is not None:
                return {"restored": 0, "reason": f"zip CRC failure on {corrupt_member}"}

            extracted: list[tuple[str, str]] = []  # (staged_path, target_path)
            for member in zf.infolist():
                if member.is_dir():
                    continue
                target = _safe_member_path(member.filename)
                if target is None:
                    continue
                if only_file is not None and os.path.basename(target) != only_file:
                    continue
                staged = os.path.join(staging, os.path.basename(target))
                with zf.open(member) as src, open(staged, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append((staged, target))

            if not extracted:
                return {"restored": 0, "reason": "no matching files in archive"}

            # Validate staged SQLite files BEFORE touching the originals.
            for staged, target in extracted:
                if target.endswith(".db"):
                    ok, detail = dbhealth.quick_check_file(staged) if dbhealth else (True, "ok")
                    if not ok:
                        return {"restored": 0,
                                "reason": f"staged {os.path.basename(target)} failed integrity: {detail}"}
                elif target.endswith(".json"):
                    try:
                        with open(staged, "r", encoding="utf-8") as f:
                            json.load(f)
                    except Exception as e:
                        return {"restored": 0,
                                "reason": f"staged {os.path.basename(target)} invalid JSON: {e}"}

            # Atomic per-file move into place.
            for staged, target in extracted:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(staged, target)
            return {"restored": len(extracted)}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def restore_from_discord(bot_token: str, force: bool = False) -> Dict[str, Any]:
    """
    Downloads the latest backup zip and restores it with full validation:
    CRC check, per-database integrity check, atomic per-file replacement.
    Originals are never touched unless every staged file validates.
    """
    if cloudbreaker.is_banned():
        _warn("Cloudflare ban active — skipping Discord restore this cycle")
        return {"success": False, "reason": "Cloudflare ban active"}

    if _op_lock.locked():
        return {"success": False, "reason": "another operation in progress"}

    async with _op_lock:
        _state["op_in_progress"] = "restore"
        try:
            fetched = await _fetch_latest_backup_zip(bot_token)
            if not fetched.get("success"):
                _err(f"Restore fetch failed: {fetched.get('reason')}")
                return {"success": False, "reason": fetched.get("reason")}
            fname = fetched.get("filename")
            _emit(f"Restoring from {fname} (validated extract)...")
            result = await asyncio.to_thread(_extract_validated, fetched["data"], None)
            if result["restored"] == 0:
                _err(f"Restore aborted, originals untouched: {result.get('reason')}")
                return {"success": False, "reason": result.get("reason")}
            _state["last_restore_time"] = datetime.utcnow().isoformat()
            _state["last_restore_files"] = result["restored"]
            with open(MARKER_FILE, "w", encoding="utf-8") as f:
                f.write(json.dumps({"timestamp": time.time(), "file": fname,
                                    "count": result["restored"]}))
            _emit(f"Database restore complete: {result['restored']} files from {fname}")
            return {"success": True, "filename": fname, "files": result["restored"]}
        except Exception as e:
            _err(f"Restore failed: {e!r}")
            return {"success": False, "reason": str(e)}
        finally:
            _state["op_in_progress"] = None


async def restore_single_file(bot_token: str, filename: str) -> bool:
    """Recovery entry point for utils.dbhealth: restore ONE database file
    from the newest backup. Validation failures leave the path untouched."""
    if cloudbreaker.is_banned() or _op_lock.locked():
        return False
    async with _op_lock:
        _state["op_in_progress"] = f"restore:{filename}"
        try:
            fetched = await _fetch_latest_backup_zip(bot_token)
            if not fetched.get("success"):
                return False
            result = await asyncio.to_thread(_extract_validated, fetched["data"], filename)
            if result["restored"] == 0:
                _warn(f"Single-file restore of {filename} aborted: {result.get('reason')}")
                return False
            _emit(f"Recovered {filename} from backup ({result['restored']} file)")
            return True
        except Exception as e:
            _warn(f"Single-file restore error for {filename}: {e!r}")
            return False
        finally:
            _state["op_in_progress"] = None


async def restore_if_needed(bot_token: str) -> bool:
    """
    Runs during bot startup.
    If DB_BACKUP_AUTO_RESTORE is true and local databases look freshly generated/missing,
    auto-restores from the latest Discord backup.
    """
    if not is_enabled():
        return False

    auto_restore = os.getenv("DB_BACKUP_AUTO_RESTORE", "true").strip().lower() == "true"
    if not auto_restore:
        return False

    # Check if restore was already performed on this container run
    if os.path.exists(MARKER_FILE):
        _emit("Database already restored in this instance lifecycle.")
        return False

    # Check if databases exist with meaningful content
    db_dir = os.path.join(BOT_DIR, "db")
    total_size = 0
    if os.path.exists(db_dir):
        for f in os.listdir(db_dir):
            if f.endswith(".db"):
                try:
                    total_size += os.path.getsize(os.path.join(db_dir, f))
                except OSError:
                    pass

    # A populated set of 38 DBs is typically > 500 KB. If empty or fresh checkout (< 50KB):
    is_fresh = total_size < 50000
    if is_fresh:
        _emit("Local databases appear fresh/empty. Initiating auto-restore from Discord...")
        res = await restore_from_discord(bot_token=bot_token, force=True)
        return res.get("success", False)
    else:
        _emit(f"Local databases present ({round(total_size / 1024, 1)} KB). Skipping startup restore.")
        return False


async def _backup_loop(bot: discord.Client) -> None:
    """Background task loop that creates periodic database snapshots."""
    interval = get_backup_interval()
    _emit(f"Automated backup loop running every {interval}s ({round(interval / 60, 1)} mins).")

    # Initial delay so startup isn't bogged down
    await asyncio.sleep(min(120, interval))

    while not bot.is_closed():
        try:
            await backup_now(reason=f"periodic ({round(interval / 60)}m)")
        except asyncio.CancelledError:
            break
        except Exception as e:
            _warn(f"Error in backup loop: {e!r}")

        await asyncio.sleep(interval)


def start(bot: discord.Client) -> None:
    """Start the periodic backup background task."""
    global _backup_task
    if not is_enabled():
        _emit("Database webhook backup is disabled (no DB_BACKUP_WEBHOOK_URL set).")
        return

    if _backup_task is None or _backup_task.done():
        _backup_task = asyncio.create_task(_backup_loop(bot), name="support:db_backup")


def stop() -> None:
    """Cancel the backup background task."""
    global _backup_task
    if _backup_task and not _backup_task.done():
        _backup_task.cancel()
        _backup_task = None


def get_status() -> Dict[str, Any]:
    """Return live backup status for diagnostics and commands."""
    return {
        "enabled": is_enabled(),
        "interval_seconds": get_backup_interval(),
        "webhook_configured": bool(get_webhook_url()),
        **_state
    }
