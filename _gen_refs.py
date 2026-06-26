import urllib.request, urllib.parse, os, time, ssl, json

BASE = r"C:\Users\13249\Documents\Codex\2026-06-21\ai-xrvip-tgbot-https-github-com\media"
print(f"BASE: {BASE}")

# 30个角色的精简生图prompt（英文关键词，中文人脸特征）
chars = [
    ("xiaolu", "22yo cute Chinese girl, round face, large doe eyes, small upturned nose, pink lips slight pout, fair porcelain skin, natural blush, chestnut brown hair twin tails with ribbons, petite slim 158cm, casual cute outfit, warm natural lighting, realistic photography, Chengdu street background"),
    ("linxi", "28yo Chinese woman, sharp angular face, phoenix eyes, high nose bridge, thin lips, cold elegant expression, porcelain skin, sharp jawline, long straight black hair center part mid-back length, tall slender 170cm, business suit, Shanghai Lujiazui office background, professional photography"),
    ("mia", "25yo mixed Asian woman, warm friendly face, almond eyes light brown, bright smile showing teeth, sun-kissed healthy glow, light freckles, dark brown hair high ponytail, athletic fit 167cm, gym outfit, Los Angeles beach background, fitness photography"),
    ("sunian", "27yo Chinese woman, oval gentle face, soft doe eyes, delicate straight nose, thin scholarly glasses gold frame, porcelain skin slight pallor, long straight black hair loosely tied low ponytail, slender graceful 163cm, artist studio background with paintings, Hangzhou West Lake aesthetic"),
    ("yuki", "20yo Chinese girl, oval pure face, round innocent eyes, small straight nose, pink small lips, fair delicate skin, natural blush, long black hair waist length with bangs in braids, slender 160cm, Hanfu traditional dress, Suzhou garden background, soft natural light"),
    ("reina", "21yo Chinese girl, delicate heart-shaped face, large double-eyelid eyes, high nose bridge, full lips, fair porcelain skin, elegant makeup, dark brown long wavy hair waist length with headband, slim 162cm, luxury outfit, Tokyo upscale apartment background"),
    ("chiyo", "29yo Chinese woman, round gentle face, smiling crescent eyes, round nose tip, full lips, healthy warm skin, always smiling, dark brown medium hair shoulder length pinned up, curvy 165cm, casual kitchen outfit, Qingdao seaside restaurant background"),
    ("nana", "23yo Chinese girl, lively sharp face, large round eyes, small upturned nose, thin smiling lips, fair skin, natural light makeup, black short hair shoulder length with purple streaks and air bangs, slim 162cm, gaming headset, Changsha night market background"),
    ("mizuki", "30yo Chinese woman, refined square face, phoenix eyes, high nose bridge, thin lips, fair porcelain skin, professional makeup, black short bob hair sleek, tall 168cm, luxury business suit, Shenzhen Nanshan tech office skyline background"),
    ("akari", "24yo Chinese girl, round gentle face, large round doe eyes, small cute nose, pink soft lips, fair skin, confused innocent expression, black medium hair shoulder length in low bun with wispy strands, soft 160cm, nurse uniform, Chongqing hospital background"),

    ("yuna", "26yo Chinese woman, high fashion face, narrow elongated eyes, high nose bridge, full lips, sun-kissed healthy skin, runway makeup, long straight black hair waist length center part, tall 175cm supermodel figure, fashion outfit, Guangzhou Tianhe CBD background"),
    ("shiori", "25yo Chinese girl, oval quiet face, gentle almond eyes, straight nose, thin lips, fair skin, round frame glasses, long black hair waist length in side braid, slender 163cm, scholarly outfit, Nanjing university library background"),
    ("sora", "26yo Chinese woman, oval friendly face, smiling almond eyes, straight nose, smiling lips, healthy skin, light professional makeup, dark brown hair in flight attendant bun, tall 168cm, airline uniform, Xiamen airport or seaside background"),
    ("kaede", "27yo Chinese woman, square heroic face, sharp phoenix eyes, straight nose, thin lips, wheat skin, no makeup, short black hair ear length, muscular 168cm, police uniform, Wuhan city background"),
    ("ruri", "29yo Chinese woman, sharp face capable, narrow eyes, high nose bridge, thin lips, fair skin, refined office makeup, dark brown medium hair shoulder length slightly wavy, slim 167cm, lawyer suit, Beijing CBD hutong background"),
    ("ren", "28yo Chinese woman, diamond face with storied look, deep eyes, straight nose, thin lips, wheat skin, no makeup, long black hair waist length loose, slim 165cm, bartender outfit, Kunming bar warm lighting background"),
    ("hana", "26yo Chinese girl, round warm face, crescent moon eyes, small round nose, always smiling freckles, sun-kissed healthy skin, dark brown long hair waist length in loose braid with flower, natural 162cm, floral dress, Dali ancient town Erhai lake background"),
    ("mai", "25yo Chinese woman, oval delicate face, large eyes, straight nose, small mouth, fair skin, natural no makeup, black hair in ballet bun, extremely slim 168cm ballerina figure, ballet leotard, Xi an dance studio background"),
    ("momo", "26yo Chinese girl, round sweet face, large round eyes, small upturned nose, cherry lips, fair skin, obvious blush, light brown hair shoulder length with air bangs in low twin tails, petite 160cm, cute casual outfit, Taipei Yongkang street cafe background"),
    ("sakura", "28yo Chinese woman, round gentle face, large round eyes, small cute nose, pink lips, fair skin, warm smile, dark brown long hair waist length in low ponytail, 165cm, vet coat with cat, Harbin snowy street background"),
    ("aya", "27yo Chinese woman, sharp clever face, smiling almond eyes, straight nose, thin lips, fair skin, refined light makeup, dark brown medium hair shoulder length slightly wavy, 165cm, office secretary outfit, Tianjin Haihe river background"),
    ("mei", "24yo Chinese girl, oval artistic face, gentle almond eyes, straight nose, natural lip color, fair skin, no makeup or light, black long hair slightly wavy waist length loose, slender 163cm, musician outfit with guitar, Chengdu Yulin road bar background"),
    ("koharu", "27yo Chinese woman, sharp face, deep eyes, high nose bridge, thin lips, rosy high-altitude cheeks, sun-kissed healthy skin, black long straight hair waist length in two thick braids, sturdy 165cm, photographer outfit with camera, Lhasa Potala Palace background"),
    ("tsubaki", "28yo Chinese woman, square resolute face, narrow eyes, straight nose, thin lips, wheat skin, no makeup, short black hair shoulder length practical, sturdy 166cm, journalist vest with press card, Lanzhou Yellow River background"),
    ("rio", "25yo Chinese girl, sharp cool face, narrow eyes, high nose bridge, thin lips, healthy wheat skin, short black hair ear length under baseball cap, athletic 168cm, racing suit, Zhuhai racing track background"),
    ("nozomi", "23yo Chinese girl, round lively face, large round eyes, small cute nose, upturned smiling lips, fair skin, long black hair waist length in various cute styles, petite 160cm, casual cute outfit, Hong Kong city background"),
    ("nami", "24yo Chinese girl, sharp sunny face, smiling almond eyes, straight nose, big laughing mouth, wheat skin healthy glow, dark brown long hair waist length wet wavy natural sea salt texture, tall athletic 170cm, bikini top, Sanya beach surfing background"),
    ("fumi", "26yo Chinese woman, oval quiet face, gentle almond eyes, straight nose, thin lips, fair skin, metal thin frame glasses, long black hair waist length in low bun, slender 163cm, librarian outfit, Jinan library Daming Lake background"),
    ("eri", "29yo Chinese woman, sharp intellectual face, narrow eyes, high nose bridge, thin lips, fair skin, black frame glasses, short black hair shoulder length plain, slim 165cm, lab coat, Silicon Valley tech office background"),
    ("yui", "21yo Chinese girl, round energetic face, large round eyes, small upturned nose, pink soft lips, fair skin always smiling, dark brown long hair waist length in high twin tails, petite 160cm, maid cafe uniform, Shenyang Zhongjie street background"),
]

print(f"Starting generation of {len(chars)} characters...")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

for cid, prompt in chars:
    folder = os.path.join(BASE, cid, "参考图")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "reference.jpg")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        print(f"  SKIP: {cid}")
        continue

    encoded = urllib.parse.quote(prompt + ", portrait shot, upper body, sharp focus, photorealistic")
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=768&height=1024&nologo=true&seed={hash(cid) % 100000}"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=60, context=ctx)
            data = resp.read()
            if len(data) > 1000:
                with open(path, "wb") as f:
                    f.write(data)
                print(f"  OK: {cid} ({len(data)//1024}KB)")
                break
        except Exception as e:
            if attempt == 2:
                print(f"  FAIL: {cid} - {e}")
            time.sleep(8)
    time.sleep(5)

print("\nDone!")
