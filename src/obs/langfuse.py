"""Langfuse initialization + LangChain callback handler.

Initialized once at startup from environment variables. The same handler
instance is reused across sessions; per-session correlation is achieved
by passing `langfuse_session_id` via the LangChain run config metadata.
"""
from __future__ import annotations

from typing import Any

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from src.config import Config

_client: Langfuse | None = None
_handler: CallbackHandler | None = None


def init_langfuse(config: Config) -> tuple[Langfuse, CallbackHandler]:
    """Initialize the global Langfuse client and LangChain callback handler."""
    global _client, _handler
    if _client is None:
        _client = Langfuse(
            public_key=config.langfuse_public_key,
            secret_key=config.langfuse_secret_key,
            host=config.langfuse_base_url,
        )
        _handler = CallbackHandler()
    return _client, _handler  # type: ignore[return-value]


def get_client() -> Langfuse:
    if _client is None:
        raise RuntimeError("Langfuse not initialized — call init_langfuse(config) first")
    return _client


def get_handler() -> CallbackHandler:
    if _handler is None:
        raise RuntimeError("Langfuse not initialized — call init_langfuse(config) first")
    return _handler


def run_config(session_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Build a LangChain run config that ties this invocation to a Langfuse trace.

    The callback handler reads `langfuse_session_id` / `langfuse_user_id`
    from metadata and applies them to the OTel span attributes, so the
    Langfuse UI groups every turn in a single session into one trace.
    """
    metadata: dict[str, Any] = {"langfuse_session_id": session_id}
    if user_id is not None:
        metadata["langfuse_user_id"] = user_id
    return {
        "callbacks": [get_handler()],
        "metadata": metadata,
    }
