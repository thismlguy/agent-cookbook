"""Airline agent variant `v1` — LangGraph ReAct agent with full policy.md as system prompt."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from src.agents.v1.prompt import load_system_prompt
from src.agents.v1.tools import make_tools
from src.domain.store import Store


def make_agent(store: Store, llm: BaseChatModel) -> CompiledStateGraph:
    """Build the v1 airline agent bound to this Store and chat model.

    The caller supplies the LLM so provider/model selection happens
    outside the variant. The agent itself is provider-agnostic.
    """
    tools = make_tools(store)
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=load_system_prompt(),
        name="airline-agent-v1",
    )
