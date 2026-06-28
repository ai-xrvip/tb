"""
Prompt 模板引擎 —— 参考 Dify 的模板变量设计
支持在 system_prompt 中使用 {time} {weather} {user_name} {mood} {relationship} 等动态变量
每次请求前自动替换为实时值，让提示词管理从硬编码变成可配置
"""
from datetime import datetime, timezone, timedelta
from cities import ROLE_CITIES, get_weather_str


def _get_time_of_day_str() -> str:
    """获取时段描述（中文）"""
    # 北京时间
    h = (datetime.now(timezone.utc) + timedelta(hours=8)).hour
    if 5 <= h < 7:   return "清晨"
    elif 7 <= h < 9:  return "早晨"
    elif 9 <= h < 12: return "上午"
    elif 12 <= h < 14: return "中午"
    elif 14 <= h < 17: return "下午"
    elif 17 <= h < 19: return "傍晚"
    elif 19 <= h < 22: return "晚上"
    elif 22 <= h < 24: return "深夜"
    else:              return "凌晨"


def _get_weekday_str() -> str:
    """获取星期描述"""
    wd = (datetime.now(timezone.utc) + timedelta(hours=8)).weekday()
    days = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return days[wd]


def _get_date_str() -> str:
    """获取日期描述"""
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    return f"{now.year}年{now.month}月{now.day}日"


def resolve_template(system_prompt: str, **kwargs) -> str:
    """解析模板变量，替换为实时值"""
    role_id = kwargs.get("role_id", "xiaolu")
    user_name = kwargs.get("user_name", "宝贝")
    mood_str = kwargs.get("mood", "")
    rel_str = kwargs.get("relationship", "")
    role_name = kwargs.get("role_name", "")

    # 天气
    city = ROLE_CITIES.get(role_id, "Beijing")
    weather_str = get_weather_str(city)

    # 替换
    result = system_prompt

    replacements = {
        "{time}": _get_time_of_day_str(),
        "{date}": _get_date_str(),
        "{weekday}": _get_weekday_str(),
        "{weather}": weather_str or "晴朗",
        "{user_name}": user_name,
        "{mood}": mood_str,
        "{relationship}": rel_str,
        "{role_name}": role_name,
        "{city}": city.replace("+", " "),
    }

    for key, val in replacements.items():
        result = result.replace(key, val)

    return result


def resolve_system_prompt(role: dict, user_name: str = "宝贝", mood_str: str = "", rel_str: str = "") -> str:
    """便捷方法：直接根据角色 dict 解析模板"""
    role_id = role.get("id", "xiaolu")
    role_name = role.get("name", "")
    prompt = role.get("system_prompt", "")
    # Emoji instruction - Telegram emoji only, no kaomoji
    prompt += "\n\n【表情使用规则】\n使用Telegram原生emoji表情符号(如☺❤️✨😉💕🎀🌟😜🤭🥰😘💋🔥👀💦💋)来表达情感。结尾可以加1-2个适合语境的emoji。\n禁止使用任何颜文字/kaomoji（如 (^∇^)、(*/ω＼*)、(>～<)、qwq、QAQ 等），颜文字会破坏聊天气氛。\n"
    return resolve_template(
        prompt,
        role_id=role_id,
        user_name=user_name,
        mood=mood_str,
        relationship=rel_str,
        role_name=role_name,
    )
