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
    """Return {action_id, kind} for the FIRST confirmation_card tag in `text`, else None."""
    cards = _extract_all_cards(text)
    return cards[0] if cards else None


def _extract_all_cards(text: str) -> list[dict[str, str]]:
    """Every confirmation_card tag in `text`, in document order."""
    cards: list[dict[str, str]] = []
    if not text:
        return cards
    for m in _CARD_RE.finditer(text):
        attrs = dict(_ATTR_RE.findall(m.group("attrs")))
        if "action_id" in attrs:
            cards.append({"action_id": attrs["action_id"], "kind": attrs.get("kind", "")})
    return cards


def _open_card(history: list[BaseMessage], store: Store) -> dict[str, str] | None:
    """The confirmation card currently awaiting the user, or None.

    A card is 'open' while its pending action is still status=='pending'. We scan
    agent messages newest-first (and within a message in document order) so the
    most recently proposed, still-unexecuted card wins. This keeps a card
    acceptable even when it was bundled with an already-executed sibling, or was
    presented a few turns ago because the user paused or pushed back — the cases
    that silently stranded multi-write tasks when only the immediately-preceding
    message was inspected.
    """
    for m in reversed(history):
        if isinstance(m, AIMessage):
            for card in _extract_all_cards(_visible_text(m.content)):
                pa = store.pending_actions.get(card["action_id"])
                if pa is not None and getattr(pa, "status", None) == "pending":
                    return card
    return None


def _surface_open_card(
    sim_history: list[BaseMessage], open_pa: Any, store: Store
) -> list[BaseMessage]:
    """Append the open card's `[Confirmation requested]` summary to the last agent
    turn in the sim-facing view, so the simulator keeps seeing a pending proposal
    it can accept/reject even after a tag-free agent reply. Sim view only — the
    real history is untouched. No-op if the summary is already shown."""
    summary = render_card_summary(open_pa, store)
    for i in range(len(sim_history) - 1, -1, -1):
        m = sim_history[i]
        if isinstance(m, AIMessage):
            text = _visible_text(m.content)
            if summary in text:
                return sim_history
            new = list(sim_history)
            new[i] = AIMessage(content=f"{text}\n\n{summary}")
            return new
    return sim_history


def _render_cards_for_sim(history: list[BaseMessage], store: Store) -> list[BaseMessage]:
    """Sim-facing copy of history: strip each agent turn to its visible text
    (dropping thinking/signature blocks) and expand any `<confirmation_card/>`
    tag into a human-readable proposal summary (route, cost, payment split).

    The production UI renders the card so the user sees what they're confirming;
    in eval the runner is that UI. The REAL history (fed to the agent and written
    to the transcript) keeps the bare tag — only this sim-facing copy is changed.
    Plain-string, tag-free agent turns pass through untouched.
    """
    rendered: list[BaseMessage] = []
    for m in history:
        if isinstance(m, AIMessage):
            text = _visible_text(m.content)

            def _expand(match: "re.Match[str]") -> str:
                attrs = dict(_ATTR_RE.findall(match.group("attrs")))
                action_id = attrs.get("action_id")
                pa = store.pending_actions.get(action_id) if action_id else None
                return render_card_summary(pa, store) if pa is not None else match.group(0)

            new_text = _CARD_RE.sub(_expand, text)
            # Rebuild only when we actually changed something (an expanded card or
            # a non-string content we flattened); plain unchanged strings pass through.
            if not isinstance(m.content, str) or new_text != m.content:
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
        entry: dict[str, Any] = {"role": "agent", "content": _visible_text(m.content)}
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


def _visible_text(content: Any) -> str:
    """The user-visible text of a message.

    Thinking-enabled models (e.g. Sonnet) return content as a list of blocks —
    a `thinking` block carrying an encrypted `signature`, plus the actual
    `text` block. Keep only the text blocks so transcripts, the judge, and the
    simulator see the agent's words, not the encrypted reasoning blob. Plain
    string content passes through unchanged (Haiku, no thinking)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                parts.append(block["text"])
        return "".join(parts)
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
            return _visible_text(m.content)
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
    # Structural writes (executed via execute_pending_action, off the LLM tool
    # surface) recorded for judge visibility: (history_index_to_insert_after, entry).
    executed_writes: list[tuple[int, dict[str, Any]]] = []
    turn = 0
    terminated_by: TerminatedBy
    while True:
        turn += 1
        if turn > max_turns:
            terminated_by = "max_turns"
            break

        # Build the sim-facing view: strip agent thinking/signature blocks to
        # visible text, and (v2) expand any <confirmation_card/> tag into a
        # rendered proposal so the sim sees what it's confirming. The real
        # history keeps the bare tag; the sim decides via `card_action` — no
        # fragile verbatim id echo. A no-op for plain tag-free string turns.
        sim_history = _render_cards_for_sim(history, store)
        # The 'open' card is whichever pending action is still awaiting the user,
        # not merely one tagged in the immediately-preceding message. Keep showing
        # it to the sim so a bundled or paused-on card stays acceptable.
        open_card = _open_card(history, store)
        open_pa = store.pending_actions.get(open_card["action_id"]) if open_card else None
        if open_pa is not None:
            sim_history = _surface_open_card(sim_history, open_pa, store)

        user_turn: UserTurn = simulator(sim_history)
        user_text = user_turn.text
        effective_kind = user_turn.kind

        if open_card is not None and open_pa is not None and user_turn.card_action == "accept":
            # Accept: run the pending action (action_id comes from the agent's
            # message, not the sim) and substitute the templated post-execute
            # message. Force one more agent turn so its confirmation is recorded.
            exec_result = execute_pending_action(open_card["action_id"], store)
            user_text = render_post_execute_message(open_pa, exec_result, store)
            effective_kind = "message"
            if exec_result.get("ok"):
                # Log the structural write so the judge sees the tool + its args
                # (e.g. the per-reservation payment_id) — it never hit the LLM
                # tool surface. Insert after the templated user turn appended next.
                _name, _args = open_pa.write_call()
                executed_writes.append(
                    (
                        len(history),
                        {
                            "role": "tool",
                            "name": _name,
                            "args": _args,
                            "content": _stringify(exec_result.get("result")),
                        },
                    )
                )

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

    writes_by_index: dict[int, list[dict[str, Any]]] = {}
    for idx, rec in executed_writes:
        writes_by_index.setdefault(idx, []).append(rec)
    transcript: list[dict[str, Any]] = []
    for i, m in enumerate(history):
        transcript.append(_serialize_message(m))
        for rec in writes_by_index.get(i, []):
            transcript.append(rec)
    return RunResult(
        task_id=task_id,
        transcript=transcript,
        turn_count=turn,
        terminated_by=terminated_by,
        store_snapshot=store.snapshot(),
        agent_response_times_ms=agent_response_times_ms,
    )
