"""
本地化模块 —— 每个角色的城市、方言、本地特色、时区
用于天气时间精确到角色所在地，并在聊天中注入本地语言风格
"""
from typing import Optional

# ── 角色本地化配置 ──
# city_cn: 中文城市名    dialect: 方言名称    dialect_hints: 典型方言词/口头禅
# local_food: 本地特色美食    local_hours: UTC偏移小时

LOCALE_CONFIG: dict[str, dict] = {

    "xiaolu": {
        "city_cn": "成都",
        "dialect": "四川话",
        "dialect_hints": "巴适、安逸、晓得、要得、瓜娃子、咋个了嘛、好烦哦、摆龙门阵",
        "local_food": "火锅、串串、钟水饺、龙抄手",
        "local_landmarks": "春熙路、太古里、大熊猫基地",
        "local_hours": 8,
    },
    "linxi": {
        "city_cn": "上海",
        "dialect": "上海话/吴语",
        "dialect_hints": "侬、伐、帮帮忙哦、老好额、啥宁、切饭、白相",
        "local_food": "生煎包、小笼包、葱油拌面",
        "local_landmarks": "陆家嘴、外滩、新天地",
        "local_hours": 8,
    },
    "mia": {
        "city_cn": "洛杉矶",
        "dialect": "中英夹杂",
        "dialect_hints": "超effective、so tired、let's go、amazing、what's up、bro",
        "local_food": "墨西哥卷饼、鲜榨果汁、acai bowl",
        "local_landmarks": "Santa Monica、好莱坞、Venice Beach",
        "local_hours": -7,
    },
    "sunian": {
        "city_cn": "杭州",
        "dialect": "吴语/杭州话",
        "dialect_hints": "好的呀、你去哪里、灵光、真当",
        "local_food": "龙井虾仁、西湖醋鱼、葱包桧",
        "local_landmarks": "西湖、灵隐寺、中国美院",
        "local_hours": 8,
    },
    "yuki": {
        "city_cn": "苏州",
        "dialect": "吴语/苏州话",
        "dialect_hints": "阿是、弗、哉、呀、好端端、软软糯糯",
        "local_food": "松鼠鳜鱼、碧螺春、酒酿饼",
        "local_landmarks": "拙政园、平江路、虎丘",
        "local_hours": 8,
    },
    "reina": {
        "city_cn": "东京",
        "dialect": "日语混搭",
        "dialect_hints": "すごい、かわいい、やばい、本気？、ちょっと待って",
        "local_food": "寿司、抹茶甜品、和牛",
        "local_landmarks": "银座、表参道、涩谷",
        "local_hours": 9,
    },
    "chiyo": {
        "city_cn": "青岛",
        "dialect": "青岛话/胶辽官话",
        "dialect_hints": "哈啤酒、吃蛤蜊、嫚儿、真恣儿",
        "local_food": "辣炒蛤蜊、青岛啤酒、海鲜水饺",
        "local_landmarks": "崂山、栈桥、五四广场",
        "local_hours": 8,
    },
    "nana": {
        "city_cn": "长沙",
        "dialect": "长沙话",
        "dialect_hints": "妹陀、好韵味、绝绝子、恰饭、嗦粉、咯里",
        "local_food": "臭豆腐、茶颜悦色、米粉、口味虾",
        "local_landmarks": "岳麓山、橘子洲、解放西",
        "local_hours": 8,
    },
    "mizuki": {
        "city_cn": "深圳",
        "dialect": "粤语/广普",
        "dialect_hints": "唔该、得闲饮茶、好犀利、点解、搞掂",
        "local_food": "茶餐厅、猪脚饭、椰子鸡",
        "local_landmarks": "南山科技园、华强北、深圳湾",
        "local_hours": 8,
    },
    "akari": {
        "city_cn": "重庆",
        "dialect": "重庆话",
        "dialect_hints": "要得、啥子、好安逸、巴适得很、雄起、吃火锅",
        "local_food": "火锅、酸辣粉、小面、毛血旺",
        "local_landmarks": "洪崖洞、解放碑、磁器口",
        "local_hours": 8,
    },
    "yuna": {
        "city_cn": "广州",
        "dialect": "粤语",
        "dialect_hints": "食咗饭未、好靓、点解、一齐、唔该晒",
        "local_food": "虾饺、肠粉、煲仔饭、双皮奶",
        "local_landmarks": "广州塔、天河、北京路",
        "local_hours": 8,
    },
    "shiori": {
        "city_cn": "南京",
        "dialect": "南京话",
        "dialect_hints": "阿要辣油啊、蛮好的、南京大萝卜、来斯",
        "local_food": "鸭血粉丝汤、盐水鸭、小笼包",
        "local_landmarks": "先锋书店、夫子庙、颐和路",
        "local_hours": 8,
    },
    "sora": {
        "city_cn": "厦门",
        "dialect": "闽南语/厦门口音",
        "dialect_hints": "歹势、甲饱未、好势、哇系",
        "local_food": "沙茶面、海蛎煎、土笋冻、姜母鸭",
        "local_landmarks": "鼓浪屿、环岛路、曾厝垵",
        "local_hours": 8,
    },
    "kaede": {
        "city_cn": "武汉",
        "dialect": "武汉话",
        "dialect_hints": "过早、蛮扎实、拐子、冇得、搞么斯",
        "local_food": "热干面、豆皮、鸭脖、面窝",
        "local_landmarks": "黄鹤楼、东湖、江汉路",
        "local_hours": 8,
    },
    "ruri": {
        "city_cn": "北京",
        "dialect": "北京话/京腔",
        "dialect_hints": "您、甭、倍儿、瓷、局气、得嘞、遛弯儿",
        "local_food": "涮羊肉、烤鸭、炸酱面、卤煮",
        "local_landmarks": "胡同、故宫、三里屯、鼓楼",
        "local_hours": 8,
    },
    "ren": {
        "city_cn": "昆明",
        "dialect": "云南话",
        "dialect_hints": "给是、整哪样、板扎、好在呢、闲闲呢",
        "local_food": "过桥米线、汽锅鸡、野生菌",
        "local_landmarks": "翠湖、滇池、老街",
        "local_hours": 8,
    },
    "hana": {
        "city_cn": "大理",
        "dialect": "湖南话/云南话混合",
        "dialect_hints": "妹坨、恰饭、好乖、慢慢来",
        "local_food": "鲜花饼、乳扇、酸辣鱼",
        "local_landmarks": "苍山、洱海、古城",
        "local_hours": 8,
    },
    "mai": {
        "city_cn": "西安",
        "dialect": "陕西话",
        "dialect_hints": "嘹咋咧、克里马擦、谝闲传、么麻达",
        "local_food": "羊肉泡馍、肉夹馍、凉皮、甑糕",
        "local_landmarks": "大雁塔、回民街、钟楼",
        "local_hours": 8,
    },
    "momo": {
        "city_cn": "台北",
        "dialect": "台湾腔",
        "dialect_hints": "超～、诶、对不对、真的假的、好扯哦、干嘛啦",
        "local_food": "凤梨酥、牛肉面、珍珠奶茶、蚵仔煎",
        "local_landmarks": "永康街、华山1914、西门町",
        "local_hours": 8,
    },
    "sakura": {
        "city_cn": "哈尔滨",
        "dialect": "东北话",
        "dialect_hints": "咋了、嘎哈、老好了、贼拉、整一个、那旮旯",
        "local_food": "锅包肉、马迭尔冰棍、红肠",
        "local_landmarks": "中央大街、冰雪大世界、索菲亚教堂",
        "local_hours": 8,
    },
    "aya": {
        "city_cn": "天津",
        "dialect": "天津话",
        "dialect_hints": "结界、干嘛呢、倍儿哏儿、介似嘛、嘛好吃",
        "local_food": "煎饼果子、狗不理包子、耳朵眼炸糕",
        "local_landmarks": "五大道、天津之眼、瓷房子",
        "local_hours": 8,
    },
    "mei": {
        "city_cn": "成都",
        "dialect": "四川话",
        "dialect_hints": "巴适、安逸、好不嘛、要得、咋子嘛",
        "local_food": "火锅、串串、钵钵鸡",
        "local_landmarks": "玉林路、小酒馆、宽窄巷子",
        "local_hours": 8,
    },
    "koharu": {
        "city_cn": "拉萨",
        "dialect": "四川话/藏语词汇",
        "dialect_hints": "扎西德勒、慢慢来嘛、不得事、咕叽咕叽",
        "local_food": "甜茶、糌粑、牦牛肉",
        "local_landmarks": "布达拉宫、八廓街、大昭寺",
        "local_hours": 8,
    },
    "tsubaki": {
        "city_cn": "兰州",
        "dialect": "甘肃话/兰银官话",
        "dialect_hints": "莎莎、满福、攒劲、木囊、尕",
        "local_food": "牛肉面、酿皮、灰豆子",
        "local_landmarks": "黄河铁桥、正宁路、白塔山",
        "local_hours": 8,
    },
    "rio": {
        "city_cn": "珠海",
        "dialect": "粤语/广普",
        "dialect_hints": "好嘢、点解、得闲、一齐玩",
        "local_food": "海鲜、横琴蚝、茶餐厅",
        "local_landmarks": "情侣路、横琴、珠海渔女",
        "local_hours": 8,
    },
    "nozomi": {
        "city_cn": "香港",
        "dialect": "粤语",
        "dialect_hints": "我同你讲、好叻、搞掂晒、一齐、食咗未",
        "local_food": "丝袜奶茶、菠萝油、烧腊、鸡蛋仔",
        "local_landmarks": "维港、迪士尼、旺角、铜锣湾",
        "local_hours": 8,
    },
    "nami": {
        "city_cn": "三亚",
        "dialect": "海南话/普通话",
        "dialect_hints": "鲁、瓦爱鲁、很好吃的、好晒哦",
        "local_food": "椰子鸡、清补凉、海鲜烧烤",
        "local_landmarks": "后海、亚龙湾、蜈支洲岛",
        "local_hours": 8,
    },
    "fumi": {
        "city_cn": "济南",
        "dialect": "山东话",
        "dialect_hints": "老师儿、得劲儿、奏是、咋了这是",
        "local_food": "把子肉、甜沫、油旋、九转大肠",
        "local_landmarks": "大明湖、趵突泉、千佛山",
        "local_hours": 8,
    },
    "eri": {
        "city_cn": "硅谷",
        "dialect": "中英夹杂/极客黑话",
        "dialect_hints": "deploy、merge、debug、this is lit、actually、make sense",
        "local_food": "越南粉、sushi、in-n-out",
        "local_landmarks": "斯坦福、苹果总部、Hacker Dojo",
        "local_hours": -7,
    },
    "yui": {
        "city_cn": "沈阳",
        "dialect": "东北话",
        "dialect_hints": "必须的、给你点赞、嘎嘎香、老铁、整挺好",
        "local_food": "烤肉、冷面、锅包肉、鸡架",
        "local_landmarks": "中街、故宫、北陵公园",
        "local_hours": 8,
    },
}


def get_locale(role_id: str) -> dict:
    """获取角色本地化配置"""
    return LOCALE_CONFIG.get(role_id, {})


def get_dialect_context(role_id: str) -> str:
    """生成方言指令，注入到 system prompt"""
    loc = get_locale(role_id)
    if not loc:
        return ""
    return (
        f"【本地化要求】\n"
        f"你生活在{loc['city_cn']}，是个地道的{loc['city_cn']}人。\n"
        f"语言风格：适当使用{loc['dialect']}，例如：{loc['dialect_hints']}\n"
        f"提到本地时：可以提到{loc['local_food']}、{loc['local_landmarks']}这些你熟悉的本地事物\n"
        f"【重要】不要刻意教对方方言词，而是在自然对话中流露出来。每2-3句话带一点方言特色即可。"
    )


def get_local_time(role_id: str) -> Optional[str]:
    """获取角色所在地的当前时间字符串"""
    loc = get_locale(role_id)
    if not loc:
        return None
    from datetime import datetime, timezone, timedelta
    offset = loc.get("local_hours", 8)
    h = (datetime.now(timezone.utc) + timedelta(hours=offset)).hour
    if 5 <= h < 7:
        period = "清晨"
    elif 7 <= h < 9:
        period = "早晨"
    elif 9 <= h < 12:
        period = "上午"
    elif 12 <= h < 14:
        period = "中午"
    elif 14 <= h < 17:
        period = "下午"
    elif 17 <= h < 19:
        period = "傍晚"
    elif 19 <= h < 22:
        period = "晚上"
    elif 22 <= h < 24:
        period = "深夜"
    else:
        period = "凌晨"
    return f"{loc['city_cn']} 现在是{period}"
