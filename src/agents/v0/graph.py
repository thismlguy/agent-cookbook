"""Airline agent variant `v0` — LangGraph ReAct agent with full policy.md as system prompt."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from src.agents.v0.prompt import load_system_prompt
from src.agents.v0.tools import make_tools
from src.domain.store import Store
from src.providers import cache_system_prompt


def make_agent(store: Store, llm: BaseChatModel) -> CompiledStateGraph:
    """Build the v0 airline agent bound to this Store and chat model.

    The caller supplies the LLM so provider/model selection happens
    outside the variant. The agent itself is provider-agnostic.
    """
    tools = make_tools(store)
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=cache_system_prompt(load_system_prompt(), llm),
        name="airline-agent-v0",
    )
