# 🚀 Easy Render Deployment Guide for Support Web

This guide walks you through deploying **Support Web** (Discord Bot + FastAPI Backend + Next.js Dashboard) onto [Render](https://render.com) using the included `render.yaml` Blueprint.

---

## ✦ Architecture on Render

```
GitHub Repository
       │
       ▼
  Render Blueprint (render.yaml)
       │
       ├──► support-web-api (Python Web Service)
       │      • Discord Bot Gateway Connection (discord.py v2)
       │      • REST API backend for Dashboard (FastAPI + uvicorn)
       │      • Built-in /health endpoint & self-keepalive
       │      • Automatically binds to Render $PORT
       │
       └──► support-web-dashboard (Node.js Web Service)
              • Next.js 14 Web Dashboard
              • Discord OAuth2 Login & Guild Management
              • Connects directly to support-web-api
```

---

## ✦ Quickstart (Method: Render Blueprint)

### Step 1: Push to GitHub
Make sure all your changes are pushed to your GitHub repository:
```bash
git add .
git commit -m "Optimize for Render deployment"
git push origin main
```

### Step 2: Create a Blueprint on Render
1. Log into your [Render Dashboard](https://dashboard.render.com).
2. Click **New +** (top right) and select **Blueprint**.
3. Select your repository (e.g. `your-username/support-web`).
4. Render will read [render.yaml](file:///c:/Users/ai658/OneDrive/Desktop/DISCORD/Support-Web-Render/support-web/render.yaml) and automatically create both services:
   - `support-web-api` (Plan: Free)
   - `support-web-dashboard` (Plan: Free)

### Step 3: Enter Required Secrets
Render will prompt you for variables marked `sync: false`:

| Variable | Service | Where to get it |
|---|---|---|
| `TOKEN` | `support-web-api` | [Discord Developer Portal](https://discord.com/developers/applications) → Your Bot → **Bot** tab → **Reset Token** |
| `DASHBOARD_API_KEY` | `support-web-api` & `support-web-dashboard` | Generate any random secure string (e.g. `openssl rand -hex 32`). Must match on both services. |
| `NEXT_PUBLIC_DASHBOARD_API_KEY` | `support-web-dashboard` | Same string as `DASHBOARD_API_KEY` |
| `NEXTAUTH_SECRET` | `support-web-dashboard` | Any random string for NextAuth session encryption |
| `DISCORD_CLIENT_ID` | `support-web-dashboard` | Discord Developer Portal → General Information → **Application ID** |
| `DISCORD_CLIENT_SECRET` | `support-web-dashboard` | Discord Developer Portal → OAuth2 → **Client Secret** |

### Step 4: Configure Discord Developer Portal
In your bot application on [Discord Developer Portal](https://discord.com/developers/applications):

1. **Privileged Gateway Intents** (Bot tab):
   - Enable **Presence Intent**
   - Enable **Server Members Intent**
   - Enable **Message Content Intent**
   *(Required for antinuke, leveling, automod, and commands)*

2. **OAuth2 Redirect URI** (OAuth2 tab → Redirects):
   Add the following URL:
   ```text
   https://<YOUR-DASHBOARD-NAME>.onrender.com/api/auth/callback/discord
   ```
   *(By default, this is `https://support-web-dashboard.onrender.com/api/auth/callback/discord` unless you named the dashboard service differently)*

### Step 5: Click "Apply" and Deploy
Render will build and launch both services automatically:
- `support-web-api` will start on Python 3.11.9 and connect to Discord.
- `support-web-dashboard` will build Next.js 14 and start serving requests.

---

## ✦ Key Optimizations Included

1. **Automatic CORS Support**:
   - `CORSMiddleware` automatically matches all `https://*.onrender.com` subdomains, preventing cross-origin blocking when Render subdomains change.

2. **Smart KeepAlive Self-Ping**:
   - On Render's Free tier, services go to sleep after 15 minutes of inactivity.
   - The bot's built-in `keepalive.py` automatically resolves `RENDER_EXTERNAL_URL` and pings its own `/health` endpoint every 10 minutes to maintain persistent uptime.

3. **Memory and Cache Optimization**:
   - Webpack caching in `next.config.js` is tuned to prevent out-of-memory errors on Render's 512MB RAM free tier.
   - `requirements.txt` has been purged of heavy, conflicting, and obsolete packages for blazing fast builds.

4. **Database Persistence (Paid Plans)**:
   - On paid Starter plans, you can uncomment the `disk:` block in `render.yaml` and set `RENDER_DISK_PATH: /var/data` to persist all SQLite databases on a Render disk.

5. **Free Tier Database Persistence via Discord Webhook (Zero Cost)**:
   - On the Free tier where disks are ephemeral, you don't need to pay for a disk.
   - Simply set `DB_BACKUP_WEBHOOK_URL` to a Discord webhook in your private staff channel.
   - The bot automatically:
     - Archives all 38 SQLite databases (`db/*.db`, `jsondb/*.json`, `j2c_data.db`, `rr.db`) and uploads them to the webhook every 30 minutes.
     - Performs a clean final backup whenever Render deploys or restarts (`SIGTERM` graceful shutdown).
     - **Auto-restores** the latest backup from Discord on startup if local databases are missing/empty.
   - You can also trigger backups manually from Discord using `>backup now` or `>backup restore`.

---

## ✦ Troubleshooting

| Issue | Cause & Solution |
|---|---|
| **Bot logs `TOKEN environment variable is missing`** | Enter your Discord bot token under Environment Variables on the `support-web-api` service in Render. |
| **`Session is closed` on login** | Python 3.14 breaks discord.py login. Ensure `PYTHON_VERSION` is set to `3.11.9` (already preset in `render.yaml`). |
| **Dashboard login fails (Redirect mismatch)** | The redirect URI in Discord Developer Portal does not match your Render dashboard URL. Check the OAuth2 Redirect URL. |
| **Health check failing** | Health check path must be `/health`. Render automatically monitors this URL and marks the service Healthy. |
