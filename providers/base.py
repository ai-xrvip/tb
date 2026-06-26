"""LLM 提供商抽象基类 —— 参考 karfly bot 和 Openaibot 的多模型架构"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional


class BaseProvider(ABC):
    """所有 LLM 提供商的基类"""

    provider_type: str = "base"

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """非流式对话，返回完整回复"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话，逐 token yield"""
        ...

    @abstractmethod
    async def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        """生成图片，返回 URL 或 base64"""
        ...

    @abstractmethod
    async def transcribe_audio(self, audio_file_path: str) -> Optional[str]:
        """语音转文字"""
        ...

    @property
    def is_available(self) -> bool:
        """检查提供商是否可用"""
        return bool(self.api_key)


class ProviderError(Exception):
    """提供商通用错误"""
    pass


class RateLimitError(ProviderError):
    """速率限制错误"""
    pass


class TokenLimitError(ProviderError):
    """Token 超限错误"""
    pass
