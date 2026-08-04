"""main.py — Application entry point (uses the refactored handler modules).

This module wires together all refactored components:
  - SQLite database (database.py)
  - Flask web admin dashboard (web_admin.py)
  - Telegram bot with inline/command/callback/text handlers
  - Background tasks: cleanup, VIP push, subscription push, DB backup

Supports both webhook (Railway) and polling (dev) modes.
"""
import asyncio
import gc
import logging
import signal
import sys
import os
import threading
import time
import urllib.request
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, filters, ContextTypes,
)

from config import config
from database import (
    start_database, stop_database,
    db_load_vip, db_load_users, db_load_invites,
    db_delete_expired_vip, db_vip_count, db_migrate_from_json,
)
from bot_utils import (
    init_locks, sync_from_context,
    VIP_USERS, ALL_USERS, INVITES,
    cleanup_all, is_vip, now_ts, PURCHASE_URL, _ONE_DAY,
)
from web_admin import run_flask
from proxy_pool import start_proxy_pool, stop_proxy_pool
from pre_cache import start_pre_cache

# Handler imports
from handlers_commands import (
    cmd_start, cmd_setvip, cmd_admin, cmd_stats,
    cmd_my, cmd_help, cmd_search, cmd_random, cmd_report, cmd_broadcast, cmd_addcards,
)
from handlers_callbacks import handle_callback
from handlers_text import handle_text
from handlers_menu import handle_inline
from handlers_subs import (
    cmd_subscribe, cmd_unsubscribe,
    _subscription_push_loop, _vip_daily_push,
    error_handler, _db_backup_loop,
)

logger = logging.getLogger(__name__)

# ========== Two-Tier Watchdog ==========
# Tier 1: asyncio heartbeat (heartbeat updated every 60s in polling loop)
# Tier 2: HTTP health check (pings Flask /health/ready endpoint)
# If both tiers fail, the process is truly dead, force-kill so Railway restarts the container.

_heartbeat = time.time()
_shutdown_requested = threading.Event()
_main_loop_ref = None
_watchdog_port = int(os.environ.get('PORT', 8000))

def _update_heartbeat():
    global _heartbeat
    _heartbeat = time.time()

def _http_health_check():
    try:
        req = urllib.request.Request(
            'http://127.0.0.1:' + str(_watchdog_port) + '/health/ready',
            method='GET',
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False

def _watchdog():
    http_fail_count = 0
    while True:
        time.sleep(60)
        if _shutdown_requested.is_set():
            return
        # Tier 2: HTTP health check
        if not _http_health_check():
            http_fail_count += 1
            if http_fail_count >= 3:
                logger.critical(
                    'Watchdog: HTTP health check failed %d times, process is dead. Force-killing...',
                    http_fail_count,
                )
                os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
        else:
            http_fail_count = 0
        # Tier 1: asyncio heartbeat
        if http_fail_count == 0:
            elapsed = time.time() - _heartbeat
            if elapsed > 600:
                logger.critical(
                    'Watchdog: bot unresponsive for %.0fs, triggering graceful restart',
                    elapsed,
                )
                _shutdown_requested.set()
                loop = _main_loop_ref
                if loop is not None and loop.is_running():
                    def _stop_loop():
                        try:
                            for task in asyncio.all_tasks(loop):
                                task.cancel()
                        except Exception:
                            pass
                        loop.stop()
                    loop.call_soon_threadsafe(_stop_loop)
threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()
# ========== Logging ==========

def _setup_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

# ========== Periodic Cleanup ==========

async def _periodic_cleanup(application):
    last_reminder_day = 0
    last_client_recycle = 0.0
    last_proxy_cleanup = 0.0
    while True:
        await asyncio.sleep(600)
        await cleanup_all()
        gc.collect()
        now_ts_val = time.time()

        # Force httpx client recycle every 2 hours to prevent connection leaks
        if now_ts_val - last_client_recycle > 7200:
            try:
                from scraper import _get_client as _sc_get_client
                from scraper import _client_lock as _sc_client_lock
                import scraper as _sc
                async with _sc_client_lock:
                    if _sc._httpx_client is not None:
                        try:
                            await _sc._httpx_client.aclose()
                        except Exception:
                            pass
                        _sc._httpx_client = None
                last_client_recycle = now_ts_val
                logger.debug("Periodic httpx client recycled")
            except Exception as ex:
                logger.debug("Periodic httpx recycle failed: %s", ex)

        # Clean up stale proxy clients every 1 hour
        if now_ts_val - last_proxy_cleanup > 3600:
            try:
                import scraper as _sc2
                async with _sc2._proxy_client_lock:
                    now = time.time()
                    expired = [p for p, (_, t) in list(_sc2._proxy_clients.items()) if now - t > 300]
                    for p in expired:
                        try:
                            await _sc2._proxy_clients[p][0].aclose()
                        except Exception:
                            pass
                        del _sc2._proxy_clients[p]
                    if expired:
                        logger.debug("Cleaned %d stale proxy clients", len(expired))
                last_proxy_cleanup = now_ts_val
            except Exception as ex:
                logger.debug("Periodic proxy cleanup failed: %s", ex)

        # Log memory usage for leak detection
        try:
            import psutil
            proc = psutil.Process()
            mem_mb = proc.memory_info().rss / 1024 / 1024
            if mem_mb > 300:
                logger.warning("High memory usage: %.0f MB", mem_mb)
        except Exception:
            pass

        today = datetime.now().strftime("%Y%m%d")
        if today != last_reminder_day:
            last_reminder_day = today
            now = now_ts()
            for uid, expiry in list(VIP_USERS.items()):
                if expiry is not None and 0 < expiry - now <= _ONE_DAY:
                    exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
                    try:
                        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                        await application.bot.send_message(
                            chat_id=uid,
                            text=f"⏰ <b>VIP即将到期提醒</b>\n\n你的VIP会员将于 <b>{exp_str}</b> 到期，请及时续费哦～",
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)
                            ]]))
                    except Exception as e:
                        logger.debug("VIP reminder send failed for user %s: %s", uid, e)

# ========== Startup ==========

async def _startup(application):
    """Run after database is ready in both webhook and polling mode."""
    await start_proxy_pool()
    await start_pre_cache()

    # Auto-migrate from JSON if there are old data files
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    if os.path.isdir(data_dir):
        migration_stats = await db_migrate_from_json(data_dir)
        if any(v > 0 for v in migration_stats.values() if isinstance(v, int)):
            logger.info("Auto-migration complete: %s", migration_stats)
        # Re-load data after migration
        await _load_data()
    else:
        logger.info("No data/ directory found for migration")

    # Start background tasks
    asyncio.create_task(_periodic_cleanup(application))
    asyncio.create_task(_vip_daily_push(application))
    asyncio.create_task(_subscription_push_loop(application))
    asyncio.create_task(_db_backup_loop())

    # Set bot commands
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 主菜单"),
        BotCommand("search", "🔍 搜索图集"),
        BotCommand("random", "🎲 随机推荐"),
        BotCommand("my", "👤 我的VIP"),
        BotCommand("subscribe", "🔔 订阅关键词"),
        BotCommand("unsubscribe", "🔕 取消订阅"),
        BotCommand("help", "📖 使用帮助"),
    ])
    logger.info("Bot started — all services running")

async def shutdown(app, signal_str=None):
    if signal_str:
        logger.info(f"Received signal {signal_str}, shutting down...")
    else:
        logger.info("Shutting down...")
    try:
        await stop_proxy_pool()
        await stop_database()
        await app.stop()
        await app.shutdown()
    except Exception as e:
        logger.warning("Shutdown error: %s", e)
    logger.info("Bot stopped.")

# ========== Register Handlers ==========

_CMD_HANDLERS = [
    ("start", cmd_start),
    ("help", cmd_help),
    ("search", cmd_search),
    ("random", cmd_random),
    ("my", cmd_my),
    ("setvip", cmd_setvip),
    ("admin", cmd_admin),
    ("stats", cmd_stats),
    ("report", cmd_report),
    ("broadcast", cmd_broadcast),
    ("addcards", cmd_addcards),
    ("subscribe", cmd_subscribe),
    ("unsubscribe", cmd_unsubscribe),
]

async def _load_data():
    """Load persistent data from SQLite into module globals."""
    logger.info("Loading data from database...")

    # Load VIPs
    VIP_USERS.clear()
    VIP_USERS.update(await db_load_vip())

    # Load all users
    ALL_USERS.clear()
    ALL_USERS.update(await db_load_users())

    # Load invites
    INVITES.clear()
    INVITES.update(await db_load_invites())

    # Ensure at least one admin VIP exists
    if not VIP_USERS and config.ADMIN_IDS:
        from database import db_save_vip
        for aid in config.ADMIN_IDS:
            VIP_USERS[aid] = None
            await db_save_vip(aid, None)

    # Sync to context (backward compat)
    sync_from_context()

    logger.info(f"Loaded {len(VIP_USERS)} VIP users, {len(ALL_USERS)} total users, {len(INVITES)} invites")

def main():
    _setup_logging()

    # Validate config
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error("Config error: " + str(e))
        sys.exit(1)

    # Initialize async locks
    init_locks()

    # Build the Application
    app = Application.builder() \
        .token(config.BOT_TOKEN) \
        .post_init(_startup) \
        .concurrent_updates(True) \
        .build()

    # Register command handlers
    for cmd, handler in _CMD_HANDLERS:
        app.add_handler(CommandHandler(cmd, handler))

    # Register message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Register callback query handler
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Register inline query handler
    app.add_handler(InlineQueryHandler(handle_inline))

    # Register error handler
    app.add_error_handler(error_handler)

    # ========== Start ==========
    if config.WEBHOOK_URL:
        logger.info("Starting in webhook mode: " + config.WEBHOOK_URL)

        async def _boot():
            await start_database()
            await _load_data()
            # Auto-migrate from JSON if there are old data files
            import os as _os
            data_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data")
            if _os.path.isdir(data_dir):
                from database import db_migrate_from_json
                migration_stats = await db_migrate_from_json(data_dir)
                if any(v > 0 for v in migration_stats.values() if isinstance(v, int)):
                    logger.info("Auto-migration complete: %s", migration_stats)
                # Re-load data after migration
                await _load_data()
            else:
                logger.info("No data/ directory found for migration")
            await app.initialize()
            await app.start()
            # Start Flask admin on a separate port
            try:
                run_flask(port=config.WEBHOOK_PORT + 1)
            except Exception as e:
                logger.warning(f"Flask admin not started: {e}")
            await app.bot.set_webhook(url=config.WEBHOOK_URL + "/webhook")
            logger.info("Webhook set. Starting HTTP server...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_boot())
        try:
            app.run_webhook(
                listen="0.0.0.0",
                port=config.WEBHOOK_PORT,
                url_path="webhook",
                webhook_url=config.WEBHOOK_URL + "/webhook",
            )
        except KeyboardInterrupt:
            loop.run_until_complete(shutdown(app, "SIGINT"))
    else:
        # Polling mode
        logger.info("Starting in polling mode (with health + admin server)")

        async def _boot():
            await start_database()
            await _load_data()
            # Auto-migrate from JSON if there are old data files
            import os as _os
            data_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data")
            if _os.path.isdir(data_dir):
                from database import db_migrate_from_json
                migration_stats = await db_migrate_from_json(data_dir)
                if any(v > 0 for v in migration_stats.values() if isinstance(v, int)):
                    logger.info("Auto-migration complete: %s", migration_stats)
                # Re-load data after migration
                await _load_data()
            else:
                logger.info("No data/ directory found for migration")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_boot())

        # Start Flask admin
        flask_port = int(os.environ.get("PORT", 8000))
        try:
            run_flask(port=flask_port)
        except Exception as e:
            logger.warning(f"Flask admin not started: {e}")

        async def _start_polling():
            nonlocal delay
            global _main_loop_ref
            _main_loop_ref = asyncio.get_running_loop()
            _shutdown_requested.clear()
            await app.initialize()  # triggers post_init → _startup → proxy_pool + pre_cache + bg tasks
            await app.start()
            await app.updater.start_polling(allowed_updates=["message", "callback_query", "inline_query"])
            try:
                while True:
                    _update_heartbeat()
                    if _shutdown_requested.is_set():
                        logger.warning("Watchdog shutdown signal received, restarting...")
                        break
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.warning("Polling loop cancelled, shutting down...")
            finally:
                try:
                    await shutdown(app)
                except Exception:
                    pass

        delay = 5
        max_delay = 60
        while True:
            try:
                asyncio.run(_start_polling())
                if _shutdown_requested.is_set():
                    _shutdown_requested.clear()
                    logger.warning("Restarting after watchdog shutdown...")
                    time.sleep(3)
                    continue
                break
            except KeyboardInterrupt:
                try:
                    asyncio.run(shutdown(app, "SIGINT"))
                except Exception:
                    pass
                break
            except Exception as e:
                logger.error(f"Bot crashed, restarting in {delay}s: {e}")
                time.sleep(delay)
                delay = min(delay * 2, max_delay)


if __name__ == "__main__":
    main()
