"""用户评价/截图精选"""
import io
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import ContextTypes
from config import config
from database import db
from roles import get_role
from utils.logger import logger

SCREEN_WIDTH = 480
PADDING = 16
BUBBLE_RADIUS = 12

_pending_testimonials = {}

def _try_load_font(size, bold=False):
    import os
    for fp in [
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()

def _wrap_text(draw, text, font, max_w):
    lines = []
    cur = ""
    for ch in text:
        t = cur + ch
        b = draw.textbbox((0, 0), t, font=font)
        if b[2] - b[0] > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines

def _gen_image(messages, role_name):
    font = _try_load_font(15)
    font_n = _try_load_font(12, bold=True)
    font_t = _try_load_font(11)
    mw = SCREEN_WIDTH - PADDING * 2 - 40
    dt = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    rows = []
    yh = PADDING + 30
    for m in messages:
        text = m.get("content", "")
        is_user = m.get("role", "user") == "user"
        label = "用户" if is_user else role_name
        lns = _wrap_text(dt, text, font, mw)
        bh = len(lns) * 21 + 32 + 12
        rows.append((label, lns, bh, is_user))
        yh += bh + 10
    th = yh + PADDING + 50
    img = Image.new("RGB", (SCREEN_WIDTH, th), (237, 240, 245))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, SCREEN_WIDTH, 36], fill=(40, 40, 40))
    draw.text((PADDING, 8), "💬 " + role_name + " · 真实对话", fill=(255, 255, 255), font=font_n)
    y = PADDING + 46
    for label, lns, bh, is_user in rows:
        bw = min(max(len(l) for l in lns) * 8 + 60, SCREEN_WIDTH - PADDING * 2 - 20)
        if is_user:
            x = SCREEN_WIDTH - PADDING - bw
            draw.rounded_rectangle([x, y, x + bw, y + bh], radius=12, fill=(42, 150, 238))  # TG blue
            draw.text((x + 10, y + 6), label, fill=(140, 140, 140), font=font_n)
            yy = y + 30
            for line in lns:
                draw.text((x + 10, yy), line, fill=(255, 255, 255), font=font)
                yy += 21
        else:
            x = PADDING
            draw.rounded_rectangle([x, y, x + bw, y + bh], radius=12, fill=(255, 255, 255))
            draw.text((x + 10, y + 6), label, fill=(140, 140, 140), font=font_n)
            yy = y + 30
            for line in lns:
                draw.text((x + 10, yy), line, fill=(30, 30, 30), font=font)
                yy += 21
        y += bh + 10
    draw.text((PADDING, th - 30), "OnlyAI · 真实用户对话 · 已脱敏处理", fill=(180, 180, 180), font=font_t)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("管理员限定")
        return
    if not context.args:
        await update.message.reply_text("/screenshot 用户ID [条数]")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID必须数字")
        return
    cnt = min(int(context.args[1]) if len(context.args) > 1 else 8, 20)
    ud = db.get_user(tid)
    if not ud:
        await update.message.reply_text("用户不存在")
        return
    if db.get_unlock_tier(tid, ud.get("current_role", "xiaolu")) == 0:
        await update.message.reply_text("未付费不能截图")
        return
    hist = db.get_chat_history(tid)
    if not hist:
        await update.message.reply_text("无对话记录")
        return
    recent = hist[-(cnt * 2):]
    if not recent:
        await update.message.reply_text("对话不足")
        return
    rid = ud.get("current_role", "xiaolu")
    role = get_role(rid)
    rn = role.get("name", rid) if role else rid
    try:
        buf = _gen_image(recent, rn)
    except Exception as e:
        logger.error(f"Screenshot: {e}")
        await update.message.reply_text("生成失败")
        return
    await update.message.reply_photo(buf, caption=f"用户{tid} · {rn} 共{len(recent)}条\n/post 发布")
    buf.seek(0)
    _pending_testimonials[user.id] = {"user_id": tid, "role_id": rid, "image_bytes": buf.read()}

async def cmd_post_testimonial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("管理员限定")
        return
    if not config.ANNOUNCEMENT_CHANNEL:
        await update.message.reply_text("未设置公告频道")
        return
    p = _pending_testimonials.pop(user.id, None)
    if not p:
        await update.message.reply_text("先 /screenshot 生成截图")
        return
    role = get_role(p["role_id"])
    rn = role.get("name", p["role_id"]) if role else p["role_id"]
    buf = io.BytesIO(p["image_bytes"])
    try:
        await context.bot.send_photo(config.ANNOUNCEMENT_CHANNEL, buf, caption=f"真实对话 · {rn}\n#用户评价")
        await update.message.reply_text("已发布到频道")
    except Exception as e:
        logger.error(f"发布失败: {e}")
        await update.message.reply_text("发布失败")