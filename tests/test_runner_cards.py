"""Runner-level tests for the v2 confirmation-card protocol in eval.

Covers the structured accept/reject signal (no verbatim id echo), the
sim-facing card rendering, and v0 backward-compatibility. LLMs are faked;
the runner + v2 plumbing are real.
"""
from __future__ import annotations

from typing import Iterable

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.v2.pending_actions import (
    FlightRef,
    PaymentRef,
    PendingBook,
    PendingModifyFlights,
    PendingPassenger,
    render_card_summary,
)
import importlib

# The subagents package re-exports `booking_specialist` (the function), which
# shadows the submodule attribute — so fetch the real module from sys.modules to
# monkeypatch its `new_action_id`.
_booking_mod = importlib.import_module("src.agents.v2.subagents.booking_specialist")
from src.config import DB_PATH
from src.domain.store import Store
from src.runner.runner import _render_cards_for_sim, _serialize_message, _visible_text, run_task
from src.sim.schemas import UserTurn


class ScriptedChatModel(FakeMessagesListChatModel):
    """Fake agent model that satisfies create_agent's bind_tools call."""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


class _ScriptedSimLLM:
    """Minimal stand-in for the sim chat model: make_simulator only calls
    `.with_structured_output(...).invoke(messages)`, so we script UserTurns."""

    def __init__(self, turns: Iterable[UserTurn]) -> None:
        self._turns = list(turns)
        self._i = 0

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001
        return self

    def invoke(self, messages):  # noqa: ANN001
        turn = self._turns[min(self._i, len(self._turns) - 1)]
        self._i += 1
        return turn


def _booking_args() -> dict:
    store = Store.load_from_path(DB_PATH)
    user = store.users["lei_rossi_3206"]
    payment_id = next(iter(user.payment_methods))
    return {
        "user_id": "lei_rossi_3206",
        "origin": "CLT",
        "destination": "BOS",
        "flight_type": "one_way",
        "cabin": "economy",
        "flights": [{"flight_number": "HAT287", "date": "2024-05-25"}],
        "passengers": [
            {"first_name": "Lei", "last_name": "Rossi", "dob": "1990-01-01"},
            {"first_name": "Jordan", "last_name": "Rossi", "dob": "1992-05-15"},
        ],
        "payment_methods": [{"payment_id": payment_id, "amount": 342}],
        "total_baggages": 0,
        "nonfree_baggages": 0,
        "insurance": "no",
    }


def _tc(name: str, args: dict, id_: str) -> dict:
    return {"name": name, "args": args, "id": id_}


# ─────────────────────────── run_task integration ───────────────────────────


def test_runner_executes_pending_action_on_accept(monkeypatch):
    """A structured card_action='accept' executes the pending action using the
    action_id from the AGENT message — the sim never reproduces the id."""
    monkeypatch.setattr(_booking_mod, "new_action_id", lambda: "act_fixed")
    agent_script = [
        AIMessage(content="", tool_calls=[_tc("check_booking_eligibility", _booking_args(), "c1")]),
        AIMessage(content='Please confirm. <confirmation_card action_id="act_fixed" kind="book"/>'),
        AIMessage(content="All set — your reservation is booked. Anything else?"),
    ]
    sim_turns = [
        UserTurn(kind="message", text="I'd like to book CLT to BOS."),
        UserTurn(kind="message", text="", card_action="accept"),
        UserTurn(kind="end", text="thanks, that's all"),
    ]

    result = run_task(
        task={"id": "t-accept", "user_scenario": {}},
        agent_id="v2",
        agent_llm=ScriptedChatModel(responses=agent_script),
        sim_llm=_ScriptedSimLLM(sim_turns),
        max_turns=8,
    )

    assert result.terminated_by == "simulator_end"
    # The executed write surfaces as a templated user turn in the transcript;
    # render_post_execute_message only emits "Confirmed booking." on a successful
    # execute, so its presence proves the pending action ran.
    user_texts = [e["content"] for e in result.transcript if e["role"] == "user"]
    assert any("Confirmed booking." in t for t in user_texts)


def test_runner_does_not_execute_on_reject(monkeypatch):
    """card_action='reject' leaves the pending action untouched; the sim's
    pivot text passes through to the agent."""
    monkeypatch.setattr(_booking_mod, "new_action_id", lambda: "act_fixed")
    agent_script = [
        AIMessage(content="", tool_calls=[_tc("check_booking_eligibility", _booking_args(), "c1")]),
        AIMessage(content='Please confirm. <confirmation_card action_id="act_fixed" kind="book"/>'),
        AIMessage(content="No problem, I won't book it."),
    ]
    sim_turns = [
        UserTurn(kind="message", text="Book CLT to BOS."),
        UserTurn(kind="message", text="Actually, never mind.", card_action="reject"),
        UserTurn(kind="end", text="bye"),
    ]

    result = run_task(
        task={"id": "t-reject", "user_scenario": {}},
        agent_id="v2",
        agent_llm=ScriptedChatModel(responses=agent_script),
        sim_llm=_ScriptedSimLLM(sim_turns),
        max_turns=8,
    )

    user_texts = [e["content"] for e in result.transcript if e["role"] == "user"]
    assert not any("Confirmed booking." in t for t in user_texts)  # never executed
    assert any("never mind" in t.lower() for t in user_texts)  # pivot text passed through


def test_runner_v0_card_path_inert():
    """v0 never emits a card; the new sim-facing rendering + card_action are a
    no-op and the run completes normally."""
    agent_script = [AIMessage(content="Hello! How can I help you today?")]
    sim_turns = [
        UserTurn(kind="message", text="hi"),
        UserTurn(kind="end", text="never mind, bye"),
    ]

    result = run_task(
        task={"id": "t-v0", "user_scenario": {}},
        agent_id="v0",
        agent_llm=ScriptedChatModel(responses=agent_script),
        sim_llm=_ScriptedSimLLM(sim_turns),
        max_turns=8,
    )

    assert result.terminated_by == "simulator_end"
    assert not any("[Confirmation requested]" in e["content"] for e in result.transcript)


# ─────────────────────────── pure-function units ───────────────────────────


def test_render_card_summary_book_full_split():
    store = Store.load_from_path(DB_PATH)
    user = store.users["lei_rossi_3206"]
    pids = list(user.payment_methods)
    pa = PendingBook(
        action_id="act_x",
        user_id="lei_rossi_3206",
        origin="CLT",
        destination="BOS",
        flight_type="one_way",
        cabin="economy",
        flights=[FlightRef(flight_number="HAT287", date="2024-05-25")],
        passengers=[PendingPassenger(first_name="A", last_name="B", dob="1990-01-01")],
        payment_methods=[
            PaymentRef(payment_id=pids[0], amount=100),
            PaymentRef(payment_id=pids[1] if len(pids) > 1 else pids[0], amount=71),
        ],
        total_baggages=0,
        nonfree_baggages=0,
        insurance="no",
    )
    summary = render_card_summary(pa, store)
    assert "Total $171" in summary
    assert "$100 to" in summary and "$71 to" in summary  # full split, both methods


def test_render_card_summary_modify_shows_delta():
    store = Store.load_from_path(DB_PATH)
    pa = PendingModifyFlights(
        action_id="act_y",
        reservation_id="ZZZZZZ",
        cabin="economy",
        flights=[FlightRef(flight_number="HAT287", date="2024-05-25")],
        payment_id="gift_card_1",
        price_delta=-1587,
    )
    summary = render_card_summary(pa, store)
    assert "$1587 refunded" in summary


def test_render_cards_for_sim_expands_only_known_and_preserves_real():
    store = Store.load_from_path(DB_PATH)
    pa = PendingBook(
        action_id="act_known",
        user_id="lei_rossi_3206",
        origin="CLT",
        destination="BOS",
        flight_type="one_way",
        cabin="economy",
        flights=[FlightRef(flight_number="HAT287", date="2024-05-25")],
        passengers=[PendingPassenger(first_name="A", last_name="B", dob="1990-01-01")],
        payment_methods=[PaymentRef(payment_id=next(iter(store.users["lei_rossi_3206"].payment_methods)), amount=171)],
        total_baggages=0,
        nonfree_baggages=0,
        insurance="no",
    )
    store.pending_actions["act_known"] = pa

    history = [
        HumanMessage(content="book it"),
        AIMessage(content='Confirm: <confirmation_card action_id="act_known" kind="book"/>'),
        AIMessage(content='Stale: <confirmation_card action_id="act_missing" kind="book"/>'),
    ]
    sim_view = _render_cards_for_sim(history, store)

    assert "[Confirmation requested]" in sim_view[1].content  # known → expanded
    assert "confirmation_card" not in sim_view[1].content
    assert '<confirmation_card action_id="act_missing"' in sim_view[2].content  # unknown → left bare
    # Real history is untouched.
    assert '<confirmation_card action_id="act_known"' in history[1].content


def test_render_cards_for_sim_noop_without_tags():
    store = Store.load_from_path(DB_PATH)
    history = [HumanMessage(content="hi"), AIMessage(content="Hello there")]
    assert _render_cards_for_sim(history, store) == history


def test_userturn_card_action_defaults_none():
    assert UserTurn(kind="message", text="x").card_action is None
    assert UserTurn(kind="message", text="", card_action="accept").card_action == "accept"


# ─────────────────────── thinking-block transcript cleanup ───────────────────────

# A Sonnet-with-thinking agent turn: list of blocks (thinking+signature, then text).
_THINKING_CONTENT = [
    {"type": "thinking", "thinking": "Let me verify the user first.", "signature": "Ev4CCmUIDhgC_base64_blob_=="},
    {"type": "text", "text": "Could you share your user ID?"},
]


def test_visible_text_strips_thinking_and_signature():
    assert _visible_text(_THINKING_CONTENT) == "Could you share your user ID?"
    assert _visible_text("plain string") == "plain string"  # unchanged for non-thinking models
    assert _visible_text(None) == ""


def test_serialize_message_uses_visible_text():
    entry = _serialize_message(AIMessage(content=_THINKING_CONTENT))
    assert entry["content"] == "Could you share your user ID?"
    assert "signature" not in entry["content"]


def test_render_cards_for_sim_flattens_thinking_blocks():
    store = Store.load_from_path(DB_PATH)
    history = [HumanMessage(content="hi"), AIMessage(content=_THINKING_CONTENT)]
    sim_view = _render_cards_for_sim(history, store)
    assert sim_view[1].content == "Could you share your user ID?"
    assert "signature" not in sim_view[1].content
