"""DeepSeek 提供商 —— 保留原有逻辑并增强流式输出"""
from typing import AsyncGenerator, Optional
from openai import AsyncOpenAI
from .base import BaseProvider, ProviderError, RateLimitError


class DeepSeekProvider(BaseProvider):
    provider_type = "deepseek"

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        super().__init__(api_key, base_url, model)
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2048, **kwargs) -> str:
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            msg = str(e)
            if "rate" in msg.lower() or "429" in msg:
                raise RateLimitError(msg) from e
            raise ProviderError(msg) from e

    async def chat_stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2048, **kwargs) -> AsyncGenerator[str, None]:
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            msg = str(e)
            if "rate" in msg.lower() or "429" in msg:
                raise RateLimitError(msg) from e
            raise ProviderError(msg) from e

    async def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        return None  # DeepSeek 暂不支持生图

    async def transcribe_audio(self, audio_file_path: str) -> Optional[str]:
        return None  # DeepSeek 暂不支持语音转文字
