"""Airline agent variant `v3` — orchestrator over specialist subagents.

The orchestrator is a LangGraph ReAct agent with an 8-tool surface
(3 reads + 4 specialist eligibility checks + transfer). Write
operations are not on the LLM's tool surface; they execute via
`execute_pending_action` invoked by the UI/runner after the user
confirms a `<confirmation_card>` tag.

See `src/agents/v3/architecture.md` for the full design.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langchain.agents import create_agent

from src.agents.v3.prompt import load_system_prompt
from src.agents.v3.tools import make_tools
from src.domain.store import Store


def make_agent(store: Store, llm: BaseChatModel) -> CompiledStateGraph:
    """Build the v3 airline orchestrator bound to this Store and chat model."""
    tools = make_tools(store)
    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=load_system_prompt(),
        name="airline-agent-v3",
    )
