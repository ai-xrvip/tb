"""handlers_menu.py — Menu handlers and inline query handler."""
from bot_utils import (
    now_ts, store_url, get_url, clean_title, parse_count_from_title,
    is_vip, user_waiting_search, user_waiting_card, send_or_edit, safe_search_wrapper, PURCHASE_URL,
    START_TEXT, START_KEYBOARD, VIP_TEXT,
    build_hot_keyword_keyboard,
)
from display import _show_results_page, _send_xchina_detail, _send_eh_detail, _send_gallery_detail
from config import config
from scraper import search_galleries, search_xchina, get_random_gallery
from scraper_eh import search_ehentai
import asyncio, html, logging, traceback
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import InlineQueryResultArticle, InputTextMessageContent
logger = logging.getLogger(__name__)

# ========== Menu Handlers ==========

async def _handle_menu_search(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.add(user_id)
    keyboard = await build_hot_keyword_keyboard([
        [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")],
    ], user_id=user_id)
    await query.edit_message_text(
        "🔍 请直接输入搜索关键词～\n\n🔥 <b>热门搜索：</b>",
        parse_mode="HTML",
        reply_markup=keyboard)

async def _route_random_gallery(update, gallery):
    url = gallery.get("url", "")
    source = gallery.get("source", "")
    pd = gallery.get("publish_date", "")
    if source == "ehentai" or "e-hentai.org" in url:
        await _send_eh_detail(update, url, publish_date=pd, from_random=True)
    elif source == "xchina" or "xchina.co" in url or "/photo/id-" in url:
        await _send_xchina_detail(update, url, author=gallery.get("author", ""), publish_date=pd, from_random=True)
    else:
        await _send_gallery_detail(update, url, from_random=True)

async def _handle_random_next(update, context):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    msg = await update.effective_message.reply_text("🎲 正在为你随机推荐...")
    try:
        gallery = await get_random_gallery()
    except Exception:
        await send_or_edit(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    if not gallery:
        await send_or_edit(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    await msg.delete()
    await _route_random_gallery(update, gallery)

async def _handle_menu_random(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    await query.edit_message_text("🎲 正在为你随机推荐...")
    try:
        gallery = await get_random_gallery()
    except Exception:
        await query.edit_message_text("😔 获取随机推荐失败，请稍后再试。")
        return
    if not gallery:
        await query.edit_message_text("😔 获取随机推荐失败，请稍后再试。")
        return
    await _route_random_gallery(update, gallery)

async def _handle_menu_vip(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    if is_vip(user_id):
        await query.edit_message_text(
            "<b>👑 你已是VIP会员</b>\n\n🎉 享受所有特权～",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]]))
        return
    await query.edit_message_text(VIP_TEXT, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
            [InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)],
            [InlineKeyboardButton("🔗 邀请好友得VIP", callback_data="invite_info")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
        ]))

async def _handle_menu_home(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    user_waiting_card.discard(user_id)
    try:
        await query.edit_message_text(START_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")
    except Exception:
        logger.debug("_handle_menu_home: edit failed, trying delete")
        try: await query.delete_message()
        except Exception:
            logger.debug("_handle_menu_home: delete also failed")
        await query.message.reply_text(START_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")

# ========== Inline Query Handler ==========

async def handle_inline(update, context):
    """Handle inline queries — search from any chat using @botname keyword."""
    query = update.inline_query
    keyword = query.query.strip()
    if not keyword or len(keyword) < 2:
        await query.answer([], switch_pm_text="输入关键词搜索图集", switch_pm_parameter="start")
        return

    results = []
    # Quick search: 4KHD + XC only (skip EH for inline — too slow)
    try:
        hd_task = asyncio.create_task(safe_search_wrapper("4KHD", search_galleries(keyword, max_results=5)))
        xc_task = asyncio.create_task(safe_search_wrapper("XChina", search_xchina(keyword, max_results=5)))
        done_set, _ = await asyncio.wait([hd_task, xc_task], timeout=4.0)
        all_found = []
        for t in done_set:
            try:
                all_found.extend(t.result())
            except Exception:
                pass
        all_found = all_found[:10]

        for i, r in enumerate(all_found):
            title = r.get("title", "Unknown")[:60]
            url = r.get("url", "")
            source = r.get("source", "")
            source_label = "🌸" if source == "xchina" else ("📖" if source == "ehentai" else "🎀")
            description = f"{source_label} {r.get('publish_date', '')}"

            results.append(
                InlineQueryResultArticle(
                    id=str(i),
                    title=title,
                    description=description,
                    thumb_url=r.get("cover") or "",
                    input_message_content=InputTextMessageContent(
                        f"/search {keyword}"
                    ),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔍 在Bot中打开", url=f"https://t.me/{context.bot.username}?start=search_{keyword}")
                    ]]),
                )
            )
    except Exception as e:
        logger.warning(f"Inline query error: {e}")

    await query.answer(results, cache_time=30, is_personal=True)

