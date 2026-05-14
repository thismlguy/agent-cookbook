"""End-to-end agent test with the OpenRouter HTTPS call mocked.

Verifies that the agent:
  1. Sends the right JSON body to OpenRouter (model, provider pin,
     reasoning-disable, max_tokens, system prompt with policy, full tool
     inventory).
  2. Drives a full ReAct loop — assistant tool_call → tool execution →
     assistant final reply — making exactly two LLM calls.
  3. Returns the mocked final assistant content.

Run: `uv run pytest tests/ -v`
"""
from __future__ import annotations

import json

import pytest
import respx
from httpx import Response
from langchain_core.messages import HumanMessage

from src.agents import get_variant
from src.config import DB_PATH, Config
from src.domain.store import Store
from src.providers import build_chat_model

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _fake_config() -> Config:
    return Config(
        openrouter_api_key="test-or-key",
        langfuse_public_key="test-lf-pub",
        langfuse_secret_key="test-lf-sec",
        langfuse_base_url="http://lf.invalid",
        model_id="moonshotai/kimi-k2.6",
    )


def _resp_with_tool_call() -> dict:
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "model": "moonshotai/kimi-k2.6",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_user_details",
                                "arguments": json.dumps({"user_id": "mia_li_3668"}),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
    }


def _resp_final() -> dict:
    return {
        "id": "gen-2",
        "object": "chat.completion",
        "model": "moonshotai/kimi-k2.6",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "You have 3 reservations on file.",
                },
            }
        ],
        "usage": {"prompt_tokens": 200, "completion_tokens": 12, "total_tokens": 212},
    }


@pytest.mark.asyncio
async def test_agent_full_react_loop_with_mocked_openrouter(monkeypatch):
    cfg = _fake_config()
    monkeypatch.setenv("OPENROUTER_API_KEY", cfg.openrouter_api_key)
    store = Store.load_from_path(DB_PATH)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL).mock(
            side_effect=[
                Response(200, json=_resp_with_tool_call()),
                Response(200, json=_resp_final()),
            ]
        )

        llm = build_chat_model(f"openrouter:{cfg.model_id}")
        agent = get_variant("v1")(store, llm)
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="Who is mia_li_3668?")]}
        )

    # 1) Two OpenRouter calls — one ReAct loop completed
    assert route.call_count == 2

    # 2) First request shape
    body1 = json.loads(route.calls[0].request.content)
    assert body1["model"] == "moonshotai/kimi-k2.6"
    assert body1["provider"] == {"only": ["moonshotai"]}
    assert body1["reasoning"] == {"enabled": False}
    # langchain-openai / openai-sdk now serializes max_tokens as max_completion_tokens
    assert body1["max_completion_tokens"] == 40960
    assert body1["temperature"] == 0

    sys_msg = body1["messages"][0]
    assert sys_msg["role"] == "system"
    assert "# Airline Agent Policy" in sys_msg["content"]

    tool_names = {t["function"]["name"] for t in body1["tools"]}
    assert tool_names >= {
        "get_user_details",
        "get_reservation_details",
        "search_direct_flight",
        "calculate",
        "book_reservation",
        "update_reservation_flights",
        "update_reservation_baggages",
        "update_reservation_passengers",
        "cancel_reservation",
        "transfer_to_human_agents",
    }

    # 3) Second request carries the tool result back
    body2 = json.loads(route.calls[1].request.content)
    roles = [m["role"] for m in body2["messages"]]
    assert "tool" in roles

    # 4) Final assistant content from the mocked second response surfaces
    assert "3 reservations" in result["messages"][-1].content
