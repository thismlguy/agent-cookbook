"""Agent variant registry — map variant id → `make_agent(store, llm)` factory."""
from __future__ import annotations

from typing import Callable

from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from src.agents.v0.graph import make_agent as _v0_make_agent
from src.agents.v1.graph import make_agent as _v1_make_agent
from src.agents.v2.graph import make_agent as _v2_make_agent
from src.domain.store import Store

AgentFactory = Callable[[Store, BaseChatModel], CompiledStateGraph]

VARIANTS: dict[str, AgentFactory] = {
    "v0": _v0_make_agent,
    "v1": _v1_make_agent,
    "v2": _v2_make_agent,  # orchestrator + specialist subagents
}


def get_variant(variant_id: str) -> AgentFactory:
    if variant_id not in VARIANTS:
        raise KeyError(
            f"unknown agent variant '{variant_id}'. Known variants: {sorted(VARIANTS)}"
        )
    return VARIANTS[variant_id]
