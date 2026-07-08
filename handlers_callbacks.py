"""handlers_callbacks.py — Main callback query handler (route-table pattern)."""
from bot_utils import (
    now_ts, store_url, get_url, clean_title, parse_count_from_title,
    is_vip, send_or_edit, ADMIN_IDS, VIP_USERS, ALL_USERS, INVITES,
    user_search_state, user_waiting_card, user_waiting_search, url_store,
    admin_setvip_state, START_TEXT, START_KEYBOARD, VIP_TEXT,
    PURCHASE_URL, _ONE_DAY,
    save_vip_db, save_invite_db, build_hot_keyword_keyboard,
)
from display import _show_results_page, _send_xchina_detail, _send_eh_detail
from display import _send_gallery_detail, _send_gallery_full, _send_gallery_page
from handlers_search import _do_search_callback
from handlers_menu import (
    _handle_menu_search, _handle_menu_random, _handle_menu_vip,
    _handle_menu_home, _handle_random_next,
)
from config import config
from database import (
    db_load_cards, db_save_card, db_activate_card,
    db_card_count_used, db_card_count_total,
    db_list_unused_cards, db_save_invite, db_add_favorite, db_get_favorites,
)
from scraper_eh import get_eh_magnet
import asyncio, html, logging, re, secrets, string, traceback
from datetime import datetime
from typing import Callable, Awaitable
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

HandlerFn = Callable[..., Awaitable[None]]

# ── Exact-match routes ──────────────────────────────────────────
_exact_routes: dict[str, HandlerFn] = {}

def _exact(prefix: str):
    """Decorator: register an exact-match callback handler."""
    def decorator(fn: HandlerFn) -> HandlerFn:
        _exact_routes[prefix] = fn
        return fn
    return decorator

# ── Prefix-match routes ─────────────────────────────────────────
_prefix_routes: list[tuple[str, HandlerFn]] = []

def _prefix(prefix: str):
    """Decorator: register a prefix-match callback handler.
    Routes are checked in registration order; first match wins."""
    def decorator(fn: HandlerFn) -> HandlerFn:
        _prefix_routes.append((prefix, fn))
        return fn
    return decorator

# ── Dispatcher ──────────────────────────────────────────────────

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    logger.info(f"Callback: user={user_id} data={data[:80]}")

    try:
        # Exact match first
        handler = _exact_routes.get(data)
        if handler:
            await handler(update, context)
            return
        # Then prefix match (in registration order)
        for prefix, handler in _prefix_routes:
            if data.startswith(prefix):
                await handler(update, context)
                return
        # No route matched
        logger.warning(f"Unhandled callback data: {data}")
    except Exception as e:
        logger.error(f"Callback error: {traceback.format_exc()}")
        try:
            await query.edit_message_text("操作失败，请重试。")
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════
#  Exact-match routes
# ═══════════════════════════════════════════════════════════════

@_exact("menu_search")
async def _route_menu_search(update, context):
    await _handle_menu_search(update, context)

@_exact("menu_random")
async def _route_menu_random(update, context):
    await _handle_menu_random(update, context)

@_exact("random_next")
async def _route_random_next(update, context):
    await _handle_random_next(update, context)

@_exact("menu_vip")
async def _route_menu_vip(update, context):
    await _handle_menu_vip(update, context)

@_exact("menu_help")
async def _route_menu_help(update, context):
    query = update.callback_query
    await query.edit_message_text(
        "<b>📖 使用帮助</b>\n\n"
        "🔍 <b>搜索图集</b> — 点击后直接输入关键词\n"
        "🎲 <b>随机推荐</b> — 每日新鲜图集随机推荐\n"
        "👑 <b>VIP会员</b> — 解锁无限搜索、完整图集浏览\n"
        "👤 <b>我的VIP</b> — 查看会员状态、续费\n"
        "🔗 <b>邀请好友</b> — 生成邀请码，好友加入双方各得VIP\n\n"
        "<b>快捷命令：</b>\n"
        "/search 关键词 — 快速搜索\n"
        "/random — 随机推荐\n"
        "/my — 查看VIP\n"
        "/start — 返回主菜单",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
        ]]))

@_exact("menu_home")
async def _route_menu_home(update, context):
    await _handle_menu_home(update, context)

@_exact("noop")
async def _route_noop(update, context):
    return

@_exact("invite_gen")
async def _route_invite_gen(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    code = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    INVITES[code] = str(user_id)
    await save_invite_db(code, user_id)
    await query.edit_message_text(
        f"🔗 <b>你的专属邀请码</b>\n\n<code>{code}</code>\n\n"
        f"好友通过 @{context.bot.username}?start={code} 加入后，你获得 <b>1天VIP</b>！\n\n"
        f"直接分享：\nhttps://t.me/{context.bot.username}?start={code}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
        ]]))

@_exact("invite_info")
async def _route_invite_info(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    await query.edit_message_text(
        "🔗 <b>邀请好友得VIP</b>\n\n"
        "每成功邀请一位新用户加入，你获得 <b>1天VIP</b>！\n\n"
        "方法：\n1. 生成邀请码\n2. 分享给好友\n3. 好友点击链接开始使用\n\n"
        "👑 VIP用户才能生成邀请码哦～",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 生成邀请码" if is_vip(user_id) else "👑 开通VIP",
                callback_data="invite_gen" if is_vip(user_id) else "menu_vip")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
        ]))

@_exact("vip_activate")
async def _route_vip_activate(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    user_waiting_card.add(user_id)
    await query.edit_message_text(
        "🔑 请输入你的卡密：\n\n格式：直接输入卡密即可",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
        ]]))

@_exact("vip_upgrade")
async def _route_vip_upgrade(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    if is_vip(user_id):
        await query.edit_message_text("<b>👑 你已是VIP会员</b>\n\n🎉 享受所有特权～", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")
            ]]))
    else:
        await query.edit_message_text(VIP_TEXT, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
                [InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")]
            ]))


# ═══════════════════════════════════════════════════════════════
#  Admin routes
# ═══════════════════════════════════════════════════════════════

@_exact("admin_gencode")
async def _route_admin_gencode(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("❌ 无权限", show_alert=True)
        return
    generated = []
    types = [
        ("📅 月卡(Y)", "month", 30),
        ("📅 季卡(J)", "quarter", 90),
        ("📅 年卡(N)", "year", 360),
        ("📅 永久(S)", "forever", 0),
    ]
    prefix_map = {"month": "Y", "quarter": "J", "year": "N", "forever": "S"}
    for label, tname, days_val in types:
        prefix = prefix_map[tname]
        for _ in range(10):
            code = prefix + "-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            asyncio.create_task(db_save_card(code, tname, days_val if days_val > 0 else None, user_id))
            generated.append(code)
    gen_lines = ["🔫 <b>已生成 40 张卡密</b>", ""]
    for label, tname, days_val in types:
        prefix = prefix_map[tname]
        type_codes = [c for c in generated if c.startswith(prefix)]
        gen_lines.append(f"{label}: {len(type_codes)}张")
    gen_lines.append("")
    gen_lines.append("点击下方导出全部卡密TXT")
    gen_text = "\n".join(gen_lines)
    await query.edit_message_text(gen_text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 导出卡密TXT", callback_data="admin_exportcards")],
            [InlineKeyboardButton("⬅️ 返回管理员面板", callback_data="admin_back")]
        ]))

@_exact("admin_exportcards")
async def _route_admin_exportcards(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("❌ 无权限", show_alert=True)
        return
    unused = await db_list_unused_cards()
    type_names = {"month": "月卡", "quarter": "季卡", "year": "年卡", "forever": "永久", "trial": "体验卡"}
    lines = [f"{r['code']}  [{type_names.get(r['card_type'], r['card_type'])}]" for r in unused]
    if lines:
        txt_content = "\n".join(lines)
        if len(txt_content) > 4000:
            txt_content = txt_content[:4000] + "\n... 已截断"
        await query.message.reply_text(
            f"<b>📥 未使用卡密 ({len(lines)}张)</b>\n\n<code>{html.escape(txt_content)}</code>",
            parse_mode="HTML")
    else:
        await query.answer("没有未使用的卡密", show_alert=True)

@_exact("admin_back")
async def _route_admin_back(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    total_vip = len(VIP_USERS)
    permanent = sum(1 for v in VIP_USERS.values() if v is None)
    timed = total_vip - permanent
    total_cards = await db_card_count_total()
    used_cards = await db_card_count_used()
    from scraper import gallery_clicks, keyword_popularity
    regular_users = [uid for uid in ALL_USERS if uid not in VIP_USERS]
    vip_users_list = [uid for uid in VIP_USERS if uid not in ADMIN_IDS]
    now = now_ts()
    stats_text = (
        "📊 <b>管理员面板</b>\n\n"
        f"👥 总用户: {len(ALL_USERS)}\n"
        f"   普通用户: {len(regular_users)}\n"
        f"   VIP用户: {total_vip} ({permanent}永久 + {timed}限时)\n\n"
        f"🔑 卡密: 已用{used_cards}/总计{total_cards}\n"
        f"🔍 搜索热词: {len(keyword_popularity)}\n"
        f"📈 点击记录: {len(gallery_clicks)}\n"
        f"🔗 邀请码: {len(INVITES)}\n\n"
        f"📅 VIP到期(7天内): {sum(1 for v in VIP_USERS.values() if v is not None and 0 < v - now < 7*86400)}"
    )
    await query.edit_message_text(stats_text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 设置VIP用户", callback_data="admin_setvip_prompt")],
            [InlineKeyboardButton("🔫 生成卡密", callback_data="admin_gencode")],
            [InlineKeyboardButton("📥 导出卡密TXT", callback_data="admin_exportcards")],
            [InlineKeyboardButton("🔍 查看全部用户", callback_data="admin_listusers")],
        ]))

@_exact("admin_setvip_prompt")
async def _route_admin_setvip_prompt(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("❌ 无权限", show_alert=True)
        return
    admin_setvip_state[user_id] = True
    await query.edit_message_text(
        "✅ 请输入要设置为VIP的用户ID：\n\n格式: <用户ID> [天数]\n例如: 123456789 30\n不写天数则为永久",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ 取消", callback_data="admin_back")
        ]]))

@_exact("admin_listusers")
async def _route_admin_listusers(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    vip_data = [(uid, VIP_USERS[uid]) for uid in VIP_USERS if uid not in ADMIN_IDS]
    regular = [uid for uid in ALL_USERS if uid not in VIP_USERS]
    text = "📋 <b>全部用户列表</b>\n\n"
    text += f"👑 <b>VIP用户 ({len(vip_data)}):</b>\n"
    if vip_data:
        for uid, exp in vip_data:
            if exp is None:
                exp_str = "永久"
            else:
                rem = max(0, int((exp - now_ts()) / 86400))
                exp_str = f"剩{rem}天"
            text += f"  • <code>{uid}</code> - {exp_str}\n"
    else:
        text += "  暂无\n"
    text += f"\n👥 <b>普通用户 ({len(regular)}):</b>\n"
    if regular:
        for uid in regular:
            text += f"  • <code>{uid}</code>\n"
    else:
        text += "  暂无\n"
    if len(text) > 4000:
        text = text[:4000] + "\n\n... 列表过长已截断"
    await query.edit_message_text(text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ 返回管理员面板", callback_data="admin_back")
        ]]))

# ═══════════════════════════════════════════════════════════════
#  Prefix-match routes (checked in registration order)
# ═══════════════════════════════════════════════════════════════

@_prefix("hot_")
async def _route_hot(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    kw = query.data[4:]
    user_waiting_search.discard(user_id)
    await _do_search_callback(query, kw)

@_prefix("p_")
async def _route_page(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    page = int(query.data.split("_")[1])
    state = user_search_state.get(user_id)
    if not state:
        await query.edit_message_text("⏳ 会话已过期，请重新搜索。")
        return
    state["page"] = page
    await _show_results_page(query, user_id)

@_prefix("d_")
async def _route_detail_4khd(update, context):
    query = update.callback_query
    url = get_url(query.data[2:])
    if not url:
        await query.edit_message_text("⏳ 链接已过期，请重新搜索。")
        return
    loading = await query.message.reply_text("⏳ 正在获取图集详情，请稍候...")
    await _send_gallery_detail(update, url)
    try: await loading.delete()
    except Exception: pass

@_prefix("x_")
async def _route_detail_xchina(update, context):
    query = update.callback_query
    url = get_url(query.data[2:])
    if not url:
        await query.edit_message_text("❌ 链接已过期，请重新搜索。")
        return
    loading = await query.message.reply_text("⏳ 正在获取图集详情...")
    entry = url_store.get(query.data[2:], {})
    await _send_xchina_detail(update, url, author=entry.get("author", ""), publish_date=entry.get("publish_date", ""))
    try: await loading.delete()
    except Exception: pass

@_prefix("e_")
async def _route_detail_eh(update, context):
    query = update.callback_query
    url = get_url(query.data[2:])
    if not url:
        await query.edit_message_text("❌ 链接已过期")
        return
    loading = await query.message.reply_text("⏳ 正在获取图集详情，请稍候...")
    await _send_eh_detail(update, url)
    try: await loading.delete()
    except Exception: pass

@_prefix("m_")
async def _route_magnet(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    url = get_url(query.data[2:])
    if not url:
        await query.answer("❌ 链接已过期", show_alert=True)
        return
    if not is_vip(user_id):
        await query.answer("👑 请先开通VIP会员", show_alert=True)
        return
    await query.answer()
    status_msg = await query.message.reply_text("🧲 正在后台获取磁力链，稍后通知你...")
    async def _bg_magnet():
        magnet = await get_eh_magnet(url)
        try:
            if magnet:
                await status_msg.edit_text(f"🧲 <b>磁力链接</b>\n\n<code>{magnet}</code>", parse_mode="HTML")
            else:
                await status_msg.edit_text("❌ 该图集暂无磁力链接")
        except Exception:
            pass
    asyncio.create_task(_bg_magnet())

# Favorites (prefix "fav_")

@_prefix("fav_add_")
async def _route_fav_add(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    entry = url_store.get(query.data[8:])
    if entry:
        target_url = entry.get("url", "")
        added = await db_add_favorite(user_id, entry.get("title", "Unknown"), target_url, entry.get("source", ""))
        if added:
            await query.answer("\u2b50 \u5df2\u6536\u85cf", show_alert=True)
        else:
            await query.answer("\u2b50 \u5df2\u6536\u85cf\u8fc7", show_alert=True)

@_exact("fav_list")
async def _route_fav_list(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    favs = await db_get_favorites(user_id)
    if not favs:
        await query.edit_message_text("\u2b50 <b>\u6536\u85cf\u5939</b>\n\n\u8fd8\u6ca1\u6709\u6536\u85cf\u4efb\u4f55\u56fe\u96c6\u54e6\uff5e",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("\U0001f3e0 \u8fd4\u56de\u4e3b\u83dc\u5355", callback_data="menu_home")
            ]]))
    else:
        fav_text = "\u2b50 <b>\u6536\u85cf\u5939</b>\n\n"
        fav_buttons = []
        for i, f in enumerate(favs):
            fav_text += f"{i+1}. {html.escape(f['title'][:40])}\n"
            fav_buttons.append([InlineKeyboardButton(f"{i+1}. {f['title'][:35]}", url=f['url'], callback_data="noop")])
        fav_buttons.append([InlineKeyboardButton("\U0001f3e0 \u8fd4\u56de\u4e3b\u83dc\u5355", callback_data="menu_home")])
        await query.edit_message_text(fav_text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(fav_buttons))
@_prefix("f_")
async def _route_full_gallery(update, context):
    query = update.callback_query
    url = get_url(query.data[2:])
    if not url:
        await query.message.reply_text("⏳ 链接已过期，请重新搜索。")
        return
    loading = await query.message.reply_text("⏳ 正在加载图片，请稍候...")
    await _send_gallery_full(update, url)
    try: await loading.delete()
    except Exception: pass

@_prefix("g_")
async def _route_gallery_page(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    payload = query.data[2:]
    underscore_pos = payload.rfind("_")
    if underscore_pos == -1:
        url_key = payload
        page = 0
    else:
        url_key = payload[:underscore_pos]
        try:
            page = int(payload[underscore_pos + 1:])
        except ValueError:
            page = 0
    url = get_url(url_key)
    if not url:
        await query.message.reply_text("\u23f3 \u94fe\u63a5\u5df2\u8fc7\u671f\u3002")
        return
    if not is_vip(user_id):
        await query.answer("\U0001f451 \u8bf7\u5148\u5f00\u901aVIP\u4f1a\u5458", show_alert=True)
        return
    loading = await query.message.reply_text(f"\u23f3 \u6b63\u5728\u52a0\u8f7d\u7b2c{page+1}\u9875\uff0c\u8bf7\u7a0d\u5019...")
    await _send_gallery_page(update, url, page)
    try: await loading.delete()
    except Exception: pass

