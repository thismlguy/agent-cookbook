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
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MAX_TOKENS = 40960
DEFAULT_TEMPERATURE = 0


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


def _build_openrouter(model: str, *, enable_reasoning: bool = False, **kwargs) -> ChatOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to build an openrouter:* model")
    extra_body: dict = {}
    if _is_kimi_k2(model):
        extra_body["provider"] = {"only": ["moonshotai"]}
        # Reasoning is OFF by default to preserve agent behavior; callers that
        # want a thinking Kimi (e.g. the user simulator) opt in explicitly. The
        # reasoning trace bills as completion tokens and stays out of `.content`.
        extra_body["reasoning"] = {"enabled": bool(enable_reasoning)}
    return ChatOpenAI(
        model=model,
        openai_api_key=api_key,
        openai_api_base=OPENROUTER_BASE_URL,
        extra_body=extra_body or None,
        temperature=kwargs.get("temperature", DEFAULT_TEMPERATURE),
        max_tokens=kwargs.get("max_tokens", DEFAULT_MAX_TOKENS),
    )


def build_chat_model(
    spec: str,
    *,
    effort: str | None = None,
    thinking: dict | None = None,
    enable_reasoning: bool = False,
    **kwargs,
):
    """Build a LangChain chat model from a `<provider>:<model>` spec.

    `kwargs` are forwarded to the underlying constructor. Recognized
    providers:
      - `openrouter:<model>` → `ChatOpenAI` on `https://openrouter.ai/api/v1`;
        Kimi K2.x is pinned to Moonshot with reasoning disabled.
      - any other prefix → delegated to LangChain's `init_chat_model`.

    Anthropic-only knobs (ignored for `openrouter:*`):
      - `effort`: shorthand for `output_config.effort` ("low"/"medium"/
        "high"/"max"). Sonnet 4.6 and Opus-tier only; Haiku 4.5 rejects it.
      - `thinking`: e.g. `{"type": "adaptive"}` for adaptive thinking.

    Prompt caching is applied separately at the system-prompt level — see
    `cache_system_prompt` — because the direct Anthropic transport caches
    via block-level `cache_control`, not a top-level request param.
    """
    provider, model = parse_spec(spec)
    if provider == "openrouter":
        return _build_openrouter(model, enable_reasoning=enable_reasoning, **kwargs)

    # Anthropic requires max_tokens; the constructor default (None → 1024)
    # is too small once thinking is on, so set a ceiling here. It bounds,
    # not targets, output — non-thinking behavior is unchanged.
    kwargs.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
    if effort is not None:
        kwargs["effort"] = effort
    if thinking is not None:
        kwargs["thinking"] = thinking

    # init_chat_model accepts "anthropic:claude-...", "openai:gpt-...", etc.
    return init_chat_model(spec, **kwargs)


def is_anthropic(llm) -> bool:
    """True if `llm` is a direct Anthropic chat model (ChatAnthropic)."""
    return getattr(llm, "_llm_type", None) == "anthropic-chat"


def cache_system_prompt(prompt: str, llm):
    """Wrap a system prompt so its prefix is prompt-cached, if `llm` supports it.

    On the direct Anthropic transport, attaching `cache_control` to the
    system text block caches everything rendered before the conversation —
    tools (rendered first) plus the system prompt. That stable prefix is
    re-sent on every turn of the ReAct loop, so caching it is the dominant
    cost lever (cache reads bill at ~0.1x).

    Returns a structured `SystemMessage` for Anthropic, or the bare string
    unchanged for any other provider (whose content format would reject the
    cache_control block). Note the Anthropic cache minimum is ~2K tokens for
    Sonnet 4.6 — shorter prefixes silently won't cache (no error).
    """
    if not is_anthropic(llm):
        return prompt
    return SystemMessage(
        content=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
    )
