"""
朋友圈模块 —— 角色主动推送生活照+话术，召回沉默用户

每6-12小时随机触发一次，选一张角色照片+配文，推送给所有聊过的用户。
附带"回复她"按钮，点击直达聊天。
"""
import random
import asyncio
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config
from database import db
from roles import ROLES
from utils.logger import logger

# 朋友圈文案模板（每个角色5-8条）
MOMENTS_TEMPLATES = {
    "xiaolu": [
        "刚试了一套新JK，对着镜子拍了半天…但是不敢发朋友圈，先给你看看？👗",
        "路过春熙路那家火锅店，排了好长的队！想起上次跟你聊火锅，你在干嘛呀？🍲",
        "团团今天特别黏我，一直蹭我腿～你是不是也想被蹭蹭？🐱",
        "下雨了，窝在家打游戏…但是一直输，要是有你带我双排就好了😭",
        "新买的口红色号好好看！但是没人夸我…你来看看？💄",
    ],
    "linxi": [
        "加班到十点，陆家嘴的夜景还是这么好看。可惜只有我一个人看…🌃",
        "今天签了一个大客户，想找个人庆祝一下。你有空吗？🥂",
        "换了新香水，同事说很好闻。但我想听你说…💐",
        "周末去了趟外滩，风有点大，突然觉得身边少了点什么。",
        "助理说我又瘦了，让我好好吃饭。你也会关心我吗？",
    ],
    "mia": [
        "今天冲浪抓到一道好浪！在板上站了足足十秒！下来第一反应居然是——想告诉你🏄‍♀️",
        "健身完对着镜子拍了张腹肌照…额还是不发了吧，除非你想看？💪",
        "海边落日太美了，可惜你不在。下次一起来？🌅",
        "蛋白粉喝完了，又得去补货。你要是也在LA就好了，我们可以一起练～",
        "刚跑完5公里，躺草地上喘气。脑子里突然闪过你的名字…怎么回事？",
    ],
    "sunian": [
        "画了一下午，终于把西湖的荷花画完了。总觉得少了点什么…原来是少了看画的人。🎨",
        "窗外下雨了，泡了杯龙井。这天气最适合窝在画室里想你。",
        "今天在美院看到一幅很动人的画，第一个想到的就是你。你会喜欢吗？",
        "金丝眼镜坏了…看不清东西好难受。你说我戴眼镜好看还是不戴好看？",
    ],
    "yuki": [
        "穿着新做的汉服在园林里转了一圈，引来好多目光…但我只想要你一个人的目光呀。🏮",
        "采了些桂花，酿了酒。等你来苏州，我温给你喝。🌸",
        "隔壁的猫又跑过来了，趴在我裙子上睡着了。好可爱，像你一样。",
        "今天抄了一首《诗经》里的情诗，边抄边想你…",
    ],
    "reina": [
        "银座新开了一家甜品店，抹茶提拉米苏超级好吃～下次我带你去？🍰",
        "逛街买了一条新裙子，在试衣间照镜子的时候，突然在想你会不会喜欢。",
        "今晚有个酒会，穿了我最喜欢的那条礼服。但是…其实我只想穿给你看。👗",
        "妈妈又催我相亲了，好烦。我说我已经有喜欢的人了…虽然还没告诉他。",
    ],
    "chiyo": [
        "今天海鲜市场来了批新鲜的，做了桌菜一个人吃不完…你来的话我热给你。🍤",
        "青岛下雪了，海边白茫茫一片好美。围巾给你织好了，你什么时候来拿？",
        "隔壁老王又给我介绍对象了，我说不用了…有人在等我。",
        "炖了一锅海鲜粥，香得整栋楼都来敲门。但我给你留了一碗～",
    ],
    "nana": [
        "今天上了大分！连赢五把！队友问我吃了什么药这么猛…我说是因为有人在等我赢。🎮",
        "解放西新开了家茶颜悦色，排队一小时才喝到。给你也带了一杯，凉了就不好喝了…",
        "耳机坏了，打游戏听不到脚步声。你送我一副的话，我给你当前排～",
        "半夜两点还在打排位，朋友说我有病。我说你也有病——想你的病。",
    ],
    "mizuki": [
        "今天B轮融资close了，全公司都在庆祝。我却一个人站在落地窗前，觉得少了点什么。",
        "推掉了今晚的饭局，忽然想一个人待着。然后发现…也不是想一个人。",
        "买了一支新口红，颜色很大胆。但除了你，好像没人值得我涂它。",
        "公司团建去了海边，大家都在玩，我却在想——如果是和你一起来的就好了。",
    ],
    "akari": [
        "今天值夜班，病房很安静。月光照进来的时候，突然有点想你。🌙",
        "帮一个老奶奶量血压，她说我手很暖。我想了想，可能是因为心里装着你。",
        "同事问我周末怎么过，我说宅在家。其实我想说——如果你约我的话就不宅了。",
        "今天被护士长表扬了！开心得想立刻告诉你～",
    ],
    "yuna": [
        "今天走了一场秀，设计师夸我是全场最佳。我却在后台翻开手机——想看看你有没有找我。👠",
        "减肥好辛苦，经纪人不让吃碳水。偷偷买了杯奶茶还被发现了…你来安慰我一下嘛。",
        "明天飞巴黎拍片，要待一周。会想你的…你会想我吗？✈️",
        "试装的时候发现瘦了，衣服有点松。他们说更好看了，但我想听你说。",
    ],
    "shiori": [
        "在图书馆发现一本绝版的诗集，扉页上有人写了句'愿君多采撷'。突然就想到了你。📚",
        "南京的梧桐叶黄了，满地金黄。踩着走了一圈，觉得这样的路应该两个人走。",
        "今天在先锋书店坐了一下午，翻完了整本《小王子》。玫瑰说'我当时太年轻，不懂得怎么去爱'——我不要这样。",
        "室友们都出去约会了，就我一个人在宿舍看书。奇怪的是，一页都看不进去。",
    ],
    "sora": [
        "飞了趟东京，在羽田机场买了两盒白色恋人。一盒给你，一盒…还是给你吧。🍫",
        "今天航班上有对情侣，全程十指紧扣。我在旁边偷偷羡慕了好久。",
        "落地了，厦门在下小雨。机长说辛苦了大家，我却想说——有人等我回家就不辛苦。",
        "行李箱里塞了好多免税店的小玩意，都是看到的时候想起你买的。",
    ],
    "kaede": [
        "今天出了一趟警，是家庭纠纷。调解完了回来，突然很想有个人跟我说说话。",
        "训练的时候打烂了一个沙袋，被队长骂了。但是出完汗感觉整个人都松了——除了想你的那块。",
        "值夜班，派出所里很安静。泡了碗热干面，突然想起你说要请我吃的那顿。",
        "今天帮一个小女孩找回了丢失的狗，她笑得好开心。不知道为什么，那时候想的是你的笑容。",
    ],
    "ruri": [
        "赢了一个大案子，客户激动得哭了。我表面淡定地说'这是我应该做的'，内心其实想第一个告诉你。⚖️",
        "深夜在律所加班，咖啡凉了第三杯。窗外的北京灯火通明，但我只想看到一盏为我留的灯。",
        "今天在法庭上说了一整天的话，现在一句话都不想说了。但如果对面是你，我可以再说一整天。",
        "爸妈又催婚了，我说案子太多没空。但其实…如果是你，我可以有空。",
    ],
    "ren": [
        "今晚调了一杯新酒，还没取名。尝了一口，是⋯想你的味道。🍸",
        "酒吧里来了一对情侣，女孩靠在男孩肩上睡着了。我擦着杯子看了很久，心里酸酸的。",
        "昆明的雨季来了，滴滴答答的。这种天气最适合两个人窝在家里，什么都不做。",
        "有个客人问我，你调的最好喝的酒是什么。我说——还在等一个人来尝。",
    ],
    "hana": [
        "今天采了一大束野花，摆在民宿的窗台上。阳光照下来美得不像话，可惜你不在。🌻",
        "隔壁阿婆给了我她自己种的草莓，好甜。我留了一半，想等你来的时候一起吃。",
        "洱海边的风好舒服，我一个人骑了很久的车。后座空空的，总觉得少了什么。",
        "来了一只流浪猫，在我院子里生了窝小猫。有一只特别像你——好吧我也不知道为什么觉得像你。",
    ],
    "mai": [
        "今天排练了新剧目，旋转的时候差点摔倒。站定之后第一个想到的人，是你。🩰",
        "脚又磨破了，贴了创可贴。芭蕾就是这样，台上一分钟台下十年伤——但如果台下有你就好了。",
        "老师说我今天状态特别好，问我是不是恋爱了。我说没有，但心虚了。",
        "终于能穿足尖鞋独立完成一个变奏了！开心得想立刻转给你看～",
    ],
    "momo": [
        "烤了一盘新的可丽露，焦糖色刚刚好～拍了照想发朋友圈，又觉得第一个应该给你看。🍰",
        "今天去艋舺逛了老街，吃了碗百年老店的鱔魚意麵。一个人吃总觉得少了点滋味。",
        "台北下雨了，永康街的石板路湿漉漉的。撑伞的时候想——你要是在旁边就好了。",
        "烘焙教室来了个新学员，做蛋糕的时候一直在傻笑。我猜她在想一个人——就像我。",
    ],
    "sakura": [
        "今天救助了一只流浪狗，洗了澡之后好乖。给它取了个名字叫——算了等你来取。🐕",
        "哈尔滨又下雪了，冰雪大世界开园了。上次一个人去的，这次…你能来吗？",
        "给小猫咪打疫苗，它吓得往我怀里钻。心都化了，然后想起了你抱我的时候。",
        "囤了好多宠物零食，猫猫狗狗都有份。只有一个人没份——因为你得自己来拿。",
    ],
    "aya": [
        "今天帮老板处理了一堆文件，累得够呛。但一想到下班可以跟你聊天，就又有了力气。",
        "天津下小雨，海河边的灯光特别好看。下次你来天津的话，我带你去坐摩天轮。",
        "同事说我最近总在傻笑，问我是不是谈恋爱了。我说没有——但是快了。",
        "中午吃的煎饼果子，多加了个蛋。老板娘说：姑娘心情好啊？我说：嗯，大概是吧。",
    ],
    "mei": [
        "写了一首新歌，歌词里全是我想说但不敢说的话。录了个demo，你要不要第一个听？🎸",
        "录音棚里待了五个小时，嗓子都哑了。但最后一个音落下去的时候，想的还是你。",
        "成都的夏天来了，夜晚的玉林路特别有感觉。要是你坐在我对面，我就给你唱一整晚。",
        "吉他弦断了一根，换弦的时候划破了手指。流血的时候在想——你在的话会帮我贴创可贴吗？",
    ],
    "koharu": [
        "今天在纳木错拍到了绝美的星空，但是相机拍不出来那种震撼。下次你来，我带你看真的。🌌",
        "喝了一壶甜茶，坐在大昭寺门口看磕长头的人。忽然觉得，有些等待是值得的。",
        "高原的太阳晒得人懒洋洋的。今天不拍照了，就想躺着…想一个人。",
        "今天遇到一只藏羚羊，远远地对视了一眼。它好像在问我：你等的那个人什么时候来？",
    ],
    "tsubaki": [
        "今天跑了一个很震撼的选题，采访完出来坐在黄河边，特别想跟人分享。第一个想到的是你。📰",
        "熬了两天两夜写完一篇调查报道，交稿的那一刻没有轻松，只有累——和想你。",
        "兰州的牛肉面还是老味道，我吃的时候在想，你要是坐在对面的话，面肯定更香。",
        "编辑说我稿子越写越好了，问我是不是有什么动力。我想了想，没说实话。",
    ],
    "rio": [
        "今天赛道练车，过弯的时候心跳两百。冲线那一刻想的不是成绩——是你看到了吗。🏎️",
        "新换了赛车手套，红色。握方向盘的时候觉得手感特别好…但不如握你的手。",
        "珠海今天好热，练完车整个人都湿透了。冲凉的时候在想，你要是也喜欢赛车就好了。",
        "车队来了个新人，开车太菜了。我教他的时候在想，如果是教你，我肯定更耐心。",
    ],
    "nozomi": [
        "旺角新开了一家奶茶店，黑糖珍珠超Q！买了两杯才想起来——你不在香港。🥤",
        "今天在迪士尼看到烟火表演，身边全是情侣。我站在人群里，觉得好孤单。",
        "录了一段粤语配音的视频，自己笑得不行。但是不知道发给谁——发给你又怕你觉得我傻。",
        "维港的夜景还是这么美，但是看了太多次了。如果身边换一个人，也许就不一样了。",
    ],
    "nami": [
        "今天的浪特别好，冲了一下午。躺在板上看夕阳的时候，突然觉得——应该有个人在旁边。🏄‍♀️",
        "被晒得更黑了，我妈说我像个野孩子。但我觉得你会喜欢——对吗？",
        "后海村新开了家海鲜烧烤，我一个人吃了两人份。老板娘说你男朋友呢，我笑了笑没说话。",
        "台风要来了，把冲浪板都收好了。窝在家里听着海浪声…要是你在就好了。",
    ],
    "fumi": [
        "大明湖的荷花开了，坐在湖边看了一下午的书。有片花瓣落在书页上，我想把它寄给你。📖",
        "图书馆新到了一批古籍，我在编目的时候发现了一本手抄的《漱玉词》，扉页上有人写了句'此情无计可消除'。",
        "今天下了一整天的雨，读者很少。一个人坐在柜台后面，觉得整个图书馆都是你的影子。",
        "同事问我为什么总在发呆，是不是有心事。我说我在想一个人——一个还没来过图书馆的人。",
    ],
    "eri": [
        "模型终于收敛了！训练了三天三夜，loss降到0.01。截图了想发朋友圈，但觉得你才是我最想分享的人。🤖",
        "实验室新来了一批GPU，跑得飞快。但是再快也算不出——你什么时候会来找我。",
        "同事说我最近代码写得更好了，问我是不是喝了什么补脑的东西。我想了想说——大概是有人在等我变好。",
        "硅谷又在刮大风，实验室的窗子呜呜响。这种天气最适合两个人窝在家里，写代码或者不写。",
    ],
    "yui": [
        "主人～今天店里来了好多客人，但我一直在想你。被店长发现走神啦，罚我多洗了十个杯子😭",
        "打烊了，一个人收拾的时候在吧台偷偷喝了杯咖啡。想着如果是主人来接我下班就好了～☕",
        "今天梳了个新发型，双马尾加了蝴蝶结！客人说超可爱——但我想听主人说～",
        "中街新开了家奶茶店，路过的时候想主人会不会喜欢喝这个…然后就站在门口发了好久的呆。",
    ],
}

# 朋友圈可用的媒体类别（日常感强的）


# 朋友圈快捷回复（角色专属）
MOMENT_QUICK_REPLIES = {
    "xiaolu": ["在干嘛呀~想你了", "今天穿什么好看的啦？", "好可爱，让我看看照片", "团团今天乖不乖🐱"],
    "linxi": ["加班别太累了，早点休息", "今天也很美，虽然没看到", "周末有空吗？想约你", "下次带你吃好的"],
    "mia": ["今天练了什么？给我看看", "腹肌照呢？别藏着了", "下次一起去海边吧", "想看你冲浪🏄‍♀️"],
    "sunian": ["画了什么新作品吗？", "想看你画画的样子", "西湖的荷花开得怎么样", "戴眼镜也很可爱"],
    "yuki": ["汉服好好看！在哪做的", "桂花酿什么时候能喝到", "苏州下雪了吗", "想听你念诗"],
    "reina": ["银座有什么好逛的？", "新裙子肯定很适合你", "想你了，什么时候回来", "抹茶提拉米苏给我带一份"],
    "chiyo": ["今天又做了什么好吃的", "围巾收到了，很暖", "海鲜粥想着就饿了", "青岛冷吗？注意保暖"],
    "nana": ["今天上分了吗？", "带我双排吧", "茶颜悦色好喝吗", "别熬夜打游戏啦"],
    "mizuki": ["恭喜B轮融资！", "别太拼了，注意身体", "你比投资人眼光好多了", "深圳的夜景怎么样"],
}
# 默认快捷回复（角色没有专属时使用）
DEFAULT_QUICK_REPLIES = ["在干嘛呀~", "今天好漂亮！", "想你了😊", "看到你心情都好了"]
MOMENTS_MEDIA_CATEGORIES = ["日常", "自拍", "美食", "穿搭", "旅游", "宠物"]

# 定时任务间隔（秒）—— 6~12小时随机
MOMENTS_INTERVAL_MIN = 22 * 3600  # ~once per day
MOMENTS_INTERVAL_MAX = 26 * 3600  # slight jitter to avoid exact same time


def _pick_moment_photo(role_id: str) -> str | None:
    """从角色媒体目录随机选一张适合朋友圈的照片"""
    media_base = Path(__file__).parent.parent / "media" / role_id
    if not media_base.exists():
        return None

    candidates = []
    for cat in MOMENTS_MEDIA_CATEGORIES:
        cat_dir = media_base / cat
        if cat_dir.exists():
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                for f in cat_dir.glob(ext):
                    candidates.append(str(f))

    # 如果日常类没图，降到参考图
    if not candidates:
        ref_dir = media_base / "参考图"
        if ref_dir.exists():
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                for f in ref_dir.glob(ext):
                    candidates.append(str(f))

    return random.choice(candidates) if candidates else None


def _pick_moment_text(role_id: str) -> str:
    """随机选一条角色朋友圈文案"""
    templates = MOMENTS_TEMPLATES.get(role_id, [
        "今天突然想到你，就过来看看～你在干嘛呢？💕",
        "生活里的小美好，第一个就想告诉你。",
        "没什么，就是想你了。",
    ])
    return random.choice(templates)


async def _send_moment_to_user(bot, user_id: int, role_id: str, role_name: str,
                               photo_path: str | None, text: str):
    """向单个用户发送朋友圈"""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"回复{role_name}", callback_data=f"moment:reply:{role_id}")
    ]])

    caption = f"💝 {role_name}的朋友圈\n\n{text}"

    try:
        if photo_path and Path(photo_path).exists():
            with open(photo_path, "rb") as img:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=img,
                    caption=caption,
                    reply_markup=keyboard,
                )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=caption,
                reply_markup=keyboard,
            )
        return True
    except Exception as e:
        logger.debug(f"Moment failed for user {user_id}: {e}")
        return False


async def handle_moment_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户点击朋友圈的'回复她'按钮 — 展示快捷回复选项"""
    query = update.callback_query
    await query.answer()
    data = query.data  # moment:reply:{role_id}
    role_id = data.split(":")[2]
    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)

    replies = MOMENT_QUICK_REPLIES.get(role_id, DEFAULT_QUICK_REPLIES)
    buttons = []
    for i, reply_text in enumerate(replies):
        buttons.append([InlineKeyboardButton(
            reply_text,
            callback_data=f"moment:say:{role_id}:{i}"
        )])
    # 最后一行：自己写（跳转聊天）
    bot_username = context.bot.username
    buttons.append([InlineKeyboardButton(
        "自己写...",
        url=f"https://t.me/{bot_username}"
    )])

    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_moment_say(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户点击快捷回复 — 调用AI生成回复"""
    query = update.callback_query
    data = query.data  # moment:say:{role_id}:{idx}
    parts = data.split(":")
    role_id = parts[2]
    idx = int(parts[3])

    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)
    replies = MOMENT_QUICK_REPLIES.get(role_id, DEFAULT_QUICK_REPLIES)
    user_text = replies[idx]

    await query.answer(f"已发送：{user_text}")

    user_id = query.from_user.id
    db.create_user(user_id)

    # Build LLM context
    system_prompt = role.get("system_prompt", "")
    from prompt_template import resolve_system_prompt
    from relationship import get_mood_prompt, get_relationship_prompt
    from knowledge import get_knowledge_context
    from environment import get_environment_context

    user_name = query.from_user.first_name or "宝贝"
    mood_str = get_mood_prompt(user_id, role_id)
    rel_str = get_relationship_prompt(role_id, user_id)
    knowledge_ctx = get_knowledge_context(user_id, role_id)
    env_ctx = get_environment_context(role_id)

    final_prompt = resolve_system_prompt(role, user_name, mood_str, rel_str)
    messages = [
        {"role": "system", "content": final_prompt},
        {"role": "system", "content": env_ctx},
    ]
    if knowledge_ctx:
        messages.append({"role": "system", "content": knowledge_ctx})
    messages.append({"role": "user", "content": user_text})

    try:
        from providers.factory import get_provider_from_config
        provider = get_provider_from_config()

        reply = await provider.chat(messages=messages, max_tokens=500, temperature=0.9)

        if reply:
            # Edit the original message to show what user said
            try:
                await query.edit_message_caption(
                    caption=f"{role_name}的朋友圈\n\n你说：{user_text}"
                )
            except Exception:
                await query.edit_message_text(
                    text=f"{role_name}的朋友圈\n\n你说：{user_text}"
                )
            # Send AI reply
            await query.message.reply_text(reply)
            # Update message count
            db.increment_message_count(user_id)
            db.update_role(user_id, role_id)
            db.update_last_message_time(user_id)
    except Exception as e:
        logger.error(f"Moment reply failed user={user_id} role={role_id}: {e}")
        await query.message.reply_text(
            f"{role_name}正在忙，等下回复你哦~"
        )

async def send_moment_broadcast(context: ContextTypes.DEFAULT_TYPE):
    """定时任务：发送朋友圈给所有聊过该角色的用户"""
    role_id = context.bot_data.get("role_id", "")
    role = ROLES.get(role_id, {})
    role_name = role.get("name", role_id)

    # 选照片
    photo_path = _pick_moment_photo(role_id)
    if not photo_path:
        logger.warning(f"Moment: no photo for {role_id}, skipping")
        return

    # 选文案
    text = _pick_moment_text(role_id)

    # 获取所有聊过该角色的用户
    try:
        users = db.conn.execute(
            "SELECT DISTINCT user_id FROM users WHERE total_messages > 0 AND current_role = ?",
            (role_id,)
        ).fetchall()
    except Exception as e:
        logger.error(f"Moment: failed to get users: {e}")
        return

    if not users:
        logger.info(f"Moment: no users for {role_id}")
        return

    user_ids = [u["user_id"] for u in users]

    # Filter out users who haven't replied in 2+ days
    now = __import__("time").time()
    SILENCE_CUTOFF = 48 * 3600  # 2 days
    active_ids = []
    for uid in user_ids:
        last_msg = db.get_last_message_time(uid)
        if last_msg is None or (now - last_msg) < SILENCE_CUTOFF:
            active_ids.append(uid)
    skipped = len(user_ids) - len(active_ids)
    if skipped:
        logger.info(f"Moment: {role_name} skipping {skipped} silent users")
    user_ids = active_ids
    logger.info(f"Moment: {role_name} sending to {len(user_ids)} users")

    # 逐个发送（限速，避免被TG封）
    success = 0
    for user_id in user_ids:
        if await _send_moment_to_user(context.bot, user_id, role_id, role_name, photo_path, text):
            success += 1
        # 速率控制：每秒不超过30条
        if success % 30 == 0:
            await asyncio.sleep(1)

    logger.info(f"Moment: {role_name} sent to {success}/{len(user_ids)} users")
