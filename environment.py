"""
天气/心情感知模块 —— 获取当前天气和时间信息，注入到 AI prompt
使用 cities.py 提供的共享天气缓存 + localization.py 提供的时区和地域化描述
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from cities import ROLE_CITIES, get_weather_str
from localization import get_locale, get_local_time


def _get_weather_detail(city: str) -> Optional[dict]:
    """获取城市天气详细信息"""
    weather_str = get_weather_str(city)
    if not weather_str:
        return None
    # 格式示例: "Light Rain Shower +27\u00b0C" 或 "Sunny 32\u00b0C"
    # 描述可能包含多个单词，温度最后一段以 +/- 开头，\u00b0C 结尾
    import re as _re
    temp_match = _re.search(r'[+-]?\d+(?=\u00b0C)', weather_str)
    if temp_match:
        temp = temp_match.group(0).replace("+", "")
        desc = weather_str[:temp_match.start()].strip()
    else:
        temp = "?"
        desc = weather_str.strip()
    return {"temp": temp, "desc": desc, "city": city, "humidity": "?", "wind": "?"}


def get_time_of_day() -> str:
    """获取北京时间时段（兼容旧接口）"""
    h = (datetime.now(timezone.utc) + timedelta(hours=8)).hour
    if 5 <= h < 9: return "清晨/早晨"
    elif 9 <= h < 12: return "上午"
    elif 12 <= h < 14: return "中午"
    elif 14 <= h < 18: return "下午"
    elif 18 <= h < 21: return "傍晚"
    elif 21 <= h < 24: return "夜晚"
    else: return "深夜"


def get_weather_description(role_id: str) -> str:
    """获取角色的天气描述（带城市中文名）"""
    city = ROLE_CITIES.get(role_id, "Beijing")
    weather = _get_weather_detail(city)
    locale = get_locale(role_id)
    city_cn = locale.get("city_cn", city) if locale else city
    if weather:
        return "你所在的城市" + city_cn + "现在是" + weather["desc"] + "，" + weather["temp"] + "\u00b0C"
    return ""


def get_environment_context(role_id: str) -> str:
    """获取完整的环境上下文（地域化天气+时间），用于注入system_prompt"""
    city = ROLE_CITIES.get(role_id, "Beijing")
    weather = _get_weather_detail(city)
    locale = get_locale(role_id)
    city_cn = locale.get("city_cn", city) if locale else city

    # 使用角色所在时区的本地时间
    local_time_str = get_local_time(role_id) or ("北京时间 " + get_time_of_day())

    parts = ["[当前时间: " + local_time_str + "]"]
    if weather:
        parts.append("[天气: " + city_cn + " " + weather["desc"] + " " + weather["temp"] + "\u00b0C]")

    return " ".join(parts)
