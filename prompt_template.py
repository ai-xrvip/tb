"""
Prompt 模板引擎 —— 参考 Dify 的模板变量设计
支持在 system_prompt 中使用 {time} {weather} {user_name} {mood} {relationship} 等动态变量
每次请求前自动替换为实时值，让提示词管理从硬编码变成可配置
"""
import re
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

# 天气 API —— 用 wttr.in，不需要 API Key
WEATHER_API = "https://wttr.in/{city}?format=%C+%t+%h"


# 角色所在城市
from cities import ROLE_CITIES

# 天气缓存（每30分钟刷新）
_weather_cache: dict[str, str] = {}
_weather_cache_time: float = 0


def _get_weather_str(city: str) -> str:
    """获取城市天气描述字符串"""
    global _weather_cache, _weather_cache_time
    now = time.time()

    if city in _weather_cache and now - _weather_cache_time < 1800:
        return _weather_cache[city]

    try:
        import urllib.request
        url = WEATHER_API.format(city=city)
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = resp.read().decode("utf-8").strip()
            _weather_cache[city] = result
            _weather_cache_time = now
            return result
    except Exception:
        return ""


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
    """解析模板变量，替换为实时值

    支持的变量：
      {time}       - 当前时段（清晨/上午/下午/晚上/深夜）
      {date}       - 当前日期（2026年6月26日）
      {weekday}    - 星期几
      {weather}    - 角色所在城市天气
      {user_name}  - 用户名字
      {mood}       - 当前心情
      {relationship} - 关系等级
      {role_name}  - 角色名字
      {city}       - 角色所在城市名
    """
    role_id = kwargs.get("role_id", "xiaolu")
    user_name = kwargs.get("user_name", "宝贝")
    mood_str = kwargs.get("mood", "")
    rel_str = kwargs.get("relationship", "")
    role_name = kwargs.get("role_name", "")

    # 天气
    city = ROLE_CITIES.get(role_id, "Beijing")
    weather_str = _get_weather_str(city)

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
    return resolve_template(
        prompt,
        role_id=role_id,
        user_name=user_name,
        mood=mood_str,
        relationship=rel_str,
        role_name=role_name,
    )
