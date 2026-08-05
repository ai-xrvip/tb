"""handlers_search.py — Search orchestration and progressive display."""
from bot_utils import (
    now_ts, store_url, get_url, clean_title, parse_count_from_title,
    is_vip, check_rate_limit, safe_search_wrapper,
    user_search_state, dedup_results, quality_score, _safe_callback,
    EH_ENABLED, RESULTS_PER_PAGE, VIP_CTA_TEXT, vip_cta_keyboard, spawn,
)
from display import _show_results_page
from scraper import search_galleries
from scraper_eh import search_ehentai
from config import config
from database import db_bump_stat, db_add_search_history, db_bump_search_quota
import asyncio, html, logging, traceback
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
logger = logging.getLogger(__name__)

# ========== Search ==========

async def _do_search(update, keyword):
    msg = update.message
    loading = await msg.reply_text("🔍 正在搜索中，请稍候...")
    user_id = update.effective_user.id
    # Record search history
    spawn(db_add_search_history(user_id, keyword))
    if not is_vip(user_id) and not await check_rate_limit(user_id):
        await loading.delete()
        await msg.reply_text("⏱ 搜索太频繁了，请稍后再试～",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]]))
        return
    await _run_search_and_display(msg, keyword, user_id, loading)

async def _do_search_callback(query, keyword):
    user_id = query.from_user.id
    msg = query.message
    spawn(db_add_search_history(user_id, keyword))
    loading = await msg.reply_text("🔍 正在搜索中，请稍候...")
    await _run_search_and_display(msg, keyword, user_id, loading, query)

async def _run_search_and_display(msg, keyword, user_id, loading, query=None):
    # Free tier: consume a daily search slot (VIP is unlimited)
    quota_left = None
    if not is_vip(user_id) and config.FREE_DAILY_SEARCHES > 0:
        today = datetime.now().strftime("%Y-%m-%d")
        used = await db_bump_search_quota(user_id, today)
        if used > config.FREE_DAILY_SEARCHES:
            try:
                await loading.delete()
            except Exception:
                pass
            await msg.reply_text(VIP_CTA_TEXT, parse_mode="HTML", reply_markup=vip_cta_keyboard())
            return
        quota_left = config.FREE_DAILY_SEARCHES - used

    hd_task = asyncio.create_task(safe_search_wrapper("4KHD", search_galleries(keyword, max_results=config.MAX_SEARCH_RESULTS)))
    eh_task = asyncio.create_task(safe_search_wrapper("EH", search_ehentai(keyword, max_results=config.MAX_SEARCH_RESULTS))) if EH_ENABLED else None

    name_map = {hd_task: "4KHD"}
    if eh_task:
        name_map[eh_task] = "EH"

    all_results: list[dict] = []
    seen_urls: set[str] = set()
    displayed_once = False
    all_tasks = set(name_map.keys())

    # Progressive display: collect already-done tasks first, then wait for more
    collected = set()
    for checkpoint in (3.0, 6.0, None):
        # First, grab any tasks that completed since last checkpoint
        just_done = {t for t in all_tasks if t.done()} - collected
        if just_done:
            done_set = just_done
        elif checkpoint is not None:
            remaining = all_tasks - collected
            if not remaining:
                break
            done_set, _ = await asyncio.wait(remaining, timeout=checkpoint, return_when=asyncio.FIRST_COMPLETED)
        else:
            remaining = all_tasks - collected
            if not remaining:
                break
            done_set, _ = await asyncio.wait(remaining, timeout=None)
        collected |= done_set

        # Collect results from newly done tasks
        for t in done_set:
            try:
                results = t.result()
            except Exception:
                results = []
            source = name_map.get(t, "?")
            new_count = 0
            for r in results:
                if r.get("url", "") not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)
                    new_count += 1
            if new_count > 0:
                logger.info(f"Progressive search: +{new_count} from {source}")

        if not all_results:
            continue  # no results yet, wait for next checkpoint

        # Sort and dedup — use quality ranking (clicks 40% + image count 30% + date 30%)
        all_results.sort(key=lambda r: quality_score(r), reverse=True)
        all_results = dedup_results(all_results)

        # Track search stat (once)
        if not displayed_once:
            spawn(db_bump_stat(datetime.now().strftime("%Y-%m-%d"), "searches"))

        # Show or update
        prev_state = user_search_state.get(user_id, {})
        results_msg_id = prev_state.get("results_msg_id")
        user_search_state[user_id] = {"page": 0, "keyword": keyword, "results": all_results, "ts": now_ts(), "quota_left": quota_left, "album_ids": prev_state.get("album_ids")}
        if not displayed_once:
            # First display — delete loading, show results
            try:
                await loading.delete()
            except Exception:
                pass
            sent = await _show_results_page(query if query else msg, user_id)
            if sent and hasattr(sent, "message_id"):
                user_search_state[user_id]["results_msg_id"] = sent.message_id
            displayed_once = True
        else:
            # Update existing display — edit tracked results message
            user_search_state[user_id]["results_msg_id"] = results_msg_id
            await _show_results_page(query if query else msg, user_id, is_update=True, progressive=True)

    # If nothing at all
    if not all_results:
        try:
            await loading.delete()
        except Exception:
            pass
        from scraper import get_hot_keywords
        hot = await get_hot_keywords(top_n=5)
        suggest_btns = [[InlineKeyboardButton(kw, callback_data=_safe_callback("hot_", kw))] for kw in hot]
        suggest_btns.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
        await msg.reply_text(
            f"😔 没有找到「{html.escape(keyword)}」相关图集\n\n🔥 试试热门搜索：",
            reply_markup=InlineKeyboardMarkup(suggest_btns))

