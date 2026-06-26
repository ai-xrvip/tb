"""
天气/心情感知模块 —— 获取当前天气和时间信息，注入到 AI prompt
"""
import os
import time
import json
import requests
from datetime import datetime
from typing import Optional


# 天气 API（用 wttr.in，不需要 API Key）
WEATHER_API = "https://wttr.in/{city}?format=j1"


# 角色所在城市
from cities import ROLE_CITIES

# 天气缓存（每30分钟刷新一次）
_weather_cache: dict[str, dict] = {}
_weather_cache_time: float = 0


def _get_weather(city: str) -> Optional[dict]:
    """获取城市天气"""
    global _weather_cache, _weather_cache_time
    now = time.time()

    # 缓存30分钟
    if city in _weather_cache and now - _weather_cache_time < 1800:
        return _weather_cache[city]

    try:
        resp = requests.get(
            WEATHER_API.format(city=city),
            timeout=10,
            headers={"User-Agent": "curl/8.0"}
        )
        if resp.status_code == 200:
            data = resp.json()
            current = data.get("current_condition", [{}])[0]
            result = {
                "temp": current.get("temp_C", "?"),
                "desc": current.get("weatherDesc", [{}])[0].get("value", "晴"),
                "humidity": current.get("humidity", "?"),
                "wind": current.get("windspeedKmph", "?"),
                "city": city,
            }
            _weather_cache[city] = result
            _weather_cache_time = now
            return result
    except Exception as e:
        logger.debug(f"Weather fetch failed: {e}")
    return None


def get_time_of_day() -> str:
    """获取时段描述"""
    h = datetime.now().hour
    if 5 <= h < 9: return "清晨/早晨"
    elif 9 <= h < 12: return "上午"
    elif 12 <= h < 14: return "中午"
    elif 14 <= h < 18: return "下午"
    elif 18 <= h < 21: return "傍晚"
    elif 21 <= h < 24: return "夜晚"
    else: return "深夜"


def get_weather_description(role_id: str) -> str:
    """获取角色的天气描述"""
    city = ROLE_CITIES.get(role_id, "北京")
    weather = _get_weather(city)
    if weather:
        return f"你所在的城市{weather['city']}现在是{weather['desc']}，{weather['temp']}°C"
    return ""


def get_environment_context(role_id: str) -> str:
    """获取完整的环境上下文（天气+时间），用于注入system_prompt"""
    city = ROLE_CITIES.get(role_id, "北京")
    weather = _get_weather(city)
    time_str = get_time_of_day()

    parts = [f"[当前时间: {time_str}]"]
    if weather:
        parts.append(f"[天气: {weather['city']} {weather['desc']} {weather['temp']}°C]")

    return " ".join(parts)
