"""handlers_subs.py — Subscriptions, error handler, VIP push, DB backup."""
from bot_utils import (
    now_ts, store_url, get_url, safe_search_wrapper, parse_date_for_sort,
    is_vip, cleanup_all, VIP_USERS, ALL_USERS, EH_ENABLED, PURCHASE_URL,
    _ONE_DAY, ADMIN_IDS,
)
from config import config
from database import (
    db_subscribe, db_unsubscribe, db_get_subscriptions, db_get_all_subscriptions,
    db_was_pushed, db_mark_pushed, db_prune_pushed, db_add_search_history,
)
from scraper import search_galleries, search_xchina
from scraper_eh import search_ehentai
import asyncio, gc, html, logging, os, traceback
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
logger = logging.getLogger(__name__)

# ========== Keyword Subscription ==========

async def cmd_subscribe(update, context):
    """Subscribe to keyword updates: /subscribe keyword [source]"""
    user_id = update.effective_user.id
    if not is_vip(user_id):
        await update.message.reply_text("👑 订阅功能仅限VIP用户使用", parse_mode="HTML")
        return
    if not context.args:
        subs = await db_get_subscriptions(user_id)
        if not subs:
            await update.message.reply_text("📭 <b>订阅管理</b>\n\n你还没有订阅关键词。\n用法: /subscribe 关键词 [平台]\n平台: 4khd | xchina | ehentai | all",
                parse_mode="HTML")
        else:
            text = "📋 <b>我的订阅</b>\n\n"
            for s in subs:
                source_label = s["source"] or "全部"
                text += f"• <code>{s['keyword']}</code> [{source_label}]\n"
            text += "\n取消: /unsubscribe 关键词 [平台]"
            await update.message.reply_text(text, parse_mode="HTML")
        return
    keyword = context.args[0].lower()
    source = context.args[1].lower() if len(context.args) > 1 else ""
    if source not in ("", "all", "4khd", "xchina", "ehentai"):
        source = ""
    added = await db_subscribe(user_id, keyword, source)
    if added:
        source_label = source or "全部"
        await update.message.reply_text(f"✅ 已订阅: {keyword} [{source_label}]\n有新图集会推送给你～", parse_mode="HTML")
    else:
        await update.message.reply_text("该关键词已订阅过。")

async def cmd_unsubscribe(update, context):
    """Unsubscribe: /unsubscribe keyword [source]"""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("用法: /unsubscribe 关键词 [平台]")
        return
    keyword = context.args[0].lower()
    source = context.args[1].lower() if len(context.args) > 1 else ""
    if source not in ("", "all", "4khd", "xchina", "ehentai"):
        source = ""
    await db_unsubscribe(user_id, keyword, source)
    await update.message.reply_text(f"✅ 已取消订阅: {keyword}")

async def _subscription_push_loop(application):
    """Background task: check subscriptions every hour and push new galleries."""
    await asyncio.sleep(120)  # wait 2 min after startup
    while True:
        try:
            subs = await db_get_all_subscriptions()
            if not subs:
                await asyncio.sleep(3600)
                continue

            # Group by keyword to avoid duplicate searches
            seen_kws: dict[str, set[int]] = {}
            for s in subs:
                key = (s["keyword"], s["source"] or "")
                if key not in seen_kws:
                    seen_kws[key] = set()
                seen_kws[key].add(s["user_id"])

            for (keyword, source), user_ids in seen_kws.items():
                try:
                    # Search the relevant source(s)
                    candidates = []
                    if not source or source == "4khd":
                        hd = await safe_search_wrapper("4KHD", search_galleries(keyword, max_results=5))
                        candidates.extend(hd)
                    if not source or source == "xchina":
                        xc = await safe_search_wrapper("XChina", search_xchina(keyword, max_results=5))
                        candidates.extend(xc)
                    if (not source or source == "ehentai") and EH_ENABLED:
                        eh = await safe_search_wrapper("EH", search_ehentai(keyword, max_results=5))
                        candidates.extend(eh)

                    if not candidates:
                        continue

                    # Get the freshest 1-2 results
                    candidates.sort(key=lambda r: parse_date_for_sort(r.get("publish_date", "")), reverse=True)
                    fresh = candidates[:2]

                    for uid in user_ids:
                        for r in fresh:
                            url = r.get("url", "")
                            if not url:
                                continue
                            if await db_was_pushed(uid, url):
                                continue
                            try:
                                await application.bot.send_message(
                                    chat_id=uid,
                                    text=f"🔔 <b>订阅更新</b>\n\n关键词: <code>{keyword}</code>\n{html.escape(r['title'][:100])}\n\n点击查看 ↓",
                                    parse_mode="HTML",
                                    reply_markup=InlineKeyboardMarkup([[
                                        InlineKeyboardButton("👀 查看详情", callback_data=
                                            "d_" + ("x_" if r.get("source") == "xchina" else
                                            "e_" if r.get("source") == "ehentai" else "d_") +
                                            await store_url(url, source=r.get("source", ""))
                                        )
                                    ]])
                                )
                                await db_mark_pushed(uid, url)
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Subscription push error for {keyword}: {e}")
                    await asyncio.sleep(1)

            # Prune old pushed entries daily
            await asyncio.sleep(1)
            if datetime.now().hour == 3:
                await db_prune_pushed(30)
        except Exception as e:
            logger.error(f"Subscription loop error: {e}")
        await asyncio.sleep(3600)  # check every hour

# ========== VIP Daily Push ==========

async def _vip_daily_push(application):
    """Daily push of latest galleries to VIP users."""
    await asyncio.sleep(3600)  # wait 1h after startup
    while True:
        try:
            now = datetime.now()
            # Push at 10:00 and 20:00
            next_hour = 10 if now.hour < 10 else (20 if now.hour < 20 else 10)
            wait_secs = ((next_hour - now.hour) % 24) * 3600 - now.minute * 60 - now.second
            if wait_secs < 0:
                wait_secs += 86400
            await asyncio.sleep(wait_secs)

            # Get recent galleries
            from scraper import search_xchina, get_hot_keywords
            candidates = []
            kws = await get_hot_keywords(top_n=3)
            for kw in kws:
                try:
                    xc = await search_xchina(kw, max_results=3, max_pages=1)
                    candidates.extend(xc)
                except Exception: pass
            if not candidates:
                continue

            import random as _rand
            picks = _rand.sample(candidates, min(3, len(candidates)))

            for uid in list(VIP_USERS.keys()):
                try:
                    pick = _rand.choice(picks)
                    await application.bot.send_message(
                        chat_id=uid,
                        text=f'\U0001f4ec <b>VIP\u6bcf\u65e5\u7cbe\u9009</b>\n\n{pick["title"]}\n\n\u70b9\u51fb\u67e5\u770b\u8be6\u60c5 \u2192',
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("\U0001f440 \u67e5\u770b\u8be6\u60c5", callback_data=f"x_{await store_url(pick['url'], source='xchina')}")
                        ]])
                    )
                except Exception:
                    pass
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"VIP push error: {e}")
        await asyncio.sleep(3600)



# ========== Error Handler ==========

async def error_handler(update, context):
    logger.error("Global error: " + str(context.error), exc_info=True)
    if update and isinstance(update, type(update)) and getattr(update, 'effective_message', None):
        try:
            await update.effective_message.reply_text("\u274c \u51fa\u9519\u4e86\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002")
        except Exception: pass

# ========== Database Backup ==========

async def _db_backup_loop():
    import os as _os
    backup_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "backups")
    _os.makedirs(backup_dir, exist_ok=True)
    await asyncio.sleep(600)
    while True:
        now = datetime.now()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= target:
            import time as _t
            target = target + _t.timedelta(days=1)
        wait_secs = (target - now).total_seconds()
        await asyncio.sleep(wait_secs)
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            backup_path = _os.path.join(backup_dir, f"bot-{date_str}.db")
            if not _os.path.exists(backup_path):
                import sqlite3
                from config import config
                src = sqlite3.connect(config.DB_PATH)
                dst = sqlite3.connect(backup_path)
                src.backup(dst)
                src.close()
                dst.close()
                logger.info(f"DB backup created: {backup_path}")
            existing = sorted(_os.listdir(backup_dir))
            to_remove = [f for f in existing[:-7] if f.endswith(".db")]
            for f in to_remove:
                _os.remove(_os.path.join(backup_dir, f))
            if to_remove:
                logger.info(f"Pruned {len(to_remove)} old backups, keeping 7")
        except Exception as e:
            logger.error(f"DB backup failed: {e}")
        await asyncio.sleep(300)
