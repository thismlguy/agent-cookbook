"""Drive one sim-user ↔ agent conversation end-to-end for a single task."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.agents import get_variant
from src.config import DB_PATH
from src.domain.store import Store
from src.sim import UserTurn, make_simulator

TerminatedBy = Literal["simulator_end", "max_turns", "error"]


@dataclass
class TurnEvent:
    """One turn boundary, emitted to the runner's `on_event` callback."""

    turn: int
    user: str | None = None
    agent: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # [{name, args, result}]
    ended: bool = False


@dataclass
class RunResult:
    """Outcome of a single task run."""

    task_id: str
    transcript: list[dict[str, Any]]
    turn_count: int
    terminated_by: TerminatedBy
    error: str | None = None
    store_snapshot: dict[str, Any] | None = None
    agent_response_times_ms: list[float] = field(default_factory=list)


def _serialize_message(m: BaseMessage) -> dict[str, Any]:
    """Convert a LangChain message into a JSON-serializable transcript entry."""
    if isinstance(m, HumanMessage):
        return {"role": "user", "content": _stringify(m.content)}
    if isinstance(m, AIMessage):
        entry: dict[str, Any] = {"role": "agent", "content": _stringify(m.content)}
        tool_calls = getattr(m, "tool_calls", None) or []
        if tool_calls:
            entry["tool_calls"] = [
                {"name": tc.get("name"), "args": tc.get("args"), "id": tc.get("id")}
                for tc in tool_calls
            ]
        return entry
    if isinstance(m, ToolMessage):
        return {
            "role": "tool",
            "tool_call_id": getattr(m, "tool_call_id", None),
            "name": getattr(m, "name", None),
            "content": _stringify(m.content),
        }
    return {"role": m.__class__.__name__.lower(), "content": _stringify(getattr(m, "content", ""))}


def _stringify(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


def _extract_tool_events(new_messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Pair each AIMessage tool_call with its ToolMessage result for one turn."""
    results_by_id: dict[str, str] = {}
    for m in new_messages:
        if isinstance(m, ToolMessage):
            results_by_id[getattr(m, "tool_call_id", "") or ""] = _stringify(m.content)
    paired: list[dict[str, Any]] = []
    for m in new_messages:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                paired.append(
                    {
                        "name": tc.get("name"),
                        "args": tc.get("args"),
                        "result": results_by_id.get(tc.get("id") or "", ""),
                    }
                )
    return paired


def _agent_final_text(new_messages: list[BaseMessage]) -> str:
    for m in reversed(new_messages):
        if isinstance(m, AIMessage):
            return _stringify(m.content)
    return ""


def run_task(
    task: dict[str, Any],
    agent_id: str,
    agent_llm: BaseChatModel,
    sim_llm: BaseChatModel,
    max_turns: int = 30,
    on_event: Callable[[TurnEvent], None] | None = None,
    invoke_config: dict[str, Any] | None = None,
) -> RunResult:
    """Drive one task end-to-end and return the structured result.

    A fresh `Store` is constructed per call so per-task state is
    isolated. The agent is instantiated via the agent-variants registry.
    The simulator owns conversation termination via its `kind == "end"`
    structured output; a `max_turns` cap is the backstop.
    """
    task_id = str(task.get("id", "?"))
    store = Store.load_from_path(DB_PATH)
    agent = get_variant(agent_id)(store, agent_llm)
    simulator = make_simulator(task.get("user_scenario") or {}, sim_llm)

    history: list[BaseMessage] = []
    agent_response_times_ms: list[float] = []
    turn = 0
    terminated_by: TerminatedBy
    while True:
        turn += 1
        if turn > max_turns:
            terminated_by = "max_turns"
            break

        user_turn: UserTurn = simulator(history)
        user_msg = HumanMessage(content=user_turn.text)
        history.append(user_msg)

        if user_turn.kind == "end":
            if on_event:
                on_event(TurnEvent(turn=turn, user=user_turn.text, ended=True))
            terminated_by = "simulator_end"
            break

        prev_len = len(history)
        t0 = time.perf_counter()
        result = agent.invoke({"messages": history}, config=invoke_config or {})
        agent_response_times_ms.append((time.perf_counter() - t0) * 1000.0)
        history = list(result["messages"])
        new_msgs = history[prev_len:]

        if on_event:
            on_event(
                TurnEvent(
                    turn=turn,
                    user=user_turn.text,
                    agent=_agent_final_text(new_msgs),
                    tool_calls=_extract_tool_events(new_msgs),
                )
            )

    transcript = [_serialize_message(m) for m in history]
    return RunResult(
        task_id=task_id,
        transcript=transcript,
        turn_count=turn,
        terminated_by=terminated_by,
        store_snapshot=store.snapshot(),
        agent_response_times_ms=agent_response_times_ms,
    )
