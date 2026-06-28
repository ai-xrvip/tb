"""
角色城市映射表 —— 为每个角色定义所在城市，用于天气查询
供 environment.py 和 prompt_template.py 共用
"""
import time as _time
import urllib.request as _urllib

ROLE_CITIES: dict[str, str] = {
    "xiaolu": "Chengdu", "linxi": "Shanghai", "mia": "Los+Angeles", "sunian": "Hangzhou",
    "yuki": "Suzhou", "reina": "Tokyo", "chiyo": "Qingdao", "nana": "Changsha",
    "mizuki": "Shenzhen", "akari": "Chongqing", "yuna": "Guangzhou", "shiori": "Nanjing",
    "sora": "Xiamen", "kaede": "Wuhan", "ruri": "Beijing", "ren": "Kunming",
    "hana": "Dali", "mai": "Xi'an", "momo": "Taipei", "sakura": "Harbin",
    "aya": "Tianjin", "mei": "Chengdu", "koharu": "Lhasa", "tsubaki": "Lanzhou",
    "rio": "Zhuhai", "nozomi": "Hong+Kong", "nami": "Sanya", "fumi": "Jinan",
    "eri": "Silicon+Valley", "yui": "Shenyang",
}

_weather_cache: dict[str, str] = {}
_weather_cache_time: float = 0
WEATHER_API = "https://wttr.in/{city}?format=%C+%t"


def get_weather_str(city: str) -> str:
    """Fetch weather string for a city, with 30-min cache."""
    global _weather_cache, _weather_cache_time
    now = _time.time()
    if city in _weather_cache and now - _weather_cache_time < 1800:
        return _weather_cache[city]
    try:
        url = WEATHER_API.format(city=city)
        req = _urllib.Request(url, headers={"User-Agent": "curl/8.0"})
        with _urllib.urlopen(req, timeout=8) as resp:
            result = resp.read().decode("utf-8").strip()
            _weather_cache[city] = result
            _weather_cache_time = now
            return result
    except Exception:
        return ""
