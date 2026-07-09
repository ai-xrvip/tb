# 4KHD Gallery Search Bot — TB Deploy

Telegram bot that searches image galleries across 4KHD.com, XChina.co, and E-Hentai.org.  
Commercial project with VIP subscription system via card activation codes.

## Setup

### 1. Create the Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) and send `/newbot`
2. Choose a name and username (e.g. `MyGallerySearchBot`)
3. Copy the token BotFather gives you
4. Send `/setinline` to @BotFather, select your bot, and set inline placeholder to `输入关键词搜索图集`
5. Send `/setinlinefeedback` and set to `100%`
6. Send `/setcommands` and paste:

```
start - 主菜单
search - 搜索图集
random - 随机推荐
my - 我的VIP
help - 使用帮助
subscribe - 订阅关键词
unsubscribe - 取消订阅
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values:
#   BOT_TOKEN — from @BotFather
#   ADMIN_IDS — your Telegram user ID (comma-separated for multiple admins)
#   EH_MEMBER_ID / EH_PASS_HASH — optional, for E-Hentai search
```

Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot).  
EH cookies can be extracted from your browser after logging into e-hentai.org.

### 3. Run locally

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your BOT_TOKEN and ADMIN_IDS
python main.py
```

The bot starts in **polling mode** by default (no webhook URL set).  
Flask admin dashboard at `http://localhost:8000/admin`.

### 4. Deploy to Railway

1. Push to a GitHub repository
2. In Railway, create a new project from that repo
3. Set `WEBHOOK_URL` to your Railway app's public URL (e.g. `https://your-app.up.railway.app`)
4. Add a **persistent volume** mounted at `/app/data` — this stores the SQLite database, backups, and logs
5. Railway auto-detects the Dockerfile and builds it

**Dockerfile notes:**
- Uses `python:3.11.11-slim` as base
- Runs as non-root user `botuser`
- HEALTHCHECK pings port 8000 every 30s

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | **Yes** | — | Telegram bot token from @BotFather |
| `ADMIN_IDS` | **Yes** | — | Comma-separated Telegram user IDs for admin access |
| `WEBHOOK_URL` | No | — | Public URL for webhook mode (e.g. Railway deploy) |
| `WEBHOOK_PORT` | No | `8000` | Port for webhook / health HTTP server |
| `PROXY_ENABLED` | No | `true` | Set `false` to disable free proxy pool |
| `SEARCH_TIMEOUT_4KHD` | No | `8.0` | Search timeout for 4KHD.com (seconds) |
| `SEARCH_TIMEOUT_XC` | No | `6.0` | Search timeout for XChina.co |
| `SEARCH_TIMEOUT_EH` | No | `12.0` | Search timeout for E-Hentai |
| `MAX_SEARCH_RESULTS` | No | `30` | Max results per search |
| `MAX_SEARCHES_PER_MINUTE` | No | `10` | Rate limit for non-VIP users |
| `EH_MEMBER_ID` | No | — | E-Hentai cookie (enables EH search) |
| `EH_PASS_HASH` | No | — | E-Hentai cookie |
| `DB_PATH` | No | `./data/bot.db` | SQLite database path |

## Commands

| Command | Description |
|---|---|
| `/start` | Main menu |
| `/search <keyword>` | Search galleries |
| `/random` | Random recommendation |
| `/my` | VIP status, favorites, invite code |
| `/help` | Usage help |
| `/subscribe <keyword> [source]` | Subscribe to keyword updates (VIP only) |
| `/unsubscribe <keyword> [source]` | Unsubscribe |
| `/admin` | Admin dashboard (stats, card generation, user list) |
| `/report` | 7-day operations report (admin only) |
| `/setvip <uid> [days]` | Grant VIP to user (admin only) |

## Architecture

```
main.py          — Application entry point (wires all modules + SQLite + Flask admin)
handlers_*.py    — Command, callback, text, menu, search, subscription handlers
display.py       — Gallery detail display (search results, pagination, full images)
scraper.py       — 4KHD.com + XChina.co scraping (httpx + curl_cffi with fallback)
scraper_eh.py    — E-Hentai scraping (cookies-auth, magnet links via bencode parser)
database.py      — SQLite WAL-mode database layer (async via ThreadPoolExecutor)
pre_cache.py     — Background recommendation pool (20 entries, 3-platform)
proxy_pool.py    — Free proxy pool manager (auto-refresh, full validation)
bot_utils.py     — Shared constants, helpers, locks, VIP/user state
bot_context.py   — Typed dataclass for all mutable runtime state
config.py        — Environment-based configuration
web_admin.py     — Flask admin dashboard (stats, trends, DB health)
```

## Data

All persistent data is in `data/bot.db` (SQLite, WAL mode).  
Automatic daily backups at 3am to `data/backups/bot-YYYY-MM-DD.db`, keeping 7 days.  
Logs rotate at 10MB with 5 backups in `data/bot.log`.

## Health Endpoints (port 8000)

| Path | Response |
|---|---|
| `/` | `OK` (plain text) |
| `/health/db` | `{"database": "ok" \| "error"}` |
| `/health/ready` | Full status: database, proxy pool size, pre-cache size |
