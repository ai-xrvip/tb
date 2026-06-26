"""
=========== bot.py ===========
主 Bot 并发入口 —— 自动启动所有配置了 Token 的角色 Bot
支持 Polling（本地开发）和 Webhook（生产部署）

新增集成:
- 多 LLM 提供商 (providers/)
- 流式输出
- 插件系统 (plugins/)
- 群聊 @提及 (handlers/group.py)
- 语音转文字 (handlers/voice.py)
- 管理员面板 (handlers/admin.py)
- 对话管理 (handlers/conversation.py)
- i18n 多语言
- 速率限制
"""
import os
import sys
import asyncio
import random
import threading
import time
from pathlib import Path
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from config import config
from deep_dream import summarize_user_conversation
from roles import ROLES, get_role
from database import db  # noqa: F401 —— db 在导入时自动建表
from utils.logger import logger
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
from handlers.payment import handle_paywall_callback
from handlers.conversation import cmd_clear, cmd_export, cmd_reset, cmd_retry
from handlers.yuanwei import get_yuanwei_conversation_handler, handle_yuanwei_callback
from handlers.keepsake import get_keepsake_conversation_handler, handle_keepsake_callback
from handlers.moments import send_moment_broadcast, handle_moment_reply, handle_moment_say, MOMENTS_INTERVAL_MIN, MOMENTS_INTERVAL_MAX
from handlers.testimonial import cmd_screenshot, cmd_post_testimonial


def validate_config():
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error(f"配置错误: {err}")
        sys.exit(1)
    logger.info("配置验证通过")


async def _rate_limit_check(update: Update, user_id: int, is_admin: bool) -> bool:
    """速率限制检查装饰器逻辑"""
    if not config.RATE_LIMIT_ENABLED:
        return True
    allowed = await check_rate_limit(user_id, is_admin)
    if not allowed:
        await update.message.reply_text("⏳ 消息太频繁啦，稍等一下再聊～")
    return allowed


def _wrap_handler(handler):
    """包装处理器，添加速率限制"""
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



async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /announce <role_id> —— 管理员手动发布频道公告（无视已公告标记）"""
    user = update.effective_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ 仅限管理员使用。")
        return

    if not config.ANNOUNCEMENT_CHANNEL:
        await update.message.reply_text("❌ 未设置 ANNOUNCEMENT_CHANNEL 环境变量。")
        return

    role_id = context.args[0] if context.args else context.bot_data.get("role_id", "xiaolu")
    if role_id not in ROLES:
        await update.message.reply_text(f"❌ 未知角色：{role_id}")
        return

    # 强制重置公告标记
    db.clear_announcement(role_id)

    app = context.application
    result = await announce_new_role(app, role_id)
    if result:
        await update.message.reply_text(f"✅ {ROLES[role_id]['name']} 频道公告已发布！")
    else:
        await update.message.reply_text(f"❌ {ROLES[role_id]['name']} 公告发布失败，请查看日志。")


def build_single_bot(role_id: str, token: str) -> Application:
    """构建单个角色的 Bot Application"""
    role = ROLES.get(role_id)
    if not role:
        logger.error(f"角色配置不存在: {role_id}")
        sys.exit(1)

    app = Application.builder().token(token).build()
    app.bot_data["role_id"] = role_id

    # ── 命令处理器 ──
    app.add_handler(CommandHandler("start", _wrap_handler(cmd_start)))
    app.add_handler(CommandHandler("checkin", _wrap_handler(cmd_checkin)))
    app.add_handler(CommandHandler("redeem", _wrap_handler(cmd_redeem), has_args=True))
    app.add_handler(CommandHandler("gencode", cmd_gencode))  # admin only, no rate limit
    app.add_handler(CommandHandler("gifts", _wrap_handler(cmd_gift_status)))

    # ── 管理员命令 ──
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("announce", cmd_announce))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))  # admin-only via internal check
    app.add_handler(CommandHandler("post", cmd_post_testimonial))  # admin-only via internal check
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("user", cmd_user_info))
    app.add_handler(CommandHandler("setvip", cmd_set_vip))
    app.add_handler(CommandHandler("yworders", cmd_yuanwei_orders))

    # ── 对话管理命令 ──
    app.add_handler(CommandHandler("clear", _wrap_handler(cmd_clear)))
    app.add_handler(CommandHandler("export", _wrap_handler(cmd_export)))
    app.add_handler(CommandHandler("reset", _wrap_handler(cmd_reset)))
    app.add_handler(CommandHandler("retry", _wrap_handler(cmd_retry)))

    # ── 礼物按钮回调 ──
    app.add_handler(CallbackQueryHandler(gift_callback, pattern="^gift:"))
    app.add_handler(CallbackQueryHandler(handle_paywall_callback, pattern="^pay:"))
    app.add_handler(CallbackQueryHandler(handle_yuanwei_callback, pattern="^yuanwei:(info|buy|cancel)"))
    app.add_handler(get_yuanwei_conversation_handler())
    app.add_handler(CallbackQueryHandler(handle_keepsake_callback, pattern="^keepsake:(info|buy|cancel)"))
    app.add_handler(get_keepsake_conversation_handler())

    # 朋友圈定时推送（如未启用job_queue则跳过）
    if app.job_queue:
        import random
        interval = random.randint(MOMENTS_INTERVAL_MIN, MOMENTS_INTERVAL_MAX)
        app.job_queue.run_repeating(
            send_moment_broadcast,
            interval=interval,
        first=random.randint(60, 600),  # 启动后1-10分钟内首次触发
        name=f"moment_{role_id}",
    )

    # ── DB Backup: every hour ──
    async def _backup_job(context):
        db.backup_database()
    app.job_queue.run_repeating(_backup_job, interval=3600, first=600)

    # ── Deep Dream: nightly summary at 3 AM ──
    async def _deep_dream_job(context):
        role_id = context.bot_data.get("role_id", "")
        users = db.get_active_users_for_role(role_id)
        count = 0
        for uid in users[:50]:  # Max 50 users per role per night
            await summarize_user_conversation(uid, role_id)
            count += 1
        if count:
            logger.info(f"Deep Dream: summarized {count} users for {role_id}")

    import datetime as _dt
    now = _dt.datetime.now()
    target = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= now:
        target += _dt.timedelta(days=1)
    first_delay = (target - now).total_seconds()
    app.job_queue.run_repeating(_deep_dream_job, interval=86400, first=int(first_delay))
    # ── 朋友圈快捷回复回调 ──
    app.add_handler(CallbackQueryHandler(handle_moment_reply, pattern="^moment:reply:"))
    app.add_handler(CallbackQueryHandler(handle_moment_say, pattern="^moment:say:"))

    # ── 群聊 @提及 ──
    if config.ENABLE_GROUP_CHAT:
        app.add_handler(MessageHandler(
            filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
            _wrap_handler(handle_group_message),
        ))
        app.add_handler(MessageHandler(
            filters.TEXT & filters.ChatType.SUPERGROUP & ~filters.COMMAND,
            _wrap_handler(handle_group_message),
        ))

    # ── 语音消息 ──
    if config.ENABLE_STT:
        app.add_handler(MessageHandler(filters.VOICE, _wrap_handler(handle_voice_message)))

    # ── 普通消息（文本 + 媒体） ──
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        _wrap_handler(handle_message),
    ))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO |
        filters.AUDIO | filters.Document.ALL | filters.Sticker.ALL,
        _wrap_handler(handle_media_message),
    ))

    # ── 管理员上传对话 ──
    app.add_handler(get_upload_conversation_handler())

    # ── 错误处理 ──
    app.add_error_handler(error_handler)

    logger.info(f"Bot 构建完成 role={role_id} name={role['name']}")
    return app


# ── Polling 模式 ──

async def run_bot_polling(role_id: str, token: str):
    app = build_single_bot(role_id, token)
    role = ROLES[role_id]
    logger.info(f"启动 Polling: {role['name']} ({role_id})")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message", "callback_query"])

    # 新角色频道公告
    await announce_new_role(app, role_id)
    logger.info(f"{role['name']} 已上线！")
    while True:
        await asyncio.sleep(3600)


# ── Webhook 模式 ──

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server for concurrent webhook handling"""
    daemon_threads = True

class WebhookHandler(BaseHTTPRequestHandler):
    apps = {}
    loop = None

    def do_GET(self):
        if self.path == "/" or self.path == "/health":
            self._send_health()
            return
        if self.path == "/health/json":
            self._send_health_json()
            return
        self.send_response(404)
        self.end_headers()

    def _send_health(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def _send_health_json(self):
        import json as _json
        try:
            from database import db as _db
            stats = {
                "status": "ok",
                "total_users": len(_db.get_all_users()),
                "active_bots": len(self.apps),
                "version": "1.0",
            }
        except Exception:
            stats = {"status": "ok", "error": "db_unreachable"}
        body = _json.dumps(stats, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/webhook/"):
            role_id = self.path.split("/")[-1]
            app = self.apps.get(role_id)
            if app:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    import json
                    update = Update.de_json(json.loads(body), app.bot)
                    asyncio.run_coroutine_threadsafe(
                        app.process_update(update), self.loop
                    )
                except Exception as e:
                    logger.error(f"webhook processing failed role={role_id}: {e}")
                self.send_response(200)
                self.end_headers()
                return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_healthcheck():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    logger.info(f"healthcheck server listening on port {port}")
    server.serve_forever()


# ── 插件加载 ──

async def _load_plugins():
    """启动时加载已配置的插件"""
    if not config.ENABLED_PLUGINS:
        return
    try:
        from plugins import plugin_manager
        await plugin_manager.load_all(config.ENABLED_PLUGINS)
        loaded = plugin_manager.loaded_plugins
        if loaded:
            logger.info(f"Plugins loaded: {loaded}")
        else:
            logger.warning("No plugins were loaded")
    except Exception as e:
        logger.error(f"Plugin loading failed: {e}", exc_info=True)


# ── 保活（Railway 防休眠） ──

def start_admin_thread(port: int = 7860):
    """Start admin panel in a background thread"""
    import threading as _th
    def _run():
        from admin_panel import start_admin_panel
        start_admin_panel(port)
    t = _th.Thread(target=_run, daemon=True, name="admin-panel")
    t.start()
    logger.info(f"Admin panel starting on port {port}")


def start_keepalive():
    """后台线程：定时自 ping /health 端点，防止 Railway 休眠"""
    if not config.ENABLE_KEEPALIVE:
        logger.info("Keepalive disabled")
        return

    def _ping():
        # 等 30 秒让服务先启动
        time.sleep(30)
        while True:
            try:
                port = os.environ.get("PORT", "8080")
                url = f"http://127.0.0.1:{port}/health"
                urllib.request.urlopen(url, timeout=5)
                logger.debug(f"Keepalive ping OK → {url}")
            except Exception as e:
                logger.warning(f"Keepalive ping failed: {e}")
            time.sleep(config.KEEPALIVE_INTERVAL)

    t = threading.Thread(target=_ping, daemon=True, name="keepalive")
    t.start()
    logger.info(f"Keepalive started (interval={config.KEEPALIVE_INTERVAL}s)")

# ── 频道公告 ──

def _find_reference_photo(role_id: str) -> str | None:
    """在 media/{role}/参考图/ 中找第一张图片"""
    ref_dir = Path("media") / role_id / "参考图"
    if not ref_dir.is_dir():
        # 尝试在所有子目录找第一张图片
        media_dir = Path("media") / role_id
        if media_dir.is_dir():
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                for img in media_dir.rglob(ext):
                    return str(img)
        return None
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        for img in ref_dir.glob(ext):
            return str(img)
    return None


def _build_announce_caption(role: dict) -> str:
    """根据角色信息拼公告文案"""
    name = role.get("name", "")
    title = role.get("title", "")
    short = role.get("short", "")
    welcome = role.get("welcome", "")

    # 取 welcome 前两句
    lines = welcome.replace("\n", " ").split("。")
    excerpt = "。".join(lines[:2]).strip() + "。"

    caption = (
        f"🔥 新角色上线！\n\n"
        f"{name}\n"
        f"✨ {title}\n\n"
        f"💬 {short}\n\n"
        f"📝 {excerpt}\n\n"
        f"👇 点击下方按钮，马上和{name}私聊吧~"
    )
    return caption


async def announce_new_role(app, role_id: str) -> bool:
    """新角色激活时发频道公告（图片+文案+按钮），已公告过则跳过"""
    if not config.ANNOUNCEMENT_CHANNEL:
        return False

    if db.is_announced(role_id):
        logger.debug(f"Role {role_id} already announced, skipping")
        return False

    role = ROLES.get(role_id)
    if not role:
        return False

    try:
        # 获取 bot 用户名
        me = await app.bot.get_me()
        bot_link = f"https://t.me/{me.username}"
    except Exception as e:
        logger.warning(f"Cannot get bot username for {role_id}: {e}")
        return False

    # 找参考图
    photo_path = _find_reference_photo(role_id)

    # 拼按钮
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
    validate_config()

    # ── Graceful shutdown ──
    import signal as _signal
    _shutdown_flag = False

    def _handle_signal(signum, frame):
        nonlocal _shutdown_flag
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        _shutdown_flag = True

    _signal.signal(_signal.SIGTERM, _handle_signal)
    _signal.signal(_signal.SIGINT, _handle_signal)

    # 启动保活（Railway 防休眠）
    start_keepalive()

    # 启动 Web 管理后台
    admin_port = int(os.environ.get("ADMIN_PORT", "7860"))
    start_admin_thread(admin_port)

    # 加载插件
    await _load_plugins()

    active_bots = config.get_active_bots()
    logger.info(f"Active bots: {list(active_bots.keys())}")

    if config.WEBHOOK_URL:
        # ── Webhook 模式 ──
        apps = {}
        for role_id, token in active_bots.items():
            apps[role_id] = build_single_bot(role_id, token)

        port = int(os.environ.get("PORT", "8080"))
        server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
        WebhookHandler.apps = apps
        WebhookHandler.loop = asyncio.get_running_loop()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        logger.info(f"webhook server running on port {port}")

        base_url = config.WEBHOOK_URL.rstrip("/")
        for role_id, app in apps.items():
            role = ROLES[role_id]
            webhook_url = f"{base_url}/webhook/{role_id}"
            await app.initialize()
            await app.start()
            await app.bot.set_webhook(url=webhook_url)
            logger.info(f"{role['name']} webhook set: {webhook_url}")


            # 新角色频道公告
            await announce_new_role(app, role_id)

        logger.info(f"All {len(apps)} bots running via webhook")

        # ── DB Backup: every hour ──
        async def _webhook_backup():
            while not _shutdown_flag:
                db.backup_database()
                await asyncio.sleep(3600)
        asyncio.create_task(_webhook_backup())

        # ── Deep Dream: nightly ──
        async def _webhook_deep_dream():
            import datetime as _dt2
            while not _shutdown_flag:
                now2 = _dt2.datetime.now()
                target2 = now2.replace(hour=3, minute=0, second=0, microsecond=0)
                if target2 <= now2:
                    target2 += _dt2.timedelta(days=1)
                await asyncio.sleep((target2 - now2).total_seconds())
                for rid in apps:
                    users = db.get_active_users_for_role(rid)
                    for uid in users[:50]:
                        await summarize_user_conversation(uid, rid)
        asyncio.create_task(_webhook_deep_dream())
        while not _shutdown_flag:
            await asyncio.sleep(3600)
    else:
        # ── Polling 模式 ──
        threading.Thread(target=run_healthcheck, daemon=True).start()
        tasks = [run_bot_polling(rid, tok) for rid, tok in active_bots.items()]
        await asyncio.gather(*tasks)



    # Cleanup
    if hasattr(db, "conn"):
        try:
            db.conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
