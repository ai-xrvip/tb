"""OpenAI 提供商 —— 完整实现 chat/stream/image/transcribe"""
from typing import AsyncGenerator, Optional
from openai import AsyncOpenAI
from .base import BaseProvider, ProviderError, RateLimitError, TokenLimitError


class OpenAIProvider(BaseProvider):
    provider_type = "openai"

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: str = "gpt-4o"):
        super().__init__(api_key, base_url, model)
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            kwargs = {"api_key": self.api_key, "timeout": 30.0}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**kwargs)
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
            if "token" in msg.lower() or "context_length" in msg.lower():
                raise TokenLimitError(msg) from e
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
        try:
            resp = await self.client.images.generate(
                model=kwargs.get("image_model", "dall-e-3"),
                prompt=prompt,
                n=1,
                size=kwargs.get("size", "1024x1024"),
            )
            return resp.data[0].url
        except Exception as e:
            raise ProviderError(f"Image generation failed: {e}") from e

    async def transcribe_audio(self, audio_file_path: str) -> Optional[str]:
        try:
            with open(audio_file_path, "rb") as f:
                resp = await self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                )
            return resp.text
        except Exception as e:
            raise ProviderError(f"Transcription failed: {e}") from e
