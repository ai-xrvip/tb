"""多语言 i18n 系统 —— 参考 karfly bot 的多语言设计"""
from typing import Optional


class I18n:
    """简单的键值对翻译系统"""

    _strings: dict[str, dict[str, str]] = {}
    _default_lang: str = "zh"

    def __init__(self, default_lang: str = "zh"):
        self._default_lang = default_lang
        self._load_builtin()

    def _load_builtin(self):
        """加载内置翻译"""
        self._strings["zh"] = _ZH_STRINGS
        self._strings["en"] = _EN_STRINGS

    def t(self, key: str, lang: Optional[str] = None, **kwargs) -> str:
        """获取翻译文本"""
        lang = lang or self._default_lang
        text = self._strings.get(lang, {}).get(key)
        if text is None:
            text = self._strings.get(self._default_lang, {}).get(key, key)
        if kwargs:
            text = text.format(**kwargs)
        return text

    def set_lang(self, lang: str):
        """设置默认语言"""
        if lang in self._strings:
            self._default_lang = lang

    def user_lang(self, user_id: int) -> str:
        """获取用户语言偏好（可从数据库读取）"""
        return self._default_lang


# ── 中文翻译 ──
_ZH_STRINGS = {
    "welcome": "✨ 欢迎回来，{name}～",
    "role_changed": "💬 已切换到角色：{name}",
    "free_limit": "💔 免费试用次数已用完～\n🔑 使用激活码：`/redeem XXXX-XXXX`",
    "code_invalid": "❌ 激活码无效，请检查后重试。",
    "code_used": "⚠️ 该激活码已被使用。",
    "code_success": "🎉 激活成功！\n📦 类型：{type}\n⏰ 有效期：{days} 天",
    "admin_only": "⛔ 此命令仅限管理员使用。",
    "network_error": "😢 网络开小差了，等我一小会儿再试试好吗？",
    "rate_limit": "⏳ 消息太频繁啦，稍等一下再聊～",
    "token_limit": "📝 对话太长了，试试 `/clear` 清空历史再聊吧～",
    "history_cleared": "🗑️ 对话历史已清空～",
    "unknown_role": "❌ 未知角色。",
    "broadcast_sent": "📢 广播已发送给 {count} 个用户。",
}

# ── 英文翻译 ──
_EN_STRINGS = {
    "welcome": "✨ Welcome back, {name}~",
    "role_changed": "💬 Switched to: {name}",
    "free_limit": "💔 Free trial used up~\n🔑 Use activation code: `/redeem XXXX-XXXX`",
    "code_invalid": "❌ Invalid activation code.",
    "code_used": "⚠️ This code has already been used.",
    "code_success": "🎉 Activated!\n📦 Type: {type}\n⏰ Valid: {days} days",
    "admin_only": "⛔ Admin only.",
    "network_error": "😢 Network issue, please try again later~",
    "rate_limit": "⏳ Too many messages, wait a moment~",
    "token_limit": "📝 Conversation too long, try `/clear`~",
    "history_cleared": "🗑️ Chat history cleared~",
    "unknown_role": "❌ Unknown role.",
    "broadcast_sent": "📢 Broadcast sent to {count} users.",
}


# 全局单例
i18n = I18n()
