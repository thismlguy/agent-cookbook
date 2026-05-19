"""Airline agent variant `v2` — LangGraph ReAct agent with framing+policy system prompt.

Structurally identical to v1. The only difference is the system prompt, which
adds a short framing layer in front of the verbatim policy. See
`prompting-best-practices.md` for the references behind the framing.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from src.agents.v2.prompt import load_system_prompt
from src.agents.v2.tools import make_tools
from src.domain.store import Store


def make_agent(store: Store, llm: BaseChatModel) -> CompiledStateGraph:
    """Build the v2 airline agent bound to this Store and chat model."""
    tools = make_tools(store)
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=load_system_prompt(),
        name="airline-agent-v2",
    )
