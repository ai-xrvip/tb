# -*- coding: utf-8 -*-
import os

BASE = r"C:\Users\13249\Documents\Codex\2026-06-21\ai-xrvip-tgbot-https-github-com"
PROFILE_DIR = os.path.join(BASE, "outputs", "character_profiles")
os.makedirs(PROFILE_DIR, exist_ok=True)
for f in os.listdir(PROFILE_DIR):
    if f.endswith(".txt"):
        os.remove(os.path.join(PROFILE_DIR, f))

MEDIA = [
    ("日常","日常生活照"),("自拍","对镜自拍"),("表情","各种表情特写"),("通勤","外出照"),
    ("穿搭","OOTD穿搭"),("美食","美食"),("宠物","宠物合影"),("工作","工作状态"),
    ("运动","运动照"),("姿态","动作姿态"),("旅游","旅游照"),("夜景","夜晚氛围照"),
    ("起床","清晨起床照"),("派对","聚会照"),("性感","私密性感照"),("泳装","泳装照"),
    ("沐浴","浴室照"),("情趣","情趣照"),("亲密","亲密照"),("裸露","裸露照"),
    ("露点","露点照"),("全裸","全裸照"),
]
MT = "\n".join('        {"id": "'+m[0]+'", "desc": "'+m[1]+'"},' for m in MEDIA)
MT = "[\n" + MT + "\n        ]"

TIERS = """
【发照片规则】
日常随时发送：[media:日常] [media:自拍] [media:表情] [media:通勤] [media:穿搭] [media:美食] [media:宠物] [media:工作]
聊熟了(30条)解锁：[media:姿态] [media:旅游] [media:夜景] [media:起床] [media:派对]
关系升温(50条)解锁：[media:性感] [media:泳装] [media:沐浴] [media:情趣]
亲密关系(100条)解锁：[media:亲密] [media:裸露]
完全信任(150条)解锁：[media:露点] [media:全裸]
发的每张照片都要附带符合语境的文字，挑逗大胆一点也没关系。"""

def esc(s):
    return s.replace("\\","\\\\").replace('"','\\"')

print("Setup complete. Ready to define characters...")
