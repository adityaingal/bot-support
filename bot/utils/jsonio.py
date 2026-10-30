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

import json
import os


def _warn(message: str) -> None:
    print(f"[jsonio] WARNING - {message}", flush=True)


def _default(default):
    return {} if default is None else default


def load_json(path, default=None):
    """Encoding-tolerant JSON read. Never raises for missing or corrupt files.

    Reads UTF-8 (BOM allowed) first; a UTF-16 file (e.g. written by a Windows
    shell redirect) is decoded, and if it holds valid JSON it is rewritten as
    UTF-8 so the file heals itself. Anything unreadable returns `default`.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return _default(default)
    except UnicodeDecodeError:
        pass
    except json.JSONDecodeError:
        _warn(f"{path} is not valid JSON - using defaults (file left untouched)")
        return _default(default)
    except OSError as exc:
        _warn(f"could not read {path} ({exc}) - using defaults")
        return _default(default)

    try:
        with open(path, "r", encoding="utf-16") as f:
            text = f.read()
    except (UnicodeDecodeError, OSError) as exc:
        _warn(f"{path} is not UTF-8 or UTF-16 ({exc}) - using defaults")
        return _default(default)

    if not text.strip():
        data = _default(default)
        try:
            save_json(path, data)
            _warn(f"{path} was empty non-UTF-8 text - rewrote it as UTF-8 JSON")
        except OSError as exc:
            _warn(f"could not rewrite {path} as UTF-8 ({exc})")
        return data

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _warn(f"{path} is valid UTF-16 but not JSON - using defaults (file left untouched)")
        return _default(default)

    try:
        save_json(path, data)
        _warn(f"{path} was not UTF-8 - rewrote it as UTF-8")
    except OSError as exc:
        _warn(f"could not rewrite {path} as UTF-8 ({exc})")
    return data


def save_json(path, data, indent=4):
    """Write JSON as UTF-8 (no BOM, LF line endings)."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
