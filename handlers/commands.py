"""
命令处理器 —— /start /redeem /gencode
"""
import uuid
import random
from telegram import Update
from telegram.ext import ContextTypes
from config import config
from database import db
from roles import ROLES
from utils.logger import logger


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /start —— 直接问对方称呼，进入互相了解流程 """
    user = update.effective_user
    user_id = user.id

    db.create_user(user_id)
    role_id = context.bot_data.get("role_id", "xiaolu")
    role = ROLES.get(role_id, ROLES["xiaolu"])

    # 先问对方怎么称呼，不自我介绍不展示角色切换
    await update.message.reply_text(
        f"嗨～我是{role['name']}，怎么称呼你呀？(*^▽^*)"
    )
async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /checkin -- 每日签到 """
    user = update.effective_user
    user_id = user.id
    db.create_user(user_id)

    role_id = context.bot_data.get("role_id", "xiaolu")
    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)

    if db.has_checked_in_today(user_id):
        replies = [
            f"今天已经见过面啦～明天再来找我好不好？{role_name}会一直等你的 💕",
            f"诶？不是才刚聊过嘛～{role_name}今天的心情都被你点亮啦，明天继续哦 ✨",
        ]
        await update.message.reply_text(random.choice(replies))
        return

    db.do_checkin(user_id)
    replies = [
        f"你来看我啦～今天一整天都在等你，总算把你盼来了 💕",
        f"早呀！{role_name}刚醒就想起你了…今天也要开开心心的哦 ☀️",
        f"终于等到你！今天有什么想跟我说的吗？我一直在听～",
    ]
    await update.message.reply_text(random.choice(replies))


async def cmd_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /redeem <激活码> —— 兑换 VIP """
    user = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text("⚠️ 请提供激活码：`/redeem XXXX-XXXX`")
        return

    code = context.args[0].strip().upper()
    code_data = db.get_code(code)

    if not code_data:
        await update.message.reply_text("❌ 激活码无效，请检查后重试。")
        return

    if code_data["is_used"]:
        await update.message.reply_text("⚠️ 该激活码已被使用。")
        return

    db.create_user(user_id)
    db.use_code(code, user_id)
    days = code_data["days"]
    db.set_vip(user_id, days)

    type_label = {"month": "月卡(30天)", "quarter": "季卡(90天)", "year": "年卡(365天)"}.get(
        code_data["type"], f"{days}天"
    )

    await update.message.reply_text(
        f"🎉 激活成功！\n"
        f"📦 类型：{type_label}\n"
        f"⏰ 有效期：{days} 天\n"
        f"💎 现在可以无限畅聊啦～"
    )


async def cmd_gencode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /gencode —— 管理员生成激活码（限 ADMIN_IDS） """
    user = update.effective_user
    user_id = user.id

    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("⛔ 此命令仅限管理员使用。")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "用法：`/gencode <数量> <类型>`\n"
            "类型：month(30天) / quarter(90天) / year(365天)"
        )
        return

    try:
        count = int(context.args[0])
    except ValueError:
        await update.message.reply_text("数量必须是数字。")
        return

    code_type = context.args[1].lower()
    type_days = {"month": 30, "quarter": 90, "year": 365}
    if code_type not in type_days:
        await update.message.reply_text("类型无效，可选：month / quarter / year")
        return

    if count < 1 or count > 50:
        await update.message.reply_text("数量范围：1-50")
        return

    days = type_days[code_type]
    generated = []
    for _ in range(count):
        code = uuid.uuid4().hex[:12].upper()
        code = f"{code[:4]}-{code[4:8]}-{code[8:12]}"
        db.import_code(code, code_type, days)
        generated.append(code)

    await update.message.reply_text(
        f"✅ 已生成 {count} 个 {code_type} 激活码({days}天)：\n\n"
        + "\n".join(f"`{c}`" for c in generated)
    )