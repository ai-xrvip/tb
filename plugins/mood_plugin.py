"""
心情相关关键词触发插件
"""
from typing import Optional
from plugins import PluginBase
from relationship import get_mood_for_user


class MoodPlugin(PluginBase):
    name = "mood"
    version = "1.0.0"
    description = "响应用户询问心情/状态"

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    async def on_message(self, update, context) -> Optional[bool]:
        user_text = update.message.text.strip()
        role_id = context.bot_data.get("role_id", "xiaolu")
        user_id = update.effective_user.id

        mood_keywords = ["心情", "开心吗", "不高兴", "怎么了", "累不累", "困不困", "状态"]
        
        if any(kw in user_text for kw in mood_keywords):
            try:
                mood = get_mood_for_user(user_id, role_id)
                mood_name = mood.get("name", "")
                mood_prompt = mood.get("prompt", "")
                
                import random
                replies = [
                    f"被你发现了～{mood_prompt}",
                    f"嗯…今天{mood_name}的，{mood_prompt}",
                    f"{mood_name}～不过跟你聊天就好多了！",
                ]
                await update.message.reply_text(random.choice(replies))
                return True
            except Exception:
                pass

        return False
