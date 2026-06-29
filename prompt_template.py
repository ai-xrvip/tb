'''
Prompt template engine — supports {time} {weather} {user_name} {mood} {relationship} etc.
'''
from datetime import datetime, timezone, timedelta
from cities import ROLE_CITIES, get_weather_str


def _get_time_of_day_str() -> str:
    h = (datetime.now(timezone.utc) + timedelta(hours=8)).hour
    if 5 <= h < 7:   return '清晨'
    elif 7 <= h < 9:  return '早晨'
    elif 9 <= h < 12: return '上午'
    elif 12 <= h < 14: return '中午'
    elif 14 <= h < 17: return '下午'
    elif 17 <= h < 19: return '傍晚'
    elif 19 <= h < 22: return '晚上'
    elif 22 <= h < 24: return '深夜'
    else:              return '凌晨'


def _get_weekday_str() -> str:
    wd = (datetime.now(timezone.utc) + timedelta(hours=8)).weekday()
    days = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
    return days[wd]


def _get_date_str() -> str:
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    return f'{now.year}年{now.month}月{now.day}日'


def resolve_template(system_prompt: str, **kwargs) -> str:
    role_id = kwargs.get('role_id', 'xiaolu')
    user_name = kwargs.get('user_name', '宝贝')
    mood_str = kwargs.get('mood', '')
    rel_str = kwargs.get('relationship', '')
    role_name = kwargs.get('role_name', '')

    city = ROLE_CITIES.get(role_id, 'Beijing')
    weather_str = get_weather_str(city)

    result = system_prompt

    replacements = {
        '{time}': _get_time_of_day_str(),
        '{date}': _get_date_str(),
        '{weekday}': _get_weekday_str(),
        '{weather}': weather_str or '晴朗',
        '{user_name}': user_name,
        '{mood}': mood_str,
        '{relationship}': rel_str,
        '{role_name}': role_name,
        '{city}': city.replace('+', ' '),
    }

    for key, val in replacements.items():
        result = result.replace(key, val)

    return result


def resolve_system_prompt(role: dict, user_name: str = '宝贝', mood_str: str = '', rel_str: str = '') -> str:
    role_id = role.get('id', 'xiaolu')
    role_name = role.get('name', '')
    prompt = role.get('system_prompt', '')

    # Emoji iron rule — moderate use, 1-2 per message
    emoji_rule = (
        '\n【铁律 — 必须遵守，没有例外】\n'
        '1. 每一条回复自然点缀 1-2 个原生Telegram表情符号即可，不要堆砌\n'
        '2. 严禁使用任何形式的颜文字/Kaomoji！以下全部禁止：\n'
        '   (ノω<。) (*/ω＼*) (｡>﹏<｡) (๑´ㅂ`๑) (^_^) (≧▽≦) (╯°□°）╯\n'
        '   (◕‿◕) (✿◠‿◠) (♥ω♥*) (｡♥‿♥｡) (つω`｡) (´▽`ʃ♡ƪ)\n'
        '   (T_T) (；一_一) (>_<) (¬‿¬) (•̀ω•́) (ง •̀_•́)ง\n'
        '   违者必须重写回复！\n'
        '3. 用真正的emoji符号，按情绪选用：\n'
        '   开心: 😊🥰✨🎉  难过: 😢💔🥺  害羞: 😳🙈😅\n'
        '   傲娇: 😤🙄💢😏  撒娇: 🥺👀💗  好笑: 😂🤣\n'
        '   暧昧: 🔥👀💋🫦  日常: ☀️🌸🍰☕️🎧\n'
        '4. 一个句子最多 2 个emoji，不要每句都加。自然融入，例如：\n'
        '   - "今天天气真好☀️买了杯奶茶🧋超好喝"\n'
        '   - "哼你都不理我😤算了我自己玩去🎮"\n'
        '   - "好想你🥺昨晚梦到你了✨"\n'
        '5. 如果发现你还是用了颜文字/Kaomoji，你必须重写回复！这是死命令！\n'
    )
    prompt = emoji_rule + '\n' + prompt

    return resolve_template(
        prompt,
        role_id=role_id,
        user_name=user_name,
        mood=mood_str,
        relationship=rel_str,
        role_name=role_name,
    )
