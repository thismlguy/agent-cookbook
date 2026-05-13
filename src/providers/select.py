"""Build a LangChain chat model from a `<provider>:<model>` spec.

OpenRouter is a first-class alias backed by `ChatOpenAI` pointed at
OpenRouter's OpenAI-compatible endpoint. Kimi K2.x routing is pinned to
the Moonshot provider, with reasoning disabled, so the agent behavior
from the foundational change is preserved exactly.

Every other provider delegates to LangChain's `init_chat_model`, which
handles per-provider message/tool serialization for us.
"""
from __future__ import annotations

import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def parse_spec(spec: str) -> tuple[str, str]:
    """Split `<provider>:<model>` into (provider, model). Errors on bad input."""
    if ":" not in spec:
        raise ValueError(
            f"model spec '{spec}' must be of the form '<provider>:<model>' "
            f"(e.g. 'openrouter:moonshotai/kimi-k2-6', 'anthropic:claude-sonnet-4-5')"
        )
    provider, model = spec.split(":", 1)
    if not provider or not model:
        raise ValueError(f"invalid model spec '{spec}': both provider and model are required")
    return provider, model


def _is_kimi_k2(model: str) -> bool:
    return model.startswith("moonshotai/kimi-k2")


def _build_openrouter(model: str, **kwargs) -> ChatOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to build an openrouter:* model")
    extra_body: dict = {}
    if _is_kimi_k2(model):
        extra_body["provider"] = {"only": ["moonshotai"]}
        extra_body["reasoning"] = {"enabled": False}
    return ChatOpenAI(
        model=model,
        openai_api_key=api_key,
        openai_api_base=OPENROUTER_BASE_URL,
        extra_body=extra_body or None,
        temperature=kwargs.get("temperature", 0),
        max_tokens=kwargs.get("max_tokens", 4096),
    )


def build_chat_model(spec: str, **kwargs) -> BaseChatModel:
    """Build a LangChain chat model from a `<provider>:<model>` spec.

    `kwargs` are forwarded to the underlying constructor. Recognized
    providers:
      - `openrouter:<model>` → `ChatOpenAI` on `https://openrouter.ai/api/v1`;
        Kimi K2.x is pinned to Moonshot with reasoning disabled.
      - any other prefix → delegated to LangChain's `init_chat_model`.
    """
    provider, model = parse_spec(spec)
    if provider == "openrouter":
        return _build_openrouter(model, **kwargs)
    # init_chat_model accepts "anthropic:claude-...", "openai:gpt-...", etc.
    return init_chat_model(spec, **kwargs)
