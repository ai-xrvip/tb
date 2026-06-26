"""LLM 提供商工厂 —— 从配置动态创建提供商实例"""
from enum import Enum
from typing import Optional, Type
from .base import BaseProvider


class ProviderType(str, Enum):
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    CLAUDE = "claude"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            value = value.lower()
            for member in cls:
                if member.value == value:
                    return member
        return None


_provider_registry: dict[ProviderType, Type[BaseProvider]] = {}


def register_provider(ptype: ProviderType, cls: Type[BaseProvider]):
    """注册新的提供商"""
    _provider_registry[ptype] = cls


_provider_cache: dict[str, "BaseProvider"] = {}

def _provider_cache_key(ptype: ProviderType, api_key: str, base_url: Optional[str], model: Optional[str]) -> str:
    return f"{ptype.value}:{api_key}:{base_url or ''}:{model or ''}"

def get_provider(
    ptype: ProviderType,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True,
) -> BaseProvider:
    if not _provider_registry:
        from .deepseek import DeepSeekProvider
        from .openai import OpenAIProvider
        register_provider(ProviderType.DEEPSEEK, DeepSeekProvider)
        register_provider(ProviderType.OPENAI, OpenAIProvider)

    if use_cache:
        cache_key = _provider_cache_key(ptype, api_key, base_url, model)
        if cache_key in _provider_cache:
            return _provider_cache[cache_key]

    cls = _provider_registry.get(ptype)
    if cls is None:
        raise ValueError(f"Unknown provider type: {ptype}")

    instance = cls(api_key=api_key, base_url=base_url, model=model)

    if use_cache:
        cache_key = _provider_cache_key(ptype, api_key, base_url, model)
        _provider_cache[cache_key] = instance

    return instance


def list_providers() -> list[str]:
    """列出所有已注册的提供商"""
    if not _provider_registry:
        from .deepseek import DeepSeekProvider
        from .openai import OpenAIProvider
        register_provider(ProviderType.DEEPSEEK, DeepSeekProvider)
        register_provider(ProviderType.OPENAI, OpenAIProvider)
    return [p.value for p in _provider_registry]
