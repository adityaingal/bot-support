#!/usr/bin/env python3
"""
Pre-flight verification script for deploying Support Web on Render.
Runs local checks on Python version, required modules, environment variables,
and files needed for Render deployment.

Usage:
    python validate_render.py
"""

import sys
import os
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def print_result(ok: bool, title: str, details: str = ""):
    symbol = "[OK]" if ok else "[FAIL]"
    print(f"{symbol} {title}")
    if details:
        for line in details.splitlines():
            print(f"   {line}")

def main():
    print("=" * 60)
    print(" Support Web - Render Pre-Flight Deployment Check")
    print("=" * 60)
    all_ok = True

    # 1. Python Version Check
    v = sys.version_info
    py_ok = (3, 10) <= (v.major, v.minor) < (3, 14)
    v_str = f"{v.major}.{v.minor}.{v.micro}"
    if py_ok:
        print_result(True, f"Python Version: {v_str} (Compatible with discord.py on Render)")
    else:
        all_ok = False
        print_result(
            False,
            f"Python Version: {v_str}",
            "Render requires Python 3.11.9 (or 3.10–3.13). Python 3.14+ causes 'Session is closed' error."
        )

    # 2. Key Files Check
    base = Path(__file__).resolve().parent
    key_files = [
        ("render.yaml", base / "render.yaml"),
        ("bot/CodeX.py", base / "bot" / "CodeX.py"),
        ("bot/requirements.txt", base / "bot" / "requirements.txt"),
        ("bot/api/server.py", base / "bot" / "api" / "server.py"),
        ("dashboard/package.json", base / "dashboard" / "package.json"),
        ("dashboard/next.config.js", base / "dashboard" / "next.config.js"),
    ]

    missing_files = []
    for label, path in key_files:
        if not path.is_file():
            missing_files.append(label)

    if not missing_files:
        print_result(True, "All required deployment files exist")
    else:
        all_ok = False
        print_result(False, "Missing critical files:", "\n".join(missing_files))

    # 3. Check for next.config.mjs conflict
    mjs_config = base / "dashboard" / "next.config.mjs"
    if mjs_config.exists():
        all_ok = False
        print_result(False, "Duplicate Next.js config detected: dashboard/next.config.mjs exists alongside next.config.js")
    else:
        print_result(True, "Next.js configuration is clean (no conflicting next.config.mjs)")

    # 4. Check requirements.txt for obsolete stdlib packages
    req_file = base / "bot" / "requirements.txt"
    if req_file.exists():
        content = req_file.read_text(encoding="utf-8", errors="ignore")
        bad_packages = [pkg for pkg in ["asyncio\n", "typing\n", "datetime\n", "pathlib\n", "collection\n"] if pkg in content]
        if bad_packages:
            all_ok = False
            print_result(False, "Obsolete stdlib backports found in requirements.txt:", "".join(bad_packages))
        else:
            print_result(True, "bot/requirements.txt is clean of conflicting stdlib packages")

        # Check required packages
        has_aiofiles = "aiofiles" in content
        has_pillow = "Pillow" in content or "pillow" in content
        if has_aiofiles and has_pillow:
            print_result(True, "bot/requirements.txt includes required aiofiles and Pillow")
        else:
            all_ok = False
            missing = []
            if not has_aiofiles: missing.append("aiofiles")
            if not has_pillow: missing.append("Pillow")
            print_result(False, "Missing required libraries in requirements.txt:", ", ".join(missing))

    # 5. Environment Variables Guidance
    print("\n--- [!] Render Required Secrets Checklist ---")
    secrets = [
        ("TOKEN", "Discord Bot Token (bot Developer Portal -> Bot -> Reset Token)"),
        ("DASHBOARD_API_KEY", "Random secret string (shared between API and Dashboard)"),
        ("NEXTAUTH_SECRET", "Random secret string for NextAuth session encryption"),
        ("DISCORD_CLIENT_ID", "Discord Application Client ID (Developer Portal -> General Information)"),
        ("DISCORD_CLIENT_SECRET", "Discord Application Client Secret (Developer Portal -> OAuth2)"),
    ]
    for key, desc in secrets:
        print(f"  * {key:<24} : {desc}")

    print("\n--- [*] Discord OAuth2 Redirect URI ---")
    print("  Add to Discord Developer Portal -> OAuth2 -> Redirects:")
    print("  https://<YOUR-DASHBOARD-NAME>.onrender.com/api/auth/callback/discord\n")

    print("=" * 60)
    if all_ok:
        print(">>> STATUS: READY FOR RENDER DEPLOYMENT!")
        print("Push your changes to GitHub and deploy via Render Blueprint (render.yaml).")
    else:
        print(">>> STATUS: SOME CHECKS FAILED. Review the messages above before deploying.")
    print("=" * 60)

if __name__ == "__main__":
    main()
