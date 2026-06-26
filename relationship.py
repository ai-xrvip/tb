"""
关系等级系统 —— 跟踪用户与角色的关系深度，影响角色说话方式
等级: stranger(0) -> acquaintance(1) -> friend(2) -> close(3) -> lover(4) -> passionate(5)
"""
import random
from database import db

RELATIONSHIP_LEVELS = [
    {"id": 0, "name": "陌生人", "min_msgs": 0,    "prompt_tag": "初次见面，保持礼貌距离"},
    {"id": 1, "name": "熟人",   "min_msgs": 10,   "prompt_tag": "认识一段时间了，语气可以轻松一些"},
    {"id": 2, "name": "朋友",   "min_msgs": 30,   "prompt_tag": "已经是朋友了，可以开玩笑"},
    {"id": 3, "name": "亲密",   "min_msgs": 70,   "prompt_tag": "关系很亲近，可以暧昧"},
    {"id": 4, "name": "恋人",   "min_msgs": 150,  "prompt_tag": "已经像恋人一样了，可以撒娇说情话"},
    {"id": 5, "name": "热恋",   "min_msgs": 300,  "prompt_tag": "热恋中的情侣，可以大胆亲密"},
]


def get_relationship_level(total_msgs: int) -> dict:
    """根据消息数获取关系等级"""
    level = RELATIONSHIP_LEVELS[0]
    for lv in reversed(RELATIONSHIP_LEVELS):
        if total_msgs >= lv["min_msgs"]:
            level = lv
            break
    return level


def get_relationship_prompt(role_id: str, user_id: int) -> str:
    """返回关系等级描述，用于注入 system_prompt"""
    total = db.get_user(user_id).get("total_messages", 0) if db.get_user(user_id) else 0
    level = get_relationship_level(total)
    return f"[当前关系: {level['name']}] {level['prompt_tag']}"


# ── 角色状态系统 ──
MOODS = [
    {"id": "happy",    "name": "开心",     "prompt": "今天心情特别好，说话都带～"},
    {"id": "tired",    "name": "疲倦",     "prompt": "今天好累啊，说话懒懒的"},
    {"id": "sleepy",   "name": "困了",     "prompt": "刚睡醒/快睡着了，迷迷糊糊的"},
    {"id": "sad",      "name": "低落",     "prompt": "今天有点不开心，需要人哄"},
    {"id": "playful",  "name": "调皮",     "prompt": "今天想逗你玩，调皮的语气"},
    {"id": "sexy",     "name": "性感",     "prompt": "今天穿了好看的内衣，心情很好很撩人"},
    {"id": "angry",    "name": "生气",     "prompt": "生气了，说话带刺但其实是希望你哄"},
    {"id": "neutral",  "name": "平常",     "prompt": "和平常一样"},
    {"id": "period",   "name": "经期",     "prompt": "来姨妈了，肚子不舒服，有点烦躁想要人关心"},
]

# 经期模拟：28天周期，每5-7天为经期
PERIOD_CYCLE = 28
PERIOD_LENGTH = 6


def get_random_mood() -> dict:
    """随机选择一个心情（加权）"""
    weights = [15, 12, 8, 5, 10, 8, 3, 35, 4]  # 百分比权重
    return random.choices(MOODS, weights=weights, k=1)[0]


def get_mood_for_user(user_id: int, role_id: str) -> dict:
    """获取用户当前的 mood，带经期逻辑（女性角色）"""
    # 用用户ID+天数做种子，保证一天内同用户同角色 mood 稳定
    import time, hashlib
    day_seed = int(time.time()) // 86400
    seed_str = f"{user_id}_{role_id}_{day_seed}"
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # 检查是否在经期（模拟）
    period_day = seed % PERIOD_CYCLE
    if period_day < PERIOD_LENGTH:
        return {"id": "period", "name": "经期", "prompt": "来姨妈了，肚子不舒服，有点烦躁想要人关心"}

    weights = [15, 12, 8, 5, 10, 8, 3, 35, 4]
    return rng.choices(MOODS, weights=weights, k=1)[0]


def get_mood_prompt(user_id: int, role_id: str) -> str:
    """返回心情描述，用于注入 system_prompt"""
    mood = get_mood_for_user(user_id, role_id)
    return f"[当前心情: {mood['name']}] {mood['prompt']}"
