"""
智能媒体标签路由表
每个标签独立定义：图从哪个文件夹找(folder) + 需要什么解锁级别(tier)
支持全局默认 + 角色个性化标签
"""
from typing import Optional
import re
import random
from pathlib import Path

# ── 全局默认标签（所有角色通用） ──
# tier: 0=免费 1=20条付费 2=70条付费 3=150条付费
DEFAULT_MEDIA_TAGS = {
    # Tier 0: 免费，随时可发
    "日常":   {"folder": "日常", "tier": 0},
    "自拍":   {"folder": "自拍", "tier": 0},
    "表情":   {"folder": "表情", "tier": 0},
    "通勤":   {"folder": "通勤", "tier": 0},
    "穿搭":   {"folder": "穿搭", "tier": 0},
    "美食":   {"folder": "美食", "tier": 0},
    "宠物":   {"folder": "宠物", "tier": 0},
    "工作":   {"folder": "工作", "tier": 0},
    "运动":   {"folder": "运动", "tier": 0},
    # Tier 0: 角色专属免费标签
    "Cos":    {"folder": "Cos", "tier": 0},
    "JK":     {"folder": "JK", "tier": 0},
    "汉服":   {"folder": "汉服", "tier": 0},
    "旗袍":   {"folder": "旗袍", "tier": 0},
    "可爱":   {"folder": "可爱", "tier": 0},
    "下午茶":  {"folder": "下午茶", "tier": 0},
    "海边":   {"folder": "海边", "tier": 0},
    # Tier 1: 聊熟了(20条)
    "姿态":   {"folder": "姿态", "tier": 1},
    "旅游":   {"folder": "旅游", "tier": 1},
    "夜景":   {"folder": "夜景", "tier": 1},
    "起床":   {"folder": "起床", "tier": 1},
    "派对":   {"folder": "派对", "tier": 1},
    # Tier 1: 角色专属
    "黑丝":   {"folder": "黑丝", "tier": 1},
    "白丝":   {"folder": "白丝", "tier": 1},
    "丝袜":   {"folder": "丝袜", "tier": 1},
    "睡衣":   {"folder": "睡衣", "tier": 1},
    "睡裙":   {"folder": "睡裙", "tier": 1},
    "素纱":   {"folder": "素纱", "tier": 1},
    "蕾丝":   {"folder": "蕾丝", "tier": 1},
    "西装":   {"folder": "西装", "tier": 1},
    "职场":   {"folder": "职场", "tier": 1},
    "高跟鞋":  {"folder": "高跟鞋", "tier": 1},
    "红酒":   {"folder": "红酒", "tier": 1},
    "晚宴":   {"folder": "晚宴", "tier": 1},
    "外滩":   {"folder": "外滩", "tier": 1},
    "东京":   {"folder": "东京", "tier": 1},
    "浴衣":   {"folder": "浴衣", "tier": 1},
    "游艇":   {"folder": "游艇", "tier": 1},
    "珠宝":   {"folder": "珠宝", "tier": 1},
    "异国":   {"folder": "异国", "tier": 1},
    "酒店":   {"folder": "酒店", "tier": 1},
    "微醺":   {"folder": "微醺", "tier": 1},
    "打烊":   {"folder": "打烊", "tier": 1},
    "深夜":   {"folder": "深夜", "tier": 1},
    "后台":   {"folder": "后台", "tier": 1},
    "形体":   {"folder": "形体", "tier": 1},
    "舞蹈服":  {"folder": "舞蹈服", "tier": 1},
    # Tier 2: 关系升温(70条)
    "性感":   {"folder": "性感", "tier": 2},
    "泳装":   {"folder": "泳装", "tier": 2},
    "沐浴":   {"folder": "沐浴", "tier": 2},
    "情趣":   {"folder": "情趣", "tier": 2},
    # Tier 2: 角色专属
    "比基尼":  {"folder": "比基尼", "tier": 2},
    "运动bra": {"folder": "运动bra", "tier": 2},
    "网袜":   {"folder": "网袜", "tier": 2},
    "浴袍":   {"folder": "浴袍", "tier": 2},
    "沙滩":   {"folder": "沙滩", "tier": 2},
    "汗水":   {"folder": "汗水", "tier": 2},
    "瑜伽":   {"folder": "瑜伽", "tier": 2},
    "健身":   {"folder": "健身", "tier": 2},
    "晨跑":   {"folder": "晨跑", "tier": 2},
    "拉伸":   {"folder": "拉伸", "tier": 2},
    # Tier 3: 亲密关系(150条)
    "亲密":   {"folder": "亲密", "tier": 3},
    "裸露":   {"folder": "裸露", "tier": 3},
    "露点":   {"folder": "露点", "tier": 3},
    "全裸":   {"folder": "全裸", "tier": 3},
    "自慰":   {"folder": "自慰", "tier": 3},
}

# ── 角色个性化标签 ──
# 继承全局标签，额外增加角色专属的分类
# 如果标签名与全局重复，角色版会覆盖全局版（比如tier不同）

# Role-specific tags (extend/override defaults per role)
ROLE_MEDIA_TAGS: dict[str, dict] = {
    "xiaolu": {
        "丝袜": {"folder": "丝袜", "tier": 1},
        "Cos":  {"folder": "Cos", "tier": 0},
        "JK":   {"folder": "JK", "tier": 0},
    },
    "linxi": {
        "西装":   {"folder": "西装", "tier": 0},
        "职场":   {"folder": "职场", "tier": 0},
        "高跟鞋":  {"folder": "高跟鞋", "tier": 0},
        "黑丝":   {"folder": "黑丝", "tier": 1},
        "红酒":   {"folder": "红酒", "tier": 1},
        "晚宴":   {"folder": "晚宴", "tier": 1},
        "外滩":   {"folder": "外滩", "tier": 1},
        "丝袜":   {"folder": "丝袜", "tier": 2},
        "睡衣":   {"folder": "睡衣", "tier": 2},
    },
    "mia": {
        "健身":     {"folder": "健身", "tier": 0},
        "晨跑":     {"folder": "晨跑", "tier": 0},
        "拉伸":     {"folder": "拉伸", "tier": 0},
        "瑜伽":     {"folder": "瑜伽", "tier": 1},
        "运动bra":  {"folder": "运动bra", "tier": 1},
        "沙滩":     {"folder": "沙滩", "tier": 1},
        "汗水":     {"folder": "汗水", "tier": 1},
        "比基尼":   {"folder": "比基尼", "tier": 2},
    },
    "sunian": {
        "画室":   {"folder": "画室", "tier": 0},
        "文艺":   {"folder": "文艺", "tier": 0},
        "画展":   {"folder": "画展", "tier": 0},
        "茶道":   {"folder": "茶道", "tier": 0},
        "素描":   {"folder": "素描", "tier": 0},
        "旗袍":   {"folder": "旗袍", "tier": 1},
        "睡裙":   {"folder": "睡裙", "tier": 2},
    },
    "yuki": {
        "汉服":   {"folder": "汉服", "tier": 0},
        "古风":   {"folder": "古风", "tier": 0},
        "团扇":   {"folder": "团扇", "tier": 0},
        "油纸伞":  {"folder": "油纸伞", "tier": 0},
        "茶道":   {"folder": "茶道", "tier": 0},
        "旗袍":   {"folder": "旗袍", "tier": 1},
        "素纱":   {"folder": "素纱", "tier": 2},
    },
    "reina": {
        "大小姐":  {"folder": "大小姐", "tier": 0},
        "下午茶":  {"folder": "下午茶", "tier": 0},
        "和服":   {"folder": "和服", "tier": 0},
        "钢琴":   {"folder": "钢琴", "tier": 0},
        "马术":   {"folder": "马术", "tier": 0},
        "东京":   {"folder": "东京", "tier": 1},
        "浴衣":   {"folder": "浴衣", "tier": 1},
        "游艇":   {"folder": "游艇", "tier": 1},
        "珠宝":   {"folder": "珠宝", "tier": 1},
        "蕾丝":   {"folder": "蕾丝", "tier": 2},
    },
    "chiyo": {
        "围裙":    {"folder": "围裙", "tier": 0},
        "厨房":    {"folder": "厨房", "tier": 0},
        "海鲜":    {"folder": "海鲜", "tier": 0},
        "赶海":    {"folder": "赶海", "tier": 0},
        "菜市场":   {"folder": "菜市场", "tier": 0},
        "包饺子":   {"folder": "包饺子", "tier": 0},
        "海边":    {"folder": "海边", "tier": 1},
        "睡裙":    {"folder": "睡裙", "tier": 2},
    },
    "nana": {
        "电竞":   {"folder": "电竞", "tier": 0},
        "直播":   {"folder": "直播", "tier": 0},
        "零食":   {"folder": "零食", "tier": 0},
        "螺蛳粉":  {"folder": "螺蛳粉", "tier": 0},
        "睡衣":   {"folder": "睡衣", "tier": 1},
        "黑丝":   {"folder": "黑丝", "tier": 1},
    },
    "mizuki": {
        "西装":    {"folder": "西装", "tier": 0},
        "办公":    {"folder": "办公", "tier": 0},
        "高跟鞋":   {"folder": "高跟鞋", "tier": 0},
        "会议室":   {"folder": "会议室", "tier": 0},
        "红酒":    {"folder": "红酒", "tier": 1},
        "晚宴":    {"folder": "晚宴", "tier": 1},
        "私人飞机": {"folder": "私人飞机", "tier": 1},
        "丝袜":    {"folder": "丝袜", "tier": 2},
        "浴袍":    {"folder": "浴袍", "tier": 2},
    },
    "akari": {
        "护士服":  {"folder": "护士服", "tier": 0},
        "可爱":   {"folder": "可爱", "tier": 0},
        "听诊器":  {"folder": "听诊器", "tier": 0},
        "值夜班":  {"folder": "值夜班", "tier": 0},
        "睡衣":   {"folder": "睡衣", "tier": 1},
        "白丝":   {"folder": "白丝", "tier": 1},
    },
    "yuna": {
        "T台":     {"folder": "T台", "tier": 0},
        "高定":    {"folder": "高定", "tier": 0},
        "街拍":    {"folder": "街拍", "tier": 0},
        "时装周":   {"folder": "时装周", "tier": 0},
        "杂志":    {"folder": "杂志", "tier": 0},
        "后台":    {"folder": "后台", "tier": 1},
        "超模丝袜": {"folder": "超模丝袜", "tier": 1},
        "比基尼":  {"folder": "比基尼", "tier": 2},
    },
    "shiori": {
        "书店":    {"folder": "书店", "tier": 0},
        "文艺":    {"folder": "文艺", "tier": 0},
        "咖啡馆":   {"folder": "咖啡馆", "tier": 0},
        "图书馆":   {"folder": "图书馆", "tier": 0},
        "手帐":    {"folder": "手帐", "tier": 0},
        "雨天":    {"folder": "雨天", "tier": 0},
        "睡裙":    {"folder": "睡裙", "tier": 2},
    },
    "sora": {
        "制服":    {"folder": "制服", "tier": 0},
        "机场":    {"folder": "机场", "tier": 0},
        "旅行":    {"folder": "旅行", "tier": 0},
        "机舱":    {"folder": "机舱", "tier": 0},
        "免税店":   {"folder": "免税店", "tier": 0},
        "异国":    {"folder": "异国", "tier": 1},
        "酒店":    {"folder": "酒店", "tier": 1},
        "丝袜":    {"folder": "丝袜", "tier": 2},
    },
    "kaede": {
        "警服":   {"folder": "警服", "tier": 0},
        "训练":   {"folder": "训练", "tier": 0},
        "便衣":   {"folder": "便衣", "tier": 0},
        "英气":   {"folder": "英气", "tier": 0},
        "射击":   {"folder": "射击", "tier": 0},
        "警车":   {"folder": "警车", "tier": 0},
        "散打":   {"folder": "散打", "tier": 0},
    },
    "ruri": {
        "西装":    {"folder": "西装", "tier": 0},
        "职场":    {"folder": "职场", "tier": 0},
        "高跟鞋":   {"folder": "高跟鞋", "tier": 0},
        "法庭":    {"folder": "法庭", "tier": 0},
        "卷宗":    {"folder": "卷宗", "tier": 0},
        "谈判":    {"folder": "谈判", "tier": 0},
        "红酒":    {"folder": "红酒", "tier": 1},
        "晚宴":    {"folder": "晚宴", "tier": 1},
        "丝袜":    {"folder": "丝袜", "tier": 2},
    },
    "ren": {
        "调酒":   {"folder": "调酒", "tier": 0},
        "酒吧":   {"folder": "酒吧", "tier": 0},
        "微醺":   {"folder": "微醺", "tier": 1},
        "黑丝":   {"folder": "黑丝", "tier": 1},
        "打烊":   {"folder": "打烊", "tier": 1},
        "深夜":   {"folder": "深夜", "tier": 1},
        "网袜":   {"folder": "网袜", "tier": 2},
    },
    "hana": {
        "花店":   {"folder": "花店", "tier": 0},
        "田园":   {"folder": "田园", "tier": 0},
        "午后":   {"folder": "午后", "tier": 0},
        "插花":   {"folder": "插花", "tier": 0},
        "浇水":   {"folder": "浇水", "tier": 0},
        "多肉":   {"folder": "多肉", "tier": 0},
        "睡裙":   {"folder": "睡裙", "tier": 2},
    },
    "mai": {
        "芭蕾":    {"folder": "芭蕾", "tier": 0},
        "练功房":   {"folder": "练功房", "tier": 0},
        "演出":    {"folder": "演出", "tier": 0},
        "舞鞋":    {"folder": "舞鞋", "tier": 0},
        "绷带":    {"folder": "绷带", "tier": 0},
        "形体":    {"folder": "形体", "tier": 1},
        "舞蹈服":   {"folder": "舞蹈服", "tier": 1},
    },
    "momo": {
        "烘焙":   {"folder": "烘焙", "tier": 0},
        "厨房":   {"folder": "厨房", "tier": 0},
        "甜品":   {"folder": "甜品", "tier": 0},
        "围裙":   {"folder": "围裙", "tier": 0},
        "可爱":   {"folder": "可爱", "tier": 0},
        "裱花":   {"folder": "裱花", "tier": 0},
        "试吃":   {"folder": "试吃", "tier": 0},
        "夜市":   {"folder": "夜市", "tier": 0},
    },
    "sakura": {
        "白大褂":  {"folder": "白大褂", "tier": 0},
        "温柔":   {"folder": "温柔", "tier": 0},
        "狗狗":   {"folder": "狗狗", "tier": 0},
        "手术":   {"folder": "手术", "tier": 0},
    },
}

def get_media_config(role_id: str, tag: str) -> dict | None:
    """Look up tag config: role-specific first, then global default."""
    role_tags = ROLE_MEDIA_TAGS.get(role_id, {})
    if tag in role_tags:
        return role_tags[tag]
    return DEFAULT_MEDIA_TAGS.get(tag)

def get_tags_for_role(role_id: str) -> dict:
    """Return merged tags for a role: global defaults + role overrides."""
    merged = dict(DEFAULT_MEDIA_TAGS)
    role_tags = ROLE_MEDIA_TAGS.get(role_id, {})
    merged.update(role_tags)
    return merged

def get_folder(role_id: str, tag: str) -> str | None:
    """Get the folder name for a tag. Role-specific first, then default."""
    cfg = get_media_config(role_id, tag)
    return cfg["folder"] if cfg else None

def get_tier(role_id: str, tag: str) -> int:
    """获取标签需要的解锁级别"""
    cfg = get_media_config(role_id, tag)
    if cfg:
        return cfg["tier"]
    return 0  # 默认免费

def get_max_tier_for_text(role_id, text):
    """Check AI reply text against all tags, return highest tier required."""
    all_tags = get_tags_for_role(role_id)
    max_tier = 0
    for tag, cfg in all_tags.items():
        if tag in text and cfg.get("tier", 0) > max_tier:
            max_tier = cfg["tier"]
    return max_tier


# ── 图片文件选取 ──

def pick_random_image(role_id: str, tag: str) -> str | None:
    """Pick a random image file path for the given tag and role.
    Returns the absolute path, or None if no images found."""
    folder_name = get_folder(role_id, tag)
    if not folder_name:
        return None
    media_base = Path(__file__).parent / "media" / role_id / folder_name
    if not media_base.is_dir():
        return None
    valid_exts = (".jpg", ".jpeg", ".png", ".webp")
    images = [f for f in media_base.iterdir()
              if f.suffix.lower() in valid_exts and f.is_file()]
    if not images:
        return None
    return str(random.choice(images))


MEDIA_TAG_RE = re.compile(r"\[media:([^\]]+)\]")


def extract_media_tags(text: str) -> list[str]:
    """Extract all unique [media:xxx] tags from text."""
    return list(set(MEDIA_TAG_RE.findall(text)))


def strip_media_tags(text: str) -> str:
    """Remove all [media:xxx] tags from text."""
    return MEDIA_TAG_RE.sub("", text).strip()


async def resolve_media_tags(
    text: str,
    role_id: str,
    user_id: int,
    update,
    unlock_tier: int,
) -> str:
    """Find all [media:XXX] tags in text, check tier, send matching images.

    For each tag:
    1. Looks up the folder via get_folder(role_id, tag)
    2. Checks if user''s unlock_tier >= required tier
    3. If yes, picks a random image and sends it via reply_photo
    4. Strips the tag from the text

    Returns the cleaned text (with all [media:xxx] tags removed).
    """
    from database import db

    tags_found = extract_media_tags(text)
    if not tags_found:
        return text

    for tag in tags_found:
        required_tier = get_tier(role_id, tag)
        if unlock_tier >= required_tier:
            img_path = pick_random_image(role_id, tag)
            if img_path:
                try:
                    with open(img_path, "rb") as f:
                        await update.message.reply_photo(photo=f)
                except Exception as e:
                    from utils.logger import logger
                    logger.error(f"Failed to send media for tag '{tag}': {e}")

    return strip_media_tags(text)
