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
import sys
import os
import threading
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
    cmd_my, cmd_help, cmd_search, cmd_random, cmd_report,
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

# ========== Logging ==========

def _setup_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

# ========== Periodic Cleanup ==========

async def _periodic_cleanup(application):
    last_reminder_day = 0
    while True:
        await asyncio.sleep(600)
        await cleanup_all()
        gc.collect()
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
    import os as _os
    data_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data")
    if _os.path.isdir(data_dir):
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
            await app.initialize()  # triggers post_init → _startup → proxy_pool + pre_cache + bg tasks
            await app.start()
            await app.updater.start_polling(allowed_updates=["message", "callback_query", "inline_query"])
            try:
                while True:
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                await shutdown(app)

        try:
            asyncio.run(_start_polling())
        except KeyboardInterrupt:
            asyncio.run(shutdown(app, "SIGINT"))


if __name__ == "__main__":
    main()
