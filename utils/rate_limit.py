"""速率限制 & 安全加固 —— 参考 karfly bot 和 chatgpt-on-wechat"""
import time
import asyncio
from collections import defaultdict
from utils.logger import logger


class RateLimiter:
    """简单的滑动窗口速率限制器"""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[int, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._last_cleanup: float = 0

    async def is_allowed(self, user_id: int) -> bool:
        """检查用户是否在限制内"""
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds
            # 每5分钟清理一次：删除 10*窗口期 内无任何请求的僵尸用户
            cleanup_window = now - self.window_seconds * 10
            if now - self._last_cleanup > 300:
                stale = [uid for uid in list(self._requests.keys()) if not any(t > cleanup_window for t in self._requests[uid])]
                for uid in stale:
                    del self._requests[uid]
                self._last_cleanup = now


            # Per-minute cleanup of stale user entries to prevent memory leaks
            if now - self._last_cleanup > 300:
                stale = [uid for uid in list(self._requests.keys())
                         if not any(t > window_start for t in self._requests[uid])]
                for uid in stale:
                    del self._requests[uid]
                self._last_cleanup = now


            # 清理旧记录
            self._requests[user_id] = [
                t for t in self._requests[user_id] if t > window_start
            ]

            if len(self._requests[user_id]) >= self.max_requests:
                return False

            self._requests[user_id].append(now)
            return True

    async def get_remaining(self, user_id: int) -> int:
        """获取剩余请求数"""
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds
            # 每5分钟清理一次：删除 10*窗口期 内无任何请求的僵尸用户
            cleanup_window = now - self.window_seconds * 10
            if now - self._last_cleanup > 300:
                stale = [uid for uid in list(self._requests.keys()) if not any(t > cleanup_window for t in self._requests[uid])]
                for uid in stale:
                    del self._requests[uid]
                self._last_cleanup = now


            # Per-minute cleanup of stale user entries to prevent memory leaks
            if now - self._last_cleanup > 300:
                stale = [uid for uid in list(self._requests.keys())
                         if not any(t > window_start for t in self._requests[uid])]
                for uid in stale:
                    del self._requests[uid]
                self._last_cleanup = now

            self._requests[user_id] = [
                t for t in self._requests[user_id] if t > window_start
            ]
            return max(0, self.max_requests - len(self._requests[user_id]))


class AdminRateLimiter(RateLimiter):
    """管理员速率限制器 —— 更宽松的限制"""

    def __init__(self):
        super().__init__(max_requests=60, window_seconds=60)


# 全局实例
user_limiter = RateLimiter(max_requests=15, window_seconds=60)
admin_limiter = AdminRateLimiter()


async def check_rate_limit(user_id: int, is_admin: bool = False) -> bool:
    """检查速率限制，返回 True 表示允许"""
    limiter = admin_limiter if is_admin else user_limiter
    return await limiter.is_allowed(user_id)


# ── 输入安全校验 ──
MAX_MESSAGE_LENGTH = 2000


def sanitize_input(text: str) -> str:
    """清洗用户输入，防止注入和过长消息"""
    if not text:
        return ""
    # 截断过长消息
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH]
    # 移除可能的控制字符
    text = text.replace("\x00", "")
    return text.strip()
