"""
TG Inline-Keyboard Admin Panel
"""
import os, time, asyncio
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from config import config
from database import db
from roles import ROLES
from utils.logger import logger

BJT = timezone(timedelta(hours=8))

def _ok(update):
    return update.effective_user.id in config.ADMIN_IDS

def _bk(d="admin:main"):
    return InlineKeyboardButton('◀ 返回', callback_data=d)

async def admin_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        await update.message.reply_text('⛔ 仅限管理员')
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 Dashboard', callback_data="admin:dash")],
        [InlineKeyboardButton('👥 用户管理', callback_data="admin:users")],
        [InlineKeyboardButton('📢 Broadcast', callback_data="admin:bcast")],
        [InlineKeyboardButton('⚙ System', callback_data="admin:sys")],
    ])
    await update.message.reply_text('🛡 **Admin Panel**\n\n欢迎回来，管理员', reply_markup=kb, parse_mode="Markdown")

async def admin_dash(query, context):
    t = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    td = db.conn.execute("SELECT COUNT(DISTINCT user_id) FROM chat_history WHERE updated_at > ?", (datetime.now(BJT).replace(hour=0,minute=0,second=0).isoformat(),)).fetchone()[0]
    v = db.conn.execute("SELECT COUNT(*) FROM user_profiles WHERE vip_tier > 0").fetchone()[0]
    m = db.conn.execute("SELECT SUM(total_messages) FROM users").fetchone()[0] or 0
    rs = db.conn.execute("SELECT current_role, COUNT(*) FROM users WHERE total_messages>0 GROUP BY current_role ORDER BY COUNT(*) DESC LIMIT 10").fetchall()
    lines = ['📊 **Dashboard**\n',
        f"👥 总用户: {t}",
        f"💬 总消息: {m}",
        f"🕓 今日活跃: {td}",
        f"💎 VIP: {v}",
        "",
        "**Top Roles:**",
    ]
    for r in rs:
        n = ROLES.get(r["current_role"],{}).get("name",r["current_role"])
        lines.append(f"  {n}: {r[1]}")
    kb = InlineKeyboardMarkup([[_bk()]])
    await query.edit_message_text(chr(10).join(lines), reply_markup=kb, parse_mode="Markdown")

async def admin_users(query, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('🔍 搜索用户', callback_data="admin:search")],
        [InlineKeyboardButton('📋 最近用户', callback_data="admin:recent")],
        [InlineKeyboardButton('💎 VIP列表', callback_data="admin:viplist")],
        [_bk()],
    ])
    await query.edit_message_text('👥 **用户管理**\n\n请选择操作', reply_markup=kb, parse_mode="Markdown")

async def admin_recent(query, context):
    us = db.conn.execute("SELECT user_id,total_messages,current_role FROM users ORDER BY user_id DESC LIMIT 20").fetchall()
    lines = ['📋 **最近用户**\n']
    for u in us:
        n = ROLES.get(u["current_role"],{}).get("name",u["current_role"])
        lines.append("`{uid}` | {n} | {msgs}msgs".format(uid=u["user_id"], n=n, msgs=u["total_messages"]))
    kb = InlineKeyboardMarkup([[_bk("admin:users")]])
    await query.edit_message_text(chr(10).join(lines), reply_markup=kb, parse_mode="Markdown")

async def admin_viplist(query, context):
    vs = db.conn.execute("SELECT user_id,vip_tier,interests FROM user_profiles WHERE vip_tier>0 ORDER BY vip_tier DESC").fetchall()
    lines = ['💎 **VIP 用户**\n']
    for v in vs:
        lines.append("`{uid}` tier={tier} {interest}".format(uid=v["user_id"], tier=v["vip_tier"], interest=v["interests"] or ""))
    if not vs:
        lines.append('暂无VIP用户')
    kb = InlineKeyboardMarkup([[_bk("admin:users")]])
    await query.edit_message_text(chr(10).join(lines), reply_markup=kb, parse_mode="Markdown")

async def admin_bcast(query, context):
    t = db.conn.execute("SELECT COUNT(*) FROM users WHERE total_messages>0").fetchone()[0]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📢 发送全部({t})", callback_data="admin:sendall")],
        [_bk()],
    ])
    await query.edit_message_text(f"📢 **Broadcast**\n\n当前活跃用户: {t}", reply_markup=kb, parse_mode="Markdown")

async def admin_sendall(query, context):
    kb = InlineKeyboardMarkup([[_bk("admin:bcast")]])
    await query.edit_message_text('💬 请用 `/broadcast <消息>` 发送', reply_markup=kb, parse_mode="Markdown")

async def admin_sys(query, context):
    lines = ['⚙ **System**\n',
        f"💾 DB: `{config.DB_PATH}`",
        f"📦 大小: {os.path.getsize(config.DB_PATH)/1024:.1f}KB",
        f"🎭 Roles: {len(ROLES)}",
        f"🤖 LLM: {config.LLM_PROVIDER}",
        f"🎙 TTS: {config.TTS_PROVIDER}",
    ]
    kb = InlineKeyboardMarkup([[_bk()]])
    await query.edit_message_text(chr(10).join(lines), reply_markup=kb, parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _ok(update):
        await query.edit_message_text('⛔ 仅限管理员')
        return
    data = query.data
    routes = {
        "admin:dash": lambda: admin_dash(query, context),
        "admin:users": lambda: admin_users(query, context),
        "admin:recent": lambda: admin_recent(query, context),
        "admin:viplist": lambda: admin_viplist(query, context),
        "admin:bcast": lambda: admin_bcast(query, context),
        "admin:sendall": lambda: admin_sendall(query, context),
        "admin:sys": lambda: admin_sys(query, context),
    }
    h = routes.get(data)
    if h: await h()
    else: await query.edit_message_text('❓ Unknown')
