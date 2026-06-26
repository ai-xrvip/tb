"""
问候/晚安/早安 关键词触发插件
当用户发送特定关键词时，自动以角色口吻回复
"""
from typing import Optional
from plugins import PluginBase
from roles import get_role


class GreetingsPlugin(PluginBase):
    name = "greetings"
    version = "1.0.0"
    description = "自动响应晚安/早安/在吗等问候语"

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    async def on_message(self, update, context) -> Optional[bool]:
        """关键词触发回复"""
        user_text = update.message.text.strip()
        role_id = context.bot_data.get("role_id", "xiaolu")
        role = get_role(role_id)
        role_name = role.get("name", "我") if role else "我"

        triggers = {
            "晚安": [
                f"晚安啦～{role_name}也要睡了，明天见哦 (*^▽^*)",
                f"嗯嗯晚安！做个好梦呀～{role_name}会想你的 💤",
                f"好梦～{role_name}偷偷说一句：今天跟你聊天超开心的！晚安 >w<",
            ],
            "早安": [
                f"早呀！{role_name}刚醒就想起你了～今天也要元气满满哦 ☀️",
                f"早安早安～{role_name}还在赖床呢，再睡五分钟嘛 (。-ω-)zzz",
                f"早上好！{role_name}刚洗完脸，今天天气超好诶！",
            ],
            "在吗": [
                f"在呢在呢！{role_name}一直在等你呀～怎么啦 (*/ω＼*)",
                f"当然在呀～{role_name}刚刚还在想你呢！",
                f"在！{role_name}刚在刷手机就看到你消息了，好巧哦～",
            ],
            "晚安💤": [
                f"晚安晚安～{role_name}也要去睡了，明天继续聊哦 (。-ω-)zzz",
            ],
            "早安☀️": [
                f"早呀～今天也是想{role_name}的一天！☀️",
            ],
        }

        for keyword, replies in triggers.items():
            if user_text == keyword or user_text.startswith(keyword):
                import random
                reply = random.choice(replies)
                await update.message.reply_text(reply)
                return True  # 阻止后续AI处理

        return False
