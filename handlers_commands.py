"""handlers_commands.py — Command handlers (start, search, admin, vip, etc.)."""
from bot_utils import (
    now_ts, store_url, get_url, clean_title, parse_count_from_title,
    is_vip, send_or_edit, user_waiting_search, user_waiting_card,
    ALL_USERS, VIP_USERS,
    INVITES, ADMIN_IDS, START_TEXT, START_KEYBOARD, VIP_TEXT,
    PURCHASE_URL, _ONE_DAY, MENU_KEYBOARD,
    save_vip_db, save_invite_db, load_vip_db, build_hot_keyword_keyboard,
    get_invite_lock,
)
from handlers_search import _do_search, _do_search_callback
from handlers_menu import _route_random_gallery
from config import config
from database import (
    db_add_user, db_bump_stat, db_save_vip, db_card_count_used, db_card_count_total,
    db_vip_count, db_vip_permanent_count, db_user_count,
    db_get_stats_last_days, db_get_user_history,
    db_delete_expired_vip,
    db_load_cards, db_activate_card,
)
import asyncio, html, logging, re, secrets, string, traceback
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
logger = logging.getLogger(__name__)

# ========== Commands ==========

async def cmd_start(update, context):
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    user_waiting_card.discard(user_id)
    if user_id not in ALL_USERS:
        ALL_USERS.add(user_id)
        asyncio.create_task(db_add_user(user_id))
        asyncio.create_task(db_bump_stat(datetime.now().strftime("%Y-%m-%d"), "new_users"))
        # Check invite: if started with /start INVITE_CODE, grant reward
        if context.args:
            code = context.args[0]
            async with get_invite_lock():
                inviter = INVITES.get(code)
                if inviter and int(inviter) != user_id:
                    # Grant 1 day VIP to inviter
                    existing = VIP_USERS.get(int(inviter))
                    if existing is not None:
                        VIP_USERS[int(inviter)] = max(existing or now_ts(), now_ts()) + _ONE_DAY
                    else:
                        if is_vip(int(inviter)):
                            VIP_USERS[int(inviter)] = max(VIP_USERS.get(int(inviter), now_ts()), now_ts()) + _ONE_DAY
                        else:
                            VIP_USERS[int(inviter)] = now_ts() + _ONE_DAY
                    asyncio.create_task(db_save_vip(int(inviter), VIP_USERS[int(inviter)]))
                    try:
                        await context.bot.send_message(
                            chat_id=int(inviter),
                            text=f"🎉 恭喜！你邀请的用户已加入～\nVIP 已延长 1 天！"
                        )
                    except Exception:
                        pass
    await update.message.reply_text(START_TEXT, reply_markup=START_KEYBOARD, parse_mode="HTML")
    await update.message.reply_text("💕 使用下方快捷按钮操作～", reply_markup=MENU_KEYBOARD)

async def cmd_setvip(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("用法: /setvip <用户ID> [天数]\n例如: /setvip 123456 30")
        return
    try:
        target = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else 0
        if days > 0:
            VIP_USERS[target] = now_ts() + days * 86400
            await update.message.reply_text(f"✅ 已将用户 {target} 设为VIP（{days}天）")
        else:
            VIP_USERS[target] = None
            await update.message.reply_text(f"✅ 已将用户 {target} 设为永久VIP")
        await save_vip_db(target, VIP_USERS[target])
        logger.info(f"VIP added: {target}")
    except ValueError:
        await update.message.reply_text("用户ID必须是数字")

async def cmd_admin(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    args = context.args
    if args and args[0] == "setvip" and len(args) > 1:
        try:
            target = int(args[1])
            days = int(args[2]) if len(args) > 2 else 0
            if days > 0:
                VIP_USERS[target] = now_ts() + days * 86400
                await update.message.reply_text(f"✅ 已将用户 {target} 设为VIP（{days}天）")
            else:
                VIP_USERS[target] = None
                await update.message.reply_text(f"✅ 已将用户 {target} 设为永久VIP")
            await save_vip_db(target, VIP_USERS[target])
        except ValueError:
            await update.message.reply_text("用户ID必须是数字")
        return

    VIP_USERS.clear()
    VIP_USERS.update(await load_vip_db())
    now = now_ts()
    expired = [uid for uid, exp in list(VIP_USERS.items()) if exp is not None and now > exp]
    for uid in expired:
        del VIP_USERS[uid]
    if expired:
        asyncio.create_task(db_delete_expired_vip())
    total_vip = len(VIP_USERS)
    permanent = sum(1 for v in VIP_USERS.values() if v is None)
    timed = total_vip - permanent
    total_cards = await db_card_count_total()
    used_cards = await db_card_count_used()

    from scraper import gallery_clicks, keyword_popularity
    regular_users = [uid for uid in ALL_USERS if uid not in VIP_USERS]
    vip_users_list = [uid for uid in VIP_USERS if uid not in ADMIN_IDS]

    # Dashboard stats
    stats_text = (
        "📊 <b>管理员面板</b>\n\n"
        f"👥 总用户: {len(ALL_USERS)}\n"
        f"   普通用户: {len(regular_users)}\n"
        f"   VIP用户: {total_vip} ({permanent}永久 + {timed}限时)\n\n"
        f"🔑 卡密: 已用{used_cards}/总计{total_cards}\n"
        f"🔍 搜索热词: {len(keyword_popularity)}\n"
        f"📈 点击记录: {len(gallery_clicks)}\n"
        f"🔗 邀请码: {len(INVITES)}"
    )

    # Weekly trends
    stats_text += "\n\n<b>📅 最近7天趋势:</b>\n"
    stats_text += f"  VIP到期(7天内): {sum(1 for v in VIP_USERS.values() if v is not None and 0 < v - now < 7*86400)}\n"

    if vip_users_list:
        stats_text += "\n\n<b>👑 VIP用户:</b>\n"
        for uid in vip_users_list[:5]:
            exp = VIP_USERS.get(uid)
            exp_str = "永久" if exp is None else datetime.fromtimestamp(exp).strftime("%m-%d")
            stats_text += f"  • {uid} ({exp_str})\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 设置VIP用户", callback_data="admin_setvip_prompt")],
        [InlineKeyboardButton("🔫 生成卡密", callback_data="admin_gencode")],
        [InlineKeyboardButton("📥 导出卡密TXT", callback_data="admin_exportcards")],
        [InlineKeyboardButton("🔍 查看全部用户", callback_data="admin_listusers")],
    ])
    await update.message.reply_text(stats_text, parse_mode="HTML", reply_markup=keyboard)

async def cmd_stats(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    total_vip = len(VIP_USERS)
    permanent = sum(1 for v in VIP_USERS.values() if v is None)
    timed = total_vip - permanent
    total_cards = await db_card_count_total()
    used_cards = await db_card_count_used()
    from scraper import gallery_clicks, keyword_popularity
    stats = (
        "📊 <b>统计数据</b>\n\n"
        f"👥 用户: {len(ALL_USERS)} (普通 {len(ALL_USERS - set(VIP_USERS.keys()))})\n"
        f"👑 VIP: {total_vip} ({permanent}永久 + {timed}限时)\n"
        f"🔑 卡密: 已用{used_cards}/总计{total_cards}\n"
        f"🔍 搜索热词: {len(keyword_popularity)}\n"
        f"📈 点击记录: {len(gallery_clicks)}\n"
    )
    await update.message.reply_text(stats, parse_mode="HTML")

async def cmd_report(update, context):
    """Daily report for admins — shows new users, activations, searches over last 7 days."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    rows = await db_get_stats_last_days(7)
    if not rows:
        await update.message.reply_text("📊 暂无统计数据（需要运行至少一天）")
        return
    text = "📊 <b>最近7天运营报表</b>\n\n"
    total_new = 0
    total_activations = 0
    total_searches = 0
    total_clicks = 0
    for r in rows:
        day = r.get("date", "?")
        nu = r.get("new_users", 0)
        ca = r.get("card_activations", 0)
        sr = r.get("searches", 0)
        cl = r.get("clicks", 0)
        text += f"🗓 {day}: +{nu}用户 | {ca}激活 | {sr}搜索 | {cl}点击\n"
        total_new += nu
        total_activations += ca
        total_searches += sr
        total_clicks += cl
    text += f"\n<b>合计:</b> +{total_new}用户 | {total_activations}激活 | {total_searches}搜索 | {total_clicks}点击"
    text += f"\n\n👥 当前总用户: {await db_user_count()}"
    text += f"\n👑 VIP: {await db_vip_count()} ({await db_vip_permanent_count()}永久)"
    text += f"\n🔑 卡密: 已用{await db_card_count_used()}/{await db_card_count_total()}"
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_my(update, context):
    user_id = update.effective_user.id
    if is_vip(user_id):
        expiry = VIP_USERS.get(user_id)
        if expiry is None:
            info = "永久会员 ♾️"
        else:
            exp_str = datetime.fromtimestamp(expiry).strftime("%Y年%m月%d日")
            remaining = max(0, int((expiry - now_ts()) / 86400))
            info = f"到期：{exp_str}  (剩{remaining}天)"
        # First check invite info
        my_invites = [code for code, inviter in INVITES.items() if inviter == str(user_id)]
        inv_text = f"\n\n🔗 你的邀请码: <code>{my_invites[0]}</code>\n发送: /start {my_invites[0]} 给好友" if my_invites else ""
        await update.message.reply_text(
            f"👑 <b>你的VIP信息</b>\n\n{info}{inv_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ 收藏夹", callback_data="fav_list")],
                [InlineKeyboardButton("🔗 生成邀请码", callback_data="invite_gen")],
                [InlineKeyboardButton("🔑 续费/升级", callback_data="vip_activate")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")],
            ]))
    else:
        await update.message.reply_text(
            "👑 <b>VIP会员</b>\n\n你还不是VIP会员哦～\n开通后可以：\n• 查看全部搜索结果\n• 翻页浏览所有图片\n• 收藏喜欢的图集",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 输入卡密激活", callback_data="vip_activate")],
                [InlineKeyboardButton("💳 购买卡密", url=PURCHASE_URL)],
                [InlineKeyboardButton("🔗 邀请好友得VIP", callback_data="invite_info")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")],
            ]))

async def cmd_help(update, context):
    await update.message.reply_text(
        "<b>📖 使用帮助</b>\n\n"
        "点击「🔍 搜索图集」后直接输入关键词即可\n"
        "/search 关键词 - 快速搜索\n"
        "/random - 随机推荐\n"
        "/my - 查看VIP & 邀请\n"
        "/start - 回到主菜单",
        parse_mode="HTML"
    )

# ---- Shared hot-keyword button builder ----
async def build_hot_keyword_keyboard(extra_buttons=None, for_results=False, user_id: int = None):
    """Build inline keyboard of hot keyword buttons plus user's search history."""
    from scraper import get_hot_keywords
    buttons = []
    # User's recent search history
    if user_id is not None:
        history = await db_get_user_history(user_id, limit=6)
        if history:
            hist_row = []
            for kw in history[:3]:
                hist_row.append(InlineKeyboardButton(f"🕐 {kw}", callback_data=f"hot_{html.escape(kw)}"))
            if hist_row:
                buttons.append(hist_row)
    # Hot keywords
    hot = await get_hot_keywords(top_n=8)
    row = []
    for kw in hot:
        row.append(InlineKeyboardButton(kw, callback_data=f"hot_{html.escape(kw)}"))
        if len(row) >= 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if extra_buttons:
        buttons.extend(extra_buttons)
    return InlineKeyboardMarkup(buttons)

async def cmd_search(update, context):
    user_id = update.effective_user.id
    if not context.args:
        user_waiting_search.add(user_id)
        keyboard = await build_hot_keyword_keyboard([
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")],
        ], user_id=user_id)
        await update.message.reply_text(
            "🔍 请直接输入搜索关键词～\n\n🔥 <b>热门搜索：</b>",
            parse_mode="HTML",
            reply_markup=keyboard)
        return
    keyword = " ".join(context.args)
    await _do_search(update, keyword)

async def cmd_random(update, context):
    user_id = update.effective_user.id
    user_waiting_search.discard(user_id)
    msg = await update.message.reply_text("🎲 正在随机推荐...")
    try:
        gallery = await get_random_gallery()
    except Exception as e:
        logger.error(f"Random error: {traceback.format_exc()}")
        await send_or_edit(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    if not gallery:
        await send_or_edit(msg, "😔 获取随机推荐失败，请稍后再试。")
        return
    await msg.delete()
    await _route_random_gallery(update, gallery)

