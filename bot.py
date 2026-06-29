""" bot.py — Multi-Bot launcher with Polling & Webhook support """
import os
import sys
import asyncio
import random
import threading
import time
import json
from pathlib import Path
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from config import config
from deep_dream import summarize_user_conversation
from roles import ROLES, get_role
from database import db
from utils.logger import logger
try:
    from db_sync import download_db, upload_db, sync_loop
    _db_sync_ok = True
except Exception:
    logger.warning("db_sync not available, DB persistence disabled")
    _db_sync_ok = False
    download_db = lambda x: False
    upload_db = lambda x: False
    sync_loop = lambda x, y: None
from utils.rate_limit import check_rate_limit
from handlers.commands import cmd_start, cmd_checkin, cmd_redeem, cmd_gencode
from handlers.pay import cmd_gift_status, gift_callback
from handlers.messages import (
    handle_message, handle_media_message,
    error_handler, get_upload_conversation_handler,
)
from handlers.group import handle_group_message
from handlers.voice import handle_voice_message
from handlers.admin import cmd_broadcast, cmd_stats, cmd_user_info, cmd_set_vip, cmd_yuanwei_orders
from handlers.admin_panel import admin_main, admin_callback
from handlers.payment import handle_paywall_callback
from handlers.conversation import cmd_clear, cmd_export, cmd_reset, cmd_retry
from handlers.yuanwei import get_yuanwei_conversation_handler, handle_yuanwei_callback
from handlers.keepsake import get_keepsake_conversation_handler, handle_keepsake_callback
from handlers.testimonial import cmd_screenshot, cmd_post_testimonial

# ── Shared shutdown flag ──
_shutdown_flag = threading.Event()
shutdown_event = asyncio.Event()
_global_jobs_registered = False
_start_time = time.time()


def _get_memory_usage() -> dict:
    """Read memory usage from /proc/self/status (Linux only)."""
    try:
        with open("/proc/self/status") as f:
            raw = f.read()
        vm_size = vm_rss = 0
        for line in raw.splitlines():
            if line.startswith("VmSize:"):
                vm_size = int(line.split()[1])
            elif line.startswith("VmRSS:"):
                vm_rss = int(line.split()[1])
        return {"vm_size_kb": vm_size, "vm_rss_kb": vm_rss}
    except Exception:
        return {"vm_size_kb": 0, "vm_rss_kb": 0}


def validate_config() -> list[str]:
    """Return list of config errors; does NOT exit."""
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error(f"Config error: {err}")
    else:
        logger.info("Config validation passed")
    return errors


async def _rate_limit_check(update: Update, user_id: int, is_admin: bool) -> bool:
    if not config.RATE_LIMIT_ENABLED:
        return True
    allowed = await check_rate_limit(user_id, is_admin)
    if not allowed:
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text("🚀 消息太频繁啦，稍等一下再聊～")
    return allowed


def _wrap_handler(handler):
    """Wrap CommandHandler, MessageHandler, or CallbackQueryHandler with rate limiting."""
    async def wrapped(update: Update, context):
        user = update.effective_user
        if user is None:
            return await handler(update, context)
        user_id = user.id
        is_admin = user_id in config.ADMIN_IDS
        if not await _rate_limit_check(update, user_id, is_admin):
            return
        return await handler(update, context)
    return wrapped


# ── Threading HTTP server for healthcheck + webhook ──
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server"""
    daemon_threads = True


class WebhookHandler(BaseHTTPRequestHandler):
    apps: dict = {}
    loop: asyncio.AbstractEventLoop = None

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._send_health()
        elif self.path == "/health/json":
            self._send_health_json()
        elif self.path.startswith("/payment/callback"):
            self._handle_epay_callback()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path.startswith("/webhook/"):
            role_id = self.path.split("/")[-1]
            app = self.apps.get(role_id)
            if not app:
                self.send_error(404, f"Unknown role: {role_id}")
                return
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                update_data = json.loads(body)
                asyncio.run_coroutine_threadsafe(
                    app.process_update(Update.de_json(update_data, app.bot)),
                    self.loop
                )
                self.send_response(200)
                self.end_headers()
            except Exception as e:
                logger.error(f"webhook processing failed role={role_id}: {e}")
                self.send_error(500)
        elif self.path.startswith("/payment/callback"):
            self._handle_epay_callback()
        else:
            self.send_error(404)

    def _send_health(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "active_bots": len(self.apps),
            "provider": config.LLM_PROVIDER,
        }).encode())

    def _send_health_json(self):
        try:
            from database import db as _db
            user_count = _db.get_total_user_count() if hasattr(_db, "get_total_user_count") else 0
        except Exception:
            user_count = 0
        memory = _get_memory_usage()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "active_bots": len(self.apps),
            "users": user_count,
            "provider": config.LLM_PROVIDER,
            "memory": memory,
            "global_jobs_registered": _global_jobs_registered,
            "uptime_seconds": int(time.time() - _start_time),
        }).encode())

    def _handle_epay_callback(self):
        """Receive EPay async payment notification"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            from urllib.parse import parse_qs
            params = parse_qs(body)
            order_id = params.get("out_trade_no", [None])[0]
            trade_status = params.get("trade_status", [None])[0]
            if order_id and trade_status == "TRADE_SUCCESS":
                import asyncio
                from handlers.payment import handle_epay_callback
                loop = self.loop if hasattr(self, 'loop') and self.loop else None
                if loop:
                    asyncio.run_coroutine_threadsafe(
                        handle_epay_callback(order_id, trade_status), loop
                    )
            else:
                logger.warning(f"EPay callback: order={order_id} status={trade_status}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"success")
        except Exception as e:
            logger.error(f"EPay callback error: {e}")
            self.send_error(500)

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs


def run_healthcheck():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    logger.info(f"Healthcheck server listening on port {port}")
    server.serve_forever()


async def _load_plugins():
    try:
        from plugins import plugin_manager
        await plugin_manager.load_all()
    except Exception as e:
        logger.warning(f"Plugin loading skipped: {e}")


def start_admin_thread(port: int = 7860):
    import threading as _th
    def _run():
        try:
            from admin_panel import start_admin_panel
            start_admin_panel(port)
        except Exception as e:
            logger.warning(f"Admin panel unavailable (gradio not installed?): {e}")
    t = _th.Thread(target=_run, daemon=True, name="admin-panel")
    t.start()
    logger.info(f"Admin panel starting on port {port}")


def start_keepalive():
    """Keepalive thread: auto-ping /health to prevent Railway sleep"""
    if not config.ENABLE_KEEPALIVE:
        return
    def _ping():
        while not _shutdown_flag.is_set():
            time.sleep(config.KEEPALIVE_INTERVAL)
            try:
                port = os.environ.get("PORT", "8080")
                url = f"http://127.0.0.1:{port}/health"
                urllib.request.urlopen(url, timeout=5)
            except Exception:
                pass
    t = threading.Thread(target=_ping, daemon=True, name="keepalive")
    t.start()


def build_single_bot(role_id: str, token: str) -> Application:
    """Build a single role Bot Application"""
    role = ROLES.get(role_id)
    if not role:
        logger.error(f"Role not found: {role_id}")
        sys.exit(1)

    app = Application.builder().token(token).build()
    app.bot_data["role_id"] = role_id

    # ── Commands ──
    app.add_handler(CommandHandler("start", _wrap_handler(cmd_start)))
    app.add_handler(CommandHandler("checkin", _wrap_handler(cmd_checkin)))
    app.add_handler(CommandHandler("redeem", _wrap_handler(cmd_redeem)))
    app.add_handler(CommandHandler("gencode", _wrap_handler(cmd_gencode)))
    app.add_handler(CommandHandler("gift", _wrap_handler(cmd_gift_status)))
    app.add_handler(CommandHandler("broadcast", _wrap_handler(cmd_broadcast)))
    app.add_handler(CommandHandler("stats", _wrap_handler(cmd_stats)))
    app.add_handler(CommandHandler("userinfo", _wrap_handler(cmd_user_info)))
    app.add_handler(CommandHandler("setvip", _wrap_handler(cmd_set_vip)))
    app.add_handler(CommandHandler("orders", _wrap_handler(cmd_yuanwei_orders)))
    app.add_handler(CommandHandler("announce", _wrap_handler(cmd_announce)))
    app.add_handler(CommandHandler("clear", _wrap_handler(cmd_clear)))
    app.add_handler(CommandHandler("export", _wrap_handler(cmd_export)))
    app.add_handler(CommandHandler("reset", _wrap_handler(cmd_reset)))
    app.add_handler(CommandHandler("retry", _wrap_handler(cmd_retry)))
    app.add_handler(CommandHandler("screenshot", _wrap_handler(cmd_screenshot)))
    app.add_handler(CommandHandler("post", _wrap_handler(cmd_post_testimonial)))

    # ── Conversations ──
    app.add_handler(get_upload_conversation_handler())
    app.add_handler(get_yuanwei_conversation_handler())
    app.add_handler(get_keepsake_conversation_handler())

    # ── Messages ──
    if config.ENABLE_GROUP_CHAT:
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_media_message))
    if config.CF_ACCOUNT_ID and config.CF_API_TOKEN:
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))

    # ── Callbacks ──
    app.add_handler(CallbackQueryHandler(handle_paywall_callback, pattern="^pay_"))
    app.add_handler(CommandHandler("admin", admin_main))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin:"))
    app.add_handler(CallbackQueryHandler(handle_yuanwei_callback, pattern="^yw_"))
    app.add_handler(CallbackQueryHandler(handle_keepsake_callback, pattern="^ks_"))
    app.add_handler(CallbackQueryHandler(gift_callback, pattern="^gift_"))

    # ── Error ──
    app.add_error_handler(error_handler)

    return app


def _register_global_jobs(app: Application):
    """Register global (once-per-process) tasks — cleanup, backup, deep dream."""
    global _global_jobs_registered
    if _global_jobs_registered:
        return
    _global_jobs_registered = True
    # -- Inactive user cleanup: daily --
    app.job_queue.run_repeating(
        lambda ctx: db.cleanup_inactive_users(180),
        interval=86400,
        first=3600,
        name="user_cleanup",
    )

    # ── DB Backup: every hour ──
    app.job_queue.run_repeating(
        lambda ctx: upload_db(config.DB_PATH),
        interval=3600,
        first=600,
        name="db_backup",
    )

    # ── Deep Dream: nightly at 3am for ALL roles ──
    import datetime as _dt
    now = _dt.datetime.now()
    target = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= now:
        target += _dt.timedelta(days=1)
    first_delay = (target - now).total_seconds()
    app.job_queue.run_repeating(
        lambda ctx: _deep_dream_all_roles(ctx),
        interval=86400,
        first=int(first_delay),
        name="deep_dream",
    )


async def _deep_dream_all_roles(context):
    """Run deep dream for all active roles."""
    from config import config as _cfg
    active = _cfg.get_active_bots()
    for rid in active:
        try:
            users = db.get_active_users_for_role(rid)
            for uid in users[:50]:
                await summarize_user_conversation(uid, rid)
        except Exception as e:
            logger.error(f"Deep Dream job error ({rid}): {e}")


async def _deep_dream_job(context, role_id: str):
    """Legacy single-role deep dream (kept for compatibility)."""
    await _deep_dream_all_roles(context)


async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    if not config.ANNOUNCEMENT_CHANNEL:
        await update.message.reply_text("❌ ANNOUNCEMENT_CHANNEL not configured.")
        return

    role_id = context.args[0] if context.args else context.bot_data.get("role_id", "xiaolu")
    if role_id not in ROLES:
        await update.message.reply_text(f"❌ Unknown role: {role_id}")
        return

    db.clear_announcement(role_id)
    app = context.application
    result = await announce_new_role(app, role_id)
    if result:
        await update.message.reply_text(f"✅ {ROLES[role_id]['name']} announcement published!")
    else:
        await update.message.reply_text(f"❌ {ROLES[role_id]['name']} announcement failed. Check logs.")


# ── Announcement helpers ──
def _find_reference_photo(role_id: str) -> str | None:
    ref_dir = Path(__file__).parent / "media" / role_id / "参考图"
    if ref_dir.is_dir():
        photos = list(ref_dir.glob("*")) + list(ref_dir.glob("*.jpg")) + list(ref_dir.glob("*.png"))
        if photos:
            return str(random.choice(photos))
    return None


def _build_announce_caption(role: dict) -> str:
    name = role.get("name", "Unknown")
    city = role.get("city", "Unknown")
    age = role.get("age", "?")
    personality = role.get("personality", "")
    return (
        f"🌟 {name} · {age}岁 · {city}\n\n"
        f"{personality}\n\n"
        f"💬 点击下方按钮，开始聊天吧～"
    )


async def announce_new_role(app, role_id: str) -> bool:
    role = ROLES.get(role_id)
    if not role:
        return False
    if not config.ANNOUNCEMENT_CHANNEL:
        return False
    if db.is_announced(role_id, config.ANNOUNCEMENT_CHANNEL):
        return False

    try:
        me = await app.bot.get_me()
        bot_link = f"https://t.me/{me.username}"
    except Exception as e:
        logger.warning(f"Cannot get bot username for {role_id}: {e}")
        return False

    photo_path = _find_reference_photo(role_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 开始聊天", url=bot_link)]
    ])
    caption = _build_announce_caption(role)

    try:
        if photo_path and Path(photo_path).is_file():
            with open(photo_path, "rb") as f:
                await app.bot.send_photo(
                    chat_id=config.ANNOUNCEMENT_CHANNEL,
                    photo=f,
                    caption=caption,
                    reply_markup=keyboard,
                )
        else:
            await app.bot.send_message(
                chat_id=config.ANNOUNCEMENT_CHANNEL,
                text=caption,
                reply_markup=keyboard,
            )
        db.mark_announced(role_id, config.ANNOUNCEMENT_CHANNEL)
        name = role.get("name", role_id)
        logger.info(f"Channel announcement sent: {name} → {config.ANNOUNCEMENT_CHANNEL}")
        return True
    except Exception as e:
        logger.error(f"Announcement failed for {role_id}: {e}", exc_info=True)
        return False


# ── Main ──
async def main():
    global _shutdown_flag  # kept for compat

    # ── Config validation (non-fatal) ──
    errors = validate_config()
    if errors:
        logger.warning(f"Starting with {len(errors)} config errors — set env vars in Railway dashboard")

    # ── Graceful shutdown ──
    import signal as _signal

    def _handle_signal(signum, frame):
        global _shutdown_flag  # kept for compat
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        _shutdown_flag.set()
        shutdown_event.set()

    _signal.signal(_signal.SIGTERM, _handle_signal)
    _signal.signal(_signal.SIGINT, _handle_signal)


    # -- Healthcheck server starts FIRST (before DB sync) --
    threading.Thread(target=run_healthcheck, daemon=True).start()

    # ── DB Sync: restore from GitHub on startup ──

    try:

        db_path = config.DB_PATH

        if not os.path.exists(db_path) or os.path.getsize(db_path) < 1024:

            logger.info("DB Sync: Local DB missing/empty, downloading from GitHub...")

            if _db_sync_ok: download_db(db_path)

    except Exception as e:

        logger.error(f"DB Sync startup error: {e}")



    # ── DB Sync: background upload loop (every 30 min) ──

    if _db_sync_ok:
        _db_sync_task = asyncio.create_task(sync_loop(config.DB_PATH, 1800))

    logger.info(f"DB Sync: Auto-backup to GitHub every 30 min, path={config.DB_PATH}")




    # ── Keepalive ──
    start_keepalive()

    # ── Admin panel ──
    admin_port = int(os.environ.get("ADMIN_PORT", "7860"))
    start_admin_thread(admin_port)

    # ── Plugins ──
    await _load_plugins()

    # ── Active bots ──
    active_bots = config.get_active_bots()
        # ── Auto VIP: owner always max tier ──
    OWNER_ID = config.OWNER_ID

    try:
        db.create_user(OWNER_ID)
        db.set_vip(OWNER_ID)
        db.update_profile_tier(OWNER_ID, 1)
        from roles import ROLES
        for rid in ROLES:
            db.set_unlock_tier(OWNER_ID, rid, tier=3, amount=0)
        logger.info(f"Owner {OWNER_ID}: VIP permanent + all roles tier 3")
    except Exception as e:
        logger.error(f"Auto VIP setup failed: {e}")

    logger.info(f"Active bots: {list(active_bots.keys()) if active_bots else 'NONE'}")

    if not active_bots:
        logger.warning("No bot tokens configured — healthcheck only. Set *_BOT_TOKEN env vars in Railway.")
        # Keep the event loop alive so healthcheck server stays up
        await shutdown_event.wait()
        return

    if config.WEBHOOK_URL:
        # ── Webhook mode ──
        apps = {}
        for role_id, token in active_bots.items():
            apps[role_id] = build_single_bot(role_id, token)

        # Override the healthcheck handler with bot apps
        # The healthcheck server is already running; we need to attach apps to it
        # Find the existing server and set apps
        port = int(os.environ.get("PORT", "8080"))
        WebhookHandler.apps = apps
        WebhookHandler.loop = asyncio.get_running_loop()

        base_url = config.WEBHOOK_URL.rstrip("/")
        for role_id, app in apps.items():
            role = ROLES[role_id]
            webhook_url = f"{base_url}/webhook/{role_id}"
            await app.initialize()
            await app.start()
            await app.bot.set_webhook(url=webhook_url)
            logger.info(f"{role['name']} webhook set: {webhook_url}")

            # New role channel announcement
            await announce_new_role(app, role_id)

        # Register global tasks only on the first bot
        if apps:
            first_app = list(apps.values())[0]
            _register_global_jobs(first_app)

        logger.info(f"All {len(apps)} bots running via webhook")

        await shutdown_event.wait()
    else:
        # ── Polling mode ──
        tasks = [run_bot_polling(rid, tok, idx, len(active_bots)) for idx, (rid, tok) in enumerate(active_bots.items())]
        await asyncio.gather(*tasks)

    # Cleanup
    if hasattr(db, "conn"):
        try:
            db.conn.close()
        except Exception:
            pass


# ── Polling mode ──
async def run_bot_polling(role_id: str, token: str, bot_index: int = 0, total_bots: int = 1):
    role = ROLES.get(role_id, {"name": role_id})
    app = build_single_bot(role_id, token)
    # Register global tasks only on the first bot
    if bot_index == 0:
        _register_global_jobs(app)
    await app.initialize()
    await app.start()
    logger.info(f"Polling started: {role['name']} ({role_id})")
    # Use run_polling pattern to avoid .updater deprecation
    polling_task = asyncio.create_task(
        app.updater.start_polling(allowed_updates=["message", "callback_query"])
    )
    # Keep alive
    await shutdown_event.wait()
    polling_task.cancel()
    await app.stop()
    await app.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
