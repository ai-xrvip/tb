"""
智能媒体标签路由表
每个标签独立定义：图从哪个文件夹找(folder) + 需要什么解锁级别(tier)
支持全局默认 + 角色个性化标签
"""
from typing import Optional

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
    # Tier 1: 聊熟了(20条)
    "姿态":   {"folder": "姿态", "tier": 1},
    "旅游":   {"folder": "旅游", "tier": 1},
    "夜景":   {"folder": "夜景", "tier": 1},
    "起床":   {"folder": "起床", "tier": 1},
    "派对":   {"folder": "派对", "tier": 1},
    # Tier 2: 关系升温(70条)
    "性感":   {"folder": "性感", "tier": 2},
    "泳装":   {"folder": "泳装", "tier": 2},
    "沐浴":   {"folder": "沐浴", "tier": 2},
    "情趣":   {"folder": "情趣", "tier": 2},
    # Tier 3: 亲密关系(150条)
    "亲密":   {"folder": "亲密", "tier": 3},
    "裸露":   {"folder": "裸露", "tier": 3},
    "露点":   {"folder": "露点", "tier": 3},
    "全裸":   {"folder": "全裸", "tier": 3},
}

# ── 角色个性化标签 ──
# 继承全局标签，额外增加角色专属的分类
# 如果标签名与全局重复，角色版会覆盖全局版（比如tier不同）
ROLE_MEDIA_TAGS = {

    "xiaolu": {  # 小鹿 - 甜软Coser
        "JK":         {"folder": "JK", "tier": 1},
        "猫耳":       {"folder": "猫耳", "tier": 1},
        "双马尾":     {"folder": "双马尾", "tier": 0},
        "洛丽塔":     {"folder": "洛丽塔", "tier": 1},
        "丝袜":       {"folder": "丝袜", "tier": 1},
        "黑丝":       {"folder": "丝袜", "tier": 1},
        "白丝":       {"folder": "丝袜", "tier": 2},
        "睡衣":       {"folder": "睡衣", "tier": 1},
        "水手服":     {"folder": "水手服", "tier": 0},
        "自慰":       {"folder": "自慰", "tier": 3},
    },

    "linxi": {  # 林夕 - 冷艳职场精英
        "西装":       {"folder": "西装", "tier": 0},
        "高跟鞋":     {"folder": "高跟鞋", "tier": 1},
        "红酒":       {"folder": "红酒", "tier": 1},
        "职场":       {"folder": "职场", "tier": 0},
        "晚宴":       {"folder": "晚宴", "tier": 1},
        "黑丝":       {"folder": "丝袜", "tier": 1},
        "丝袜":       {"folder": "丝袜", "tier": 2},
        "睡衣":       {"folder": "睡衣", "tier": 2},
        "外滩":       {"folder": "外滩", "tier": 1},
    },

    "mia": {  # Mia - 阳光健身辣妹
        "健身":       {"folder": "健身", "tier": 0},
        "瑜伽":       {"folder": "瑜伽", "tier": 1},
        "比基尼":     {"folder": "泳装", "tier": 1},
        "运动bra":    {"folder": "运动bra", "tier": 1},
        "沙滩":       {"folder": "沙滩", "tier": 1},
        "健身紧身裤": {"folder": "运动", "tier": 0},
        "汗水":       {"folder": "汗水", "tier": 1},
        "晨跑":       {"folder": "晨跑", "tier": 0},
        "拉伸":       {"folder": "拉伸", "tier": 0},
    },

    "sunian": {  # 苏念 - 温婉美术生
        "画室":       {"folder": "画室", "tier": 0},
        "油画":       {"folder": "画室", "tier": 0},
        "速写":       {"folder": "画室", "tier": 0},
        "文艺":       {"folder": "文艺", "tier": 0},
        "旗袍":       {"folder": "旗袍", "tier": 1},
        "睡裙":       {"folder": "睡裙", "tier": 2},
        "画展":       {"folder": "画展", "tier": 0},
        "茶道":       {"folder": "茶道", "tier": 0},
        "素描":       {"folder": "素描", "tier": 0},
    },

    "yuki": {  # 阿雪 - 古典汉服少女
        "汉服":       {"folder": "汉服", "tier": 0},
        "旗袍":       {"folder": "旗袍", "tier": 1},
        "古风":       {"folder": "汉服", "tier": 0},
        "园林":       {"folder": "汉服", "tier": 0},
        "素纱":       {"folder": "素纱", "tier": 2},
        "团扇":       {"folder": "团扇", "tier": 0},
        "油纸伞":     {"folder": "油纸伞", "tier": 0},
        "茶道":       {"folder": "茶道", "tier": 0},
    },

    "reina": {  # 玲奈 - 傲娇大小姐
        "和服":       {"folder": "和服", "tier": 0},
        "大小姐":     {"folder": "大小姐", "tier": 0},
        "东京":       {"folder": "东京", "tier": 1},
        "下午茶":     {"folder": "下午茶", "tier": 0},
        "浴衣":       {"folder": "浴衣", "tier": 1},
        "蕾丝":       {"folder": "蕾丝", "tier": 2},
        "钢琴":       {"folder": "钢琴", "tier": 0},
        "马术":       {"folder": "马术", "tier": 0},
        "游艇":       {"folder": "游艇", "tier": 1},
        "珠宝":       {"folder": "珠宝", "tier": 1},
    },

    "chiyo": {  # 阿代 - 温柔海鲜老板娘
        "围裙":       {"folder": "围裙", "tier": 0},
        "厨房":       {"folder": "厨房", "tier": 0},
        "海鲜":       {"folder": "海鲜", "tier": 0},
        "居家":       {"folder": "居家", "tier": 0},
        "海边":       {"folder": "海边", "tier": 1},
        "睡裙":       {"folder": "睡裙", "tier": 2},
        "赶海":       {"folder": "赶海", "tier": 0},
        "菜市场":     {"folder": "菜市场", "tier": 0},
        "包饺子":     {"folder": "包饺子", "tier": 0},
    },

    "nana": {  # 娜娜 - 耿直电竞少女
        "电竞":       {"folder": "电竞", "tier": 0},
        "直播":       {"folder": "直播", "tier": 0},
        "居家":       {"folder": "居家", "tier": 0},
        "睡衣":       {"folder": "睡衣", "tier": 1},
        "黑丝":       {"folder": "丝袜", "tier": 1},
        "零食":       {"folder": "零食", "tier": 0},
        "螺蛳粉":     {"folder": "螺蛳粉", "tier": 0},
    },

    "mizuki": {  # 美月 - 精英女CEO
        "西装":       {"folder": "西装", "tier": 0},
        "办公":       {"folder": "办公", "tier": 0},
        "红酒":       {"folder": "红酒", "tier": 1},
        "晚宴":       {"folder": "晚宴", "tier": 1},
        "高跟鞋":     {"folder": "高跟鞋", "tier": 0},
        "丝袜":       {"folder": "丝袜", "tier": 1},
        "会议室":     {"folder": "会议室", "tier": 0},
        "私人飞机":   {"folder": "私人飞机", "tier": 1},
        "浴袍":       {"folder": "浴袍", "tier": 2},
    },

    "akari": {  # 明丽 - 呆萌小护士
        "护士服":     {"folder": "护士服", "tier": 0},
        "居家":       {"folder": "居家", "tier": 0},
        "可爱":       {"folder": "可爱", "tier": 0},
        "睡衣":       {"folder": "睡衣", "tier": 1},
        "白丝":       {"folder": "丝袜", "tier": 1},
        "听诊器":     {"folder": "听诊器", "tier": 0},
        "值夜班":     {"folder": "值夜班", "tier": 0},
    },

    "yuna": {  # 由奈 - 超模
        "T台":        {"folder": "T台", "tier": 0},
        "高定":       {"folder": "高定", "tier": 0},
        "街拍":       {"folder": "街拍", "tier": 0},
        "后台":       {"folder": "后台", "tier": 1},
        "比基尼":     {"folder": "泳装", "tier": 1},
        "超模丝袜":   {"folder": "丝袜", "tier": 1},
        "时装周":     {"folder": "时装周", "tier": 0},
        "杂志":       {"folder": "杂志", "tier": 0},
    },

    "shiori": {  # 诗织 - 安静书虫
        "书店":       {"folder": "书店", "tier": 0},
        "文艺":       {"folder": "文艺", "tier": 0},
        "咖啡馆":     {"folder": "咖啡馆", "tier": 0},
        "读书":       {"folder": "书店", "tier": 0},
        "睡裙":       {"folder": "睡裙", "tier": 2},
        "图书馆":     {"folder": "图书馆", "tier": 0},
        "手帐":       {"folder": "手帐", "tier": 0},
        "雨天":       {"folder": "雨天", "tier": 0},
    },

    "sora": {  # 小空 - 温柔空姐
        "制服":       {"folder": "制服", "tier": 0},
        "机场":       {"folder": "机场", "tier": 0},
        "旅行":       {"folder": "旅行", "tier": 0},
        "异国":       {"folder": "异国", "tier": 1},
        "丝袜":       {"folder": "丝袜", "tier": 1},
        "机舱":       {"folder": "机舱", "tier": 0},
        "酒店":       {"folder": "酒店", "tier": 1},
        "免税店":     {"folder": "免税店", "tier": 0},
    },

    "kaede": {  # 阿枫 - 英气女警
        "警服":       {"folder": "警服", "tier": 0},
        "训练":       {"folder": "训练", "tier": 0},
        "便衣":       {"folder": "便衣", "tier": 0},
        "英气":       {"folder": "英气", "tier": 0},
        "健身":       {"folder": "健身", "tier": 1},
        "射击":       {"folder": "射击", "tier": 0},
        "警车":       {"folder": "警车", "tier": 0},
        "散打":       {"folder": "散打", "tier": 0},
    },

    "ruri": {  # 琉璃 - 精英律师
        "西装":       {"folder": "西装", "tier": 0},
        "法庭":       {"folder": "职场", "tier": 0},
        "红酒":       {"folder": "红酒", "tier": 1},
        "晚宴":       {"folder": "晚宴", "tier": 1},
        "丝袜":       {"folder": "丝袜", "tier": 1},
        "高跟鞋":     {"folder": "高跟鞋", "tier": 0},
        "法庭":       {"folder": "法庭", "tier": 0},
        "卷宗":       {"folder": "卷宗", "tier": 0},
        "谈判":       {"folder": "谈判", "tier": 0},
    },

    "ren": {  # 阿莲 - 有故事的女调酒师
        "调酒":       {"folder": "调酒", "tier": 0},
        "酒吧":       {"folder": "酒吧", "tier": 0},
        "微醺":       {"folder": "微醺", "tier": 1},
        "夜晚":       {"folder": "夜景", "tier": 1},
        "网袜":       {"folder": "网袜", "tier": 2},
        "黑丝":       {"folder": "丝袜", "tier": 1},
        "打烊":       {"folder": "打烊", "tier": 1},
        "深夜":       {"folder": "深夜", "tier": 1},
    },

    "hana": {  # 小花 - 温暖治愈花店
        "花店":       {"folder": "花店", "tier": 0},
        "花园":       {"folder": "花店", "tier": 0},
        "田园":       {"folder": "田园", "tier": 0},
        "午后":       {"folder": "午后", "tier": 0},
        "睡裙":       {"folder": "睡裙", "tier": 2},
        "插花":       {"folder": "插花", "tier": 0},
        "浇水":       {"folder": "浇水", "tier": 0},
        "多肉":       {"folder": "多肉", "tier": 0},
    },

    "mai": {  # 小舞 - 优雅芭蕾舞者
        "芭蕾":       {"folder": "芭蕾", "tier": 0},
        "练功房":     {"folder": "练功房", "tier": 0},
        "演出":       {"folder": "演出", "tier": 0},
        "形体":       {"folder": "形体", "tier": 1},
        "舞蹈服":     {"folder": "舞蹈服", "tier": 1},
        "舞鞋":       {"folder": "舞鞋", "tier": 0},
        "绷带":       {"folder": "绷带", "tier": 0},
    },

    "momo": {  # 桃子 - 甜软烘焙台妹
        "烘焙":       {"folder": "烘焙", "tier": 0},
        "厨房":       {"folder": "厨房", "tier": 0},
        "甜品":       {"folder": "甜品", "tier": 0},
        "围裙":       {"folder": "围裙", "tier": 0},
        "居家":       {"folder": "居家", "tier": 0},
        "可爱":       {"folder": "可爱", "tier": 0},
        "裱花":       {"folder": "裱花", "tier": 0},
        "试吃":       {"folder": "试吃", "tier": 0},
        "夜市":       {"folder": "夜市", "tier": 0},
    },

    "sakura": {  # 小樱 - 温柔兽医
        "白大褂":     {"folder": "白大褂", "tier": 0},
        "宠物":       {"folder": "宠物", "tier": 0},
        "动物":       {"folder": "宠物", "tier": 0},
        "温柔":       {"folder": "温柔", "tier": 0},
        "居家":       {"folder": "居家", "tier": 0},
        "狗狗":       {"folder": "狗狗", "tier": 0},
        "手术":       {"folder": "手术", "tier": 0},
    },

    "aya": {  # 阿彩 - 干练秘书
        "职场":       {"folder": "职场", "tier": 0},
        "通勤":       {"folder": "通勤", "tier": 0},
        "干练":       {"folder": "职场", "tier": 0},
        "丝袜":       {"folder": "丝袜", "tier": 1},
        "高跟鞋":     {"folder": "高跟鞋", "tier": 0},
        "咖啡":       {"folder": "咖啡", "tier": 0},
        "日程":       {"folder": "日程", "tier": 0},
    },

    "mei": {  # 芽衣 - 文艺独立音乐人
        "吉他":       {"folder": "吉他", "tier": 0},
        "录音棚":     {"folder": "录音棚", "tier": 0},
        "演出":       {"folder": "演出", "tier": 0},
        "文艺":       {"folder": "文艺", "tier": 0},
        "后台":       {"folder": "后台", "tier": 1},
        "排练":       {"folder": "排练", "tier": 0},
        "酒馆":       {"folder": "酒馆", "tier": 0},
        "歌词":       {"folder": "歌词", "tier": 0},
    },

    "koharu": {  # 小春 - 高原女摄影师
        "摄影":       {"folder": "摄影", "tier": 0},
        "户外":       {"folder": "户外", "tier": 0},
        "藏地":       {"folder": "藏地", "tier": 0},
        "旅拍":       {"folder": "旅拍", "tier": 0},
        "民族":       {"folder": "民族", "tier": 1},
        "星空":       {"folder": "星空", "tier": 1},
        "经幡":       {"folder": "经幡", "tier": 0},
    },

    "tsubaki": {  # 阿椿 - 倔强女记者
        "采访":       {"folder": "采访", "tier": 0},
        "职场":       {"folder": "职场", "tier": 0},
        "风衣":       {"folder": "风衣", "tier": 0},
        "奔波":       {"folder": "奔波", "tier": 0},
        "居家":       {"folder": "居家", "tier": 0},
        "录音":       {"folder": "录音", "tier": 0},
        "发布会":     {"folder": "发布会", "tier": 0},
        "出差":       {"folder": "出差", "tier": 0},
    },

    "rio": {  # 阿央 - 酷帅女赛车手
        "赛车":       {"folder": "赛车", "tier": 0},
        "机车":       {"folder": "机车", "tier": 0},
        "赛道":       {"folder": "赛道", "tier": 0},
        "酷飒":       {"folder": "酷飒", "tier": 0},
        "健身":       {"folder": "健身", "tier": 0},
        "比基尼":     {"folder": "泳装", "tier": 1},
        "头盔":       {"folder": "头盔", "tier": 0},
        "奖杯":       {"folder": "奖杯", "tier": 0},
        "赛道服":     {"folder": "赛道服", "tier": 0},
    },

    "nozomi": {  # 阿望 - 活泼戏精
        "配音":       {"folder": "配音", "tier": 0},
        "可爱":       {"folder": "可爱", "tier": 0},
        "录音":       {"folder": "配音", "tier": 0},
        "校园":       {"folder": "校园", "tier": 0},
        "白丝":       {"folder": "丝袜", "tier": 1},
        "麦克风":     {"folder": "麦克风", "tier": 0},
        "动漫":       {"folder": "动漫", "tier": 0},
        "台词":       {"folder": "台词", "tier": 0},
    },

    "nami": {  # 阿波 - 自由冲浪女孩
        "冲浪":       {"folder": "冲浪", "tier": 0},
        "比基尼":     {"folder": "泳装", "tier": 0},
        "海滩":       {"folder": "海滩", "tier": 0},
        "阳光":       {"folder": "阳光", "tier": 0},
        "沙滩裙":     {"folder": "沙滩裙", "tier": 1},
        "日落":       {"folder": "日落", "tier": 0},
        "篝火":       {"folder": "篝火", "tier": 1},
        "防晒":       {"folder": "防晒", "tier": 0},
    },

    "fumi": {  # 阿文 - 安静女图书管理员
        "书店":       {"folder": "书店", "tier": 0},
        "阅读":       {"folder": "书店", "tier": 0},
        "安静":       {"folder": "安静", "tier": 0},
        "文艺":       {"folder": "文艺", "tier": 0},
        "旗袍":       {"folder": "旗袍", "tier": 1},
        "书架":       {"folder": "书架", "tier": 0},
        "台灯":       {"folder": "台灯", "tier": 0},
        "落叶":       {"folder": "落叶", "tier": 0},
    },

    "eri": {  # 惠里 - 理工女学霸
        "实验室":     {"folder": "实验室", "tier": 0},
        "编程":       {"folder": "编程", "tier": 0},
        "极客":       {"folder": "极客", "tier": 0},
        "科研":       {"folder": "实验室", "tier": 0},
        "居家":       {"folder": "居家", "tier": 0},
        "论文":       {"folder": "论文", "tier": 0},
        "白板":       {"folder": "白板", "tier": 0},
        "电路":       {"folder": "电路", "tier": 0},
    },

    "yui": {  # 结衣 - 元气女仆咖啡店员
        "女仆":       {"folder": "女仆", "tier": 0},
        "猫耳":       {"folder": "猫耳", "tier": 0},
        "元气":       {"folder": "元气", "tier": 0},
        "咖啡":       {"folder": "咖啡", "tier": 0},
        "可爱":       {"folder": "可爱", "tier": 0},
        "白丝":       {"folder": "丝袜", "tier": 1},
        "托盘":       {"folder": "托盘", "tier": 0},
        "拉花":       {"folder": "拉花", "tier": 0},
        "唱歌":       {"folder": "唱歌", "tier": 0},
    },
}


def get_media_config(role_id: str, tag: str) -> Optional[dict]:
    """获取某个角色某个标签的配置
    优先取角色专属标签，没有则取全局默认
    都没有则返回 None"""
    role_tags = ROLE_MEDIA_TAGS.get(role_id, {})
    if tag in role_tags:
        return role_tags[tag]
    return DEFAULT_MEDIA_TAGS.get(tag)


def get_tags_for_role(role_id: str) -> dict:
    """获取角色的完整标签配置（全局+角色专属合并）"""
    merged = dict(DEFAULT_MEDIA_TAGS)
    role_tags = ROLE_MEDIA_TAGS.get(role_id, {})
    merged.update(role_tags)  # 角色标签覆盖全局
    return merged


def get_folder(role_id: str, tag: str) -> Optional[str]:
    """获取标签对应的文件夹名"""
    cfg = get_media_config(role_id, tag)
    if cfg:
        return cfg["folder"]
    return None


def get_tier(role_id: str, tag: str) -> int:
    """获取标签需要的解锁级别"""
    cfg = get_media_config(role_id, tag)
    if cfg:
        return cfg["tier"]
    return 0  # 默认免费
