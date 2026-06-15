"""Airline agent variant `v1` — LangGraph ReAct agent with framing+policy system prompt.

Structurally identical to v0. The only difference is the system prompt, which
adds a short framing layer in front of the verbatim policy. See
`prompting-best-practices.md` for the references behind the framing.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from src.agents.v1.prompt import load_system_prompt
from src.agents.v1.tools import make_tools
from src.domain.store import Store
from src.providers import cache_system_prompt


def make_agent(store: Store, llm: BaseChatModel) -> CompiledStateGraph:
    """Build the v1 airline agent bound to this Store and chat model."""
    tools = make_tools(store)
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=cache_system_prompt(load_system_prompt(), llm),
        name="airline-agent-v1",
    )
