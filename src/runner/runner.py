"""Drive one sim-user ↔ agent conversation end-to-end for a single task."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.agents import get_variant
from src.agents.v2.pending_actions import (
    execute_pending_action,
    render_card_summary,
    render_post_execute_message,
)
from src.config import DB_PATH
from src.domain.store import Store
from src.sim import UserTurn, make_simulator

# Match `<confirmation_card action_id="..." kind="..."/>` regardless of
# attribute order or whitespace.
_CARD_RE = re.compile(
    r"<confirmation_card\s+(?P<attrs>[^>]*?)/>",
    re.IGNORECASE,
)
_ATTR_RE = re.compile(r"(\w+)\s*=\s*\"([^\"]*)\"")


def _extract_card(text: str) -> dict[str, str] | None:
    """Return {action_id, kind} if `text` contains a confirmation_card tag, else None."""
    if not text:
        return None
    m = _CARD_RE.search(text)
    if not m:
        return None
    attrs = dict(_ATTR_RE.findall(m.group("attrs")))
    if "action_id" not in attrs:
        return None
    return {"action_id": attrs["action_id"], "kind": attrs.get("kind", "")}


def _render_cards_for_sim(history: list[BaseMessage], store: Store) -> list[BaseMessage]:
    """Sim-facing copy of history with each `<confirmation_card/>` tag expanded
    into a human-readable proposal summary (route, cost, payment split, etc.).

    The production UI renders the card so the user sees what they're confirming;
    in eval the runner is that UI. The REAL history (fed to the agent and written
    to the transcript) keeps the bare tag — only this sim-facing copy is expanded.
    A no-op when no tags are present, so v0/v1 transcripts pass through unchanged.
    """
    rendered: list[BaseMessage] = []
    for m in history:
        if isinstance(m, AIMessage):
            text = _stringify(m.content)

            def _expand(match: "re.Match[str]") -> str:
                attrs = dict(_ATTR_RE.findall(match.group("attrs")))
                action_id = attrs.get("action_id")
                pa = store.pending_actions.get(action_id) if action_id else None
                return render_card_summary(pa, store) if pa is not None else match.group(0)

            new_text = _CARD_RE.sub(_expand, text)
            if new_text != text:
                rendered.append(AIMessage(content=new_text))
                continue
        rendered.append(m)
    return rendered

TerminatedBy = Literal["simulator_end", "transferred", "max_turns", "error"]


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
    max_turns: int = 15,
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

        # v2 confirmation-card protocol: the agent presents a proposal as a
        # bare <confirmation_card/> tag. Show the simulator a rendered summary of
        # that proposal (the runner is the "UI" in eval), then let it decide via
        # the structured `card_action` field — no fragile verbatim id echo.
        sim_history = _render_cards_for_sim(history, store) if agent_id == "v2" else history
        user_turn: UserTurn = simulator(sim_history)
        user_text = user_turn.text
        effective_kind = user_turn.kind

        last_agent_text = ""
        for m in reversed(history):
            if isinstance(m, AIMessage):
                last_agent_text = _stringify(m.content)
                break
        prior_card = _extract_card(last_agent_text)
        if prior_card is not None and user_turn.card_action == "accept":
            # Accept: run the pending action (action_id comes from the agent's
            # message, not the sim) and substitute the templated post-execute
            # message. Force one more agent turn so its confirmation is recorded.
            pa = store.pending_actions.get(prior_card["action_id"])
            if pa is not None:
                exec_result = execute_pending_action(prior_card["action_id"], store)
                user_text = render_post_execute_message(pa, exec_result, store)
                effective_kind = "message"

        user_msg = HumanMessage(content=user_text)
        history.append(user_msg)

        if effective_kind == "end":
            if on_event:
                on_event(TurnEvent(turn=turn, user=user_text, ended=True))
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
                    user=user_text,
                    agent=_agent_final_text(new_msgs),
                    tool_calls=_extract_tool_events(new_msgs),
                )
            )

        # If the agent escalated this turn, stop driving the conversation —
        # the simulator has nothing useful left to add and burns turns/tokens
        # roleplaying a hold queue. The agent has already emitted its
        # standard "YOU ARE BEING TRANSFERRED..." message inside this same
        # invoke (the ReAct loop continues until a final AIMessage with no
        # tool_calls).
        if any(
            isinstance(m, AIMessage)
            and any(
                (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None))
                == "transfer_to_human_agents"
                for tc in (getattr(m, "tool_calls", None) or [])
            )
            for m in new_msgs
        ):
            terminated_by = "transferred"
            break

    transcript = [_serialize_message(m) for m in history]
    return RunResult(
        task_id=task_id,
        transcript=transcript,
        turn_count=turn,
        terminated_by=terminated_by,
        store_snapshot=store.snapshot(),
        agent_response_times_ms=agent_response_times_ms,
    )
