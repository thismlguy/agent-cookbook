"""LangGraph ReAct agent — OpenRouter / Moonshot / Kimi K2.6 by default."""
from __future__ import annotations

from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from src.agent.prompt import load_system_prompt
from src.agent.tools import make_tools
from src.config import Config
from src.domain.store import Store

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_llm(config: Config) -> ChatOpenAI:
    """Build the LLM client pinned to OpenRouter → Moonshot."""
    return ChatOpenAI(
        model=config.model_id,
        openai_api_key=config.openrouter_api_key,
        openai_api_base=OPENROUTER_BASE_URL,
        extra_body={
            "provider": {"only": ["moonshotai"]},
            "reasoning": {"enabled": False},
        },
        temperature=0,
        max_tokens=4096,
    )


def build_agent(config: Config, store: Store) -> CompiledStateGraph:
    """Build a fresh airline agent bound to this Store.

    Each Chainlit session creates its own Store and its own agent so
    state stays isolated. The full policy.md is injected verbatim as
    the system prompt; provider-side prompt caching keeps the per-turn
    token cost bounded.
    """
    llm = build_llm(config)
    tools = make_tools(store)
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=load_system_prompt(),
        name="airline-agent",
    )
