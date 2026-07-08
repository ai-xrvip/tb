"""handlers_search.py — Search orchestration and progressive display."""
from bot_utils import (
    now_ts, store_url, get_url, clean_title, parse_count_from_title,
    is_vip, check_rate_limit, safe_search_wrapper,
    user_search_state, dedup_results, quality_score,
    EH_ENABLED, RESULTS_PER_PAGE,
)
from display import _show_results_page
from scraper import search_galleries, search_xchina
from scraper_eh import search_ehentai
from config import config
from database import db_bump_stat, db_add_search_history
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
    asyncio.create_task(db_add_search_history(user_id, keyword))
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
    asyncio.create_task(db_add_search_history(user_id, keyword))
    loading = await msg.reply_text("🔍 正在搜索中，请稍候...")
    await _run_search_and_display(msg, keyword, user_id, loading, query)

async def _run_search_and_display(msg, keyword, user_id, loading, query=None):
    hd_task = asyncio.create_task(safe_search_wrapper("4KHD", search_galleries(keyword, max_results=config.MAX_SEARCH_RESULTS)))
    xc_task = asyncio.create_task(safe_search_wrapper("XChina", search_xchina(keyword, max_results=config.MAX_SEARCH_RESULTS)))
    eh_task = asyncio.create_task(safe_search_wrapper("EH", search_ehentai(keyword, max_results=config.MAX_SEARCH_RESULTS))) if EH_ENABLED else None

    name_map = {hd_task: "4KHD", xc_task: "XChina"}
    if eh_task:
        name_map[eh_task] = "EH"

    all_results: list[dict] = []
    seen_urls: set[str] = set()
    displayed_once = False
    all_tasks = set(name_map.keys())

    # Progressive display: show first batch at 3s, update as more arrive
    for checkpoint in (3.0, 6.0, None):
        remaining = all_tasks - {t for t in all_tasks if t.done()}
        if not remaining:
            break
        if checkpoint is not None:
            done_set, _ = await asyncio.wait(remaining, timeout=checkpoint, return_when=asyncio.FIRST_COMPLETED)
        else:
            done_set, _ = await asyncio.wait(remaining, timeout=None)

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
            asyncio.create_task(db_bump_stat(datetime.now().strftime("%Y-%m-%d"), "searches"))

        # Show or update
        user_search_state[user_id] = {"page": 0, "keyword": keyword, "results": all_results, "ts": now_ts()}
        if not displayed_once:
            # First display — delete loading, show results
            try:
                await loading.delete()
            except Exception:
                pass
            await _show_results_page(query if query else msg, user_id)
            displayed_once = True
        else:
            # Update existing display
            await _show_results_page(query if query else msg, user_id, is_update=True)

    # If nothing at all
    if not all_results:
        try:
            await loading.delete()
        except Exception:
            pass
        from scraper import get_hot_keywords
        hot = await get_hot_keywords(top_n=5)
        suggest_btns = [[InlineKeyboardButton(kw, callback_data=f"hot_{html.escape(kw)}")] for kw in hot]
        suggest_btns.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
        await msg.reply_text(
            f"😔 没有找到「{html.escape(keyword)}」相关图集\n\n🔥 试试热门搜索：",
            reply_markup=InlineKeyboardMarkup(suggest_btns))

