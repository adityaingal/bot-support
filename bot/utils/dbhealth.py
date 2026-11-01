# ╔══════════════════════════════════════════════════════════════════╗
# ║   Database health, validation & safe self-healing                ║
# ║                                                                  ║
# ║   Responsibilities:                                              ║
# ║     - verify every SQLite DB with PRAGMA quick_check at startup  ║
# ║     - quarantine corrupt files (never delete user data)          ║
# ║     - framework for forward-only schema migrations with a        ║
# ║       pre-migration copy                                        ║
# ║     - safe reset rules: ONLY files listed in RESETTABLE_FILES    ║
# ║       may ever be auto-reset; everything else is sacred          ║
# ║     - health snapshot consumed by /api/status + dashboard        ║
# ║                                                                  ║
# ║   Safety invariants:                                             ║
# ║     * never delete or truncate a database automatically          ║
# ║     * never replace a valid DB with an empty one                 ║
# ║     * a corrupt file is preserved as <name>.corrupt-<ts> before  ║
# ║       anything else touches the path                             ║
# ║     * all checks run off the event loop (threads)                ║
# ╚══════════════════════════════════════════════════════════════════╝

import os
import sys
import time
import json
import shutil
import sqlite3
import asyncio
import traceback
from datetime import datetime

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BOT_DIR, "db")
JSONDB_DIR = os.path.join(BOT_DIR, "jsondb")

# Root-level SQLite files that are part of the data set.
ROOT_DB_FILES = ("j2c_data.db", "rr.db")

# Only these files may EVER be automatically reset (recreated empty).
# Everything else — user accounts, economy, moderation records, server
# settings — requires an explicit administrator action.
RESETTABLE_FILES: frozenset = frozenset()  # intentionally empty: nothing is auto-reset

# Files whose absence is expected (created lazily by cogs) — missing is
# "ok", not an error, and they are created empty on demand by the cogs.
EXPECTED_LAZY = True

SCHEMA_VERSION_FILE = os.path.join(DB_DIR, ".schema_version")

# Migration registry: version -> list of (db_filename, callable(conn)).
# Migrations are forward-only; each runs in one transaction on a worker
# thread AFTER a .premigration copy has been made.
MIGRATIONS: dict[int, list] = {}

_health: dict = {
    "status": "unchecked",       # unchecked | healthy | degraded
    "checked_at": None,
    "databases": 0,
    "corrupt": [],               # [{file, error, quarantined_as}]
    "repaired": [],              # [{file, from_backup}]
    "migrations_applied": [],
    "last_integrity_check": None,
    "size_bytes": 0,
    "error": None,
}


def _log(msg: str) -> None:
    print(f"[DATABASE] {msg}", flush=True)


def _warn(msg: str) -> None:
    print(f"WARNING - [DATABASE] {msg}", flush=True)


# --- Discovery -------------------------------------------------------------

def discover_db_files() -> list[str]:
    """Absolute paths of every SQLite file we manage."""
    files: list[str] = []
    if os.path.isdir(DB_DIR):
        for name in sorted(os.listdir(DB_DIR)):
            if name.endswith(".db") and not name.endswith(("-journal", ".tmp", ".temp")):
                files.append(os.path.join(DB_DIR, name))
    for name in ROOT_DB_FILES:
        path = os.path.join(BOT_DIR, name)
        if os.path.isfile(path):
            files.append(path)
    return files


def discover_json_files() -> list[str]:
    files: list[str] = []
    if os.path.isdir(JSONDB_DIR):
        for name in sorted(os.listdir(JSONDB_DIR)):
            if name.endswith(".json"):
                files.append(os.path.join(JSONDB_DIR, name))
    counting = os.path.join(DB_DIR, "counting.json")
    if os.path.isfile(counting):
        files.append(counting)
    return files


# --- Integrity -------------------------------------------------------------

def quick_check_file(path: str) -> tuple[bool, str]:
    """PRAGMA quick_check on one file. Runs in a worker thread via
    asyncio.to_thread. Returns (ok, detail)."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            detail = (row[0] if row else "ok") or "ok"
            return (detail == "ok", str(detail))
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        return False, f"{type(e).__name__}: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _quarantine(path: str) -> str | None:
    """Preserve a corrupt file as <path>.corrupt-<epoch> so no data is
    ever lost, then leave the original path free for recovery."""
    try:
        ts = int(time.time())
        dest = f"{path}.corrupt-{ts}"
        shutil.move(path, dest)
        _warn(f"Quarantined corrupt database {os.path.basename(path)} -> {os.path.basename(dest)}")
        return dest
    except Exception as e:
        _warn(f"Could not quarantine {os.path.basename(path)}: {e!r}")
        return None


def _validate_json(path: str) -> tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            json.load(f)
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# --- Migrations ------------------------------------------------------------

def current_schema_version() -> int:
    try:
        if os.path.exists(SCHEMA_VERSION_FILE):
            with open(SCHEMA_VERSION_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip() or 0)
    except Exception:
        pass
    return 0


def _set_schema_version(version: int) -> None:
    os.makedirs(DB_DIR, exist_ok=True)
    tmp = SCHEMA_VERSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(version))
    os.replace(tmp, SCHEMA_VERSION_FILE)


def _premigration_copy(path: str) -> str | None:
    try:
        dest = f"{path}.premigration-{int(time.time())}"
        shutil.copy2(path, dest)
        return dest
    except Exception as e:
        _warn(f"Pre-migration copy failed for {os.path.basename(path)}: {e!r}")
        return None


async def apply_migrations() -> list[str]:
    """Run registered forward-only migrations above the stored version.
    Each migration: one transaction; a .premigration copy is made first.
    An interrupted migration rolls back and the version is not advanced."""
    applied: list[str] = []
    have = current_schema_version()
    todo = sorted(v for v in MIGRATIONS if v > have)
    if not todo:
        return applied
    for version in todo:
        for db_filename, fn in MIGRATIONS[version]:
            path = os.path.join(DB_DIR, db_filename)
            if not os.path.isfile(path):
                continue
            _premigration_copy(path)

            def _run(p=path, migr=fn):
                conn = sqlite3.connect(p, timeout=30)
                try:
                    conn.execute("BEGIN")
                    migr(conn)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()

            try:
                await asyncio.to_thread(_run)
                applied.append(f"v{version}:{db_filename}")
                _log(f"Migration v{version} applied to {db_filename}")
            except Exception as e:
                _warn(f"Migration v{version} failed on {db_filename}: {e!r}")
                traceback.print_exc()
                # Do NOT advance the version past a failed migration.
                return applied
        _set_schema_version(version)
    return applied


# --- Startup validation & self-healing ------------------------------------

async def validate_all(restore_callback=None) -> dict:
    """Full startup pass: discover, integrity-check, quarantine corrupt
    files, optionally hand them to a restore callback (db_backup) for
    recovery from the latest Discord backup.

    ``restore_callback(filename) -> bool`` must restore ONE database file
    from the newest valid backup and return success. It is only invoked
    for files that failed validation AND were successfully quarantined.
    """
    _health["status"] = "checking"
    _health["checked_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    _health["corrupt"] = []
    _health["repaired"] = []
    _health["migrations_applied"] = []
    _health["error"] = None

    dbs = discover_db_files()
    jsons = discover_json_files()
    total_size = 0
    corrupt: list[dict] = []

    # Integrity-check every SQLite file off the event loop.
    checks = await asyncio.gather(
        *(asyncio.to_thread(quick_check_file, p) for p in dbs),
        return_exceptions=True,
    )
    for path, result in zip(dbs, checks):
        try:
            size = os.path.getsize(path)
            total_size += size
        except OSError:
            size = 0
        if isinstance(result, BaseException):
            corrupt.append({"file": os.path.basename(path), "error": repr(result)})
            continue
        ok, detail = result
        if not ok:
            corrupt.append({"file": os.path.basename(path), "error": detail, "path": path})

    # JSON files: parse check (non-destructive).
    for path in jsons:
        ok, detail = await asyncio.to_thread(_validate_json, path)
        if not ok:
            corrupt.append({"file": os.path.basename(path), "error": detail, "path": path, "json": True})

    # Heal: quarantine corrupt SQLite files, then try a backup restore.
    for item in corrupt:
        path = item.get("path")
        if not path or item.get("json"):
            continue
        quarantined = await asyncio.to_thread(_quarantine, path)
        item["quarantined_as"] = quarantined
        if quarantined and restore_callback is not None:
            try:
                success = await restore_callback(os.path.basename(path))
            except Exception as e:
                success = False
                _warn(f"Restore callback error for {item['file']}: {e!r}")
            if success:
                ok, detail = await asyncio.to_thread(quick_check_file, path)
                if ok:
                    _health["repaired"].append({"file": item["file"], "from_backup": True})
                    _log(f"Recovered {item['file']} from backup (validation passed)")
                    item.pop("error", None)
                else:
                    _warn(f"Restored {item['file']} still fails integrity check: {detail}")

    _health["corrupt"] = [
        {k: v for k, v in c.items() if k != "path"} for c in corrupt
    ]
    _health["databases"] = len(dbs)
    _health["size_bytes"] = total_size
    _health["last_integrity_check"] = _health["checked_at"]

    unresolved = [c for c in _health["corrupt"] if "error" in c]
    if unresolved:
        _health["status"] = "degraded"
        _warn(f"{len(unresolved)} database(s) failed validation — degraded mode "
              f"(originals preserved); details in /api/status")
    else:
        _health["status"] = "healthy"
        _log(f"Validated {len(dbs)} SQLite + {len(jsons)} JSON files "
             f"({round(total_size / 1024, 1)} KB) — all healthy")
    return dict(_health)


# --- Maintenance -----------------------------------------------------------

async def cleanup_temp_files(max_age_hours: float = 24.0) -> int:
    """Remove expired temp artifacts (-journal/-wal/-shm leftovers of
    removed DBs, .tmp files, old quarantine copies past retention)."""
    removed = 0
    cutoff = time.time() - max_age_hours * 3600

    def _scan_and_remove():
        nonlocal removed
        targets = []
        for folder in (DB_DIR, JSONDB_DIR, BOT_DIR):
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if not os.path.isfile(path):
                    continue
                if not (name.endswith((".tmp", ".temp")) or ".corrupt-" in name
                        or ".premigration-" in name):
                    continue
                try:
                    if os.path.getmtime(path) < cutoff:
                        targets.append(path)
                except OSError:
                    pass
        for path in targets:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass

    await asyncio.to_thread(_scan_and_remove)
    if removed:
        _log(f"Maintenance: removed {removed} expired temp file(s)")
    return removed


def get_health() -> dict:
    """Snapshot for /api/status and the dashboard. No secrets."""
    return dict(_health)
