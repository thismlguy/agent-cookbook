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
    PendingCancel,
    PendingModifyFlights,
    PendingPassenger,
    render_card_summary,
)
import importlib

# The subagents package re-exports `booking_specialist` (the function), which
# shadows the submodule attribute — so fetch the real module from sys.modules to
# monkeypatch its `new_action_id`.
_booking_mod = importlib.import_module("src.agents.v2.subagents.booking_specialist")
_cancel_mod = importlib.import_module("src.agents.v2.subagents.cancellation_specialist")
from src.config import DB_PATH
from src.domain.store import Store
from src.runner.runner import (
    _open_card,
    _render_cards_for_sim,
    _serialize_message,
    _surface_open_card,
    _visible_text,
    run_task,
)
from src.sim.schemas import UserTurn


def _id_sequence(ids):
    """A new_action_id() stand-in that hands out `ids` in order (deterministic
    action_ids so a test can name the cards the agent emits)."""
    it = iter(ids)
    return lambda: next(it)


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


def test_runner_executes_two_bundled_cards(monkeypatch):
    """Reproduces task 42: the agent bundles TWO confirmation cards in one
    message. Each accept must execute one — the second card stays acceptable even
    though it was never the immediately-preceding message's only/first card.
    Pre-fix, only the first card ever executed and the second was stranded.
    Also asserts the structural write is logged into the transcript (judge view)."""
    monkeypatch.setattr(_cancel_mod, "new_action_id", _id_sequence(["act_c1", "act_c2"]))
    agent_script = [
        AIMessage(
            content="",
            tool_calls=[
                _tc("check_cancellation_eligibility",
                    {"reservation_id": "4WQ150", "reason": "airline_cancelled"}, "c1"),
                _tc("check_cancellation_eligibility",
                    {"reservation_id": "VAAOXJ", "reason": "airline_cancelled"}, "c2"),
            ],
        ),
        AIMessage(
            content=(
                'Both are eligible — please confirm each. '
                '<confirmation_card action_id="act_c1" kind="cancel"/> '
                '<confirmation_card action_id="act_c2" kind="cancel"/>'
            )
        ),
        AIMessage(content="4WQ150 is cancelled. The second is still awaiting your confirmation."),
        AIMessage(content="VAAOXJ is cancelled too. Anything else?"),
    ]
    sim_turns = [
        UserTurn(kind="message", text="Cancel both 4WQ150 and VAAOXJ — duplicate bookings."),
        UserTurn(kind="message", text="", card_action="accept"),
        UserTurn(kind="message", text="", card_action="accept"),
        UserTurn(kind="end", text="thanks"),
    ]

    result = run_task(
        task={"id": "t-bundled", "user_scenario": {}},
        agent_id="v2",
        agent_llm=ScriptedChatModel(responses=agent_script),
        sim_llm=_ScriptedSimLLM(sim_turns),
        max_turns=10,
    )

    # Both writes executed: two templated confirmations, both reservations gone
    # from the store (cancel_reservation removes them).
    user_texts = [e["content"] for e in result.transcript if e["role"] == "user"]
    assert sum("Confirmed cancellation." in t for t in user_texts) == 2
    reservations = result.store_snapshot["reservations"]
    assert "4WQ150" not in reservations and "VAAOXJ" not in reservations
    # Fix 2: each structural write is logged as a tool entry the judge can see.
    cancel_writes = [
        e for e in result.transcript
        if e.get("role") == "tool" and e.get("name") == "cancel_reservation"
    ]
    written_ids = {e["args"]["reservation_id"] for e in cancel_writes}
    assert written_ids == {"4WQ150", "VAAOXJ"}


def test_runner_executes_card_after_pushback(monkeypatch):
    """Reproduces task 11: the user doesn't accept on the turn right after the
    card — they ask a question first, the agent replies in prose (no tag), and
    only then accepts. The card from two turns ago must still execute."""
    monkeypatch.setattr(_cancel_mod, "new_action_id", _id_sequence(["act_c1"]))
    agent_script = [
        AIMessage(content="",
                  tool_calls=[_tc("check_cancellation_eligibility",
                                  {"reservation_id": "4WQ150", "reason": "airline_cancelled"}, "c1")]),
        AIMessage(content='Eligible. <confirmation_card action_id="act_c1" kind="cancel"/>'),
        AIMessage(content="The refund returns to your original payment method."),  # prose, no tag
        AIMessage(content="Done — 4WQ150 is cancelled. Anything else?"),
    ]
    sim_turns = [
        UserTurn(kind="message", text="Cancel 4WQ150."),
        UserTurn(kind="message", text="Wait — what's the refund amount?"),  # card_action=None
        UserTurn(kind="message", text="Ok, go ahead.", card_action="accept"),
        UserTurn(kind="end", text="bye"),
    ]

    result = run_task(
        task={"id": "t-pushback", "user_scenario": {}},
        agent_id="v2",
        agent_llm=ScriptedChatModel(responses=agent_script),
        sim_llm=_ScriptedSimLLM(sim_turns),
        max_turns=10,
    )

    user_texts = [e["content"] for e in result.transcript if e["role"] == "user"]
    assert any("Confirmed cancellation." in t for t in user_texts)  # stale card still executed
    assert "4WQ150" not in result.store_snapshot["reservations"]


def test_open_card_and_surface_handle_stale_bundled():
    """Unit: _open_card returns the most-recent still-pending card even when it's
    the 2nd card of a bundle / not in the last message, and _surface_open_card
    re-shows it to the sim view."""
    store = Store.load_from_path(DB_PATH)
    store.pending_actions["a1"] = PendingCancel(action_id="a1", reservation_id="R1")
    store.pending_actions["a2"] = PendingCancel(action_id="a2", reservation_id="R2")
    history = [
        HumanMessage(content="cancel both"),
        AIMessage(content='Confirm each: <confirmation_card action_id="a1" kind="cancel"/> '
                          '<confirmation_card action_id="a2" kind="cancel"/>'),
        AIMessage(content="R1 cancelled."),  # tag-free follow-up
    ]
    store.pending_actions["a1"].status = "executed"  # first already ran

    open_card = _open_card(history, store)
    assert open_card is not None and open_card["action_id"] == "a2"  # stale+bundled, still open

    sim_view = _surface_open_card(_render_cards_for_sim(history, store),
                                  store.pending_actions["a2"], store)
    assert "[Confirmation requested]" in sim_view[-1].content  # re-surfaced on last agent turn

    # When nothing is pending, _open_card is None.
    store.pending_actions["a2"].status = "executed"
    assert _open_card(history, store) is None


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


def test_cabin_change_refund_is_passenger_multiplied():
    """policy.md: a cabin change charges/refunds the fare difference for EVERY
    passenger (all share the same flights/cabin). GV1N64 is business→basic_economy
    with 3 passengers; per-passenger diff is -$1748, so the refund must be -$5244.
    The specialist's card delta and the authoritative write must agree.
    Regression for the per-passenger (non-multiplied) bug in data/CHANGES.md."""
    from src.agents.v0.tools import make_tools
    from src.agents.v2.subagents.modification_specialist import modification_specialist
    from src.agents.v2.subagents.schemas import ModificationInput

    store = Store.load_from_path(DB_PATH)
    r = store.reservations["GV1N64"]
    assert r.cabin == "business" and len(r.passengers) == 3  # guard the fixture
    payment_id = next(iter(store.users[r.user_id].payment_methods))

    # specialist card delta
    resp = modification_specialist(
        ModificationInput(reservation_id="GV1N64", change_kind="cabin",
                          new_cabin="basic_economy", payment_id=payment_id),
        store,
    )
    assert store.pending_actions[resp.action_id].price_delta == -5244

    # authoritative write records the same amount
    store2 = Store.load_from_path(DB_PATH)
    flights = [{"flight_number": f.flight_number, "date": f.date}
               for f in store2.reservations["GV1N64"].flights]
    tools = {t.name: t for t in make_tools(store2)}
    out = tools["update_reservation_flights"].invoke(
        {"reservation_id": "GV1N64", "cabin": "basic_economy",
         "flights": flights, "payment_id": payment_id}
    )
    assert out["payment_history"][-1]["amount"] == -5244


def test_modify_baggage_derives_free_allowance():
    """Baggage modification derives the paid-bag count from the free allowance
    (membership x cabin x passengers), ignoring the LLM's nonfree_baggages —
    mirroring booking_specialist. Regression for tasks 22/33 (charged for bags
    that should be free). 4WQ150 is silver/business x3 = 9 free bags, so adding
    up to 8 stays free even if the LLM claims they're all paid."""
    from src.agents.v2.subagents.modification_specialist import modification_specialist
    from src.agents.v2.subagents.schemas import ModificationInput

    store = Store.load_from_path(DB_PATH)
    pid = next(iter(store.users[store.reservations["4WQ150"].user_id].payment_methods))
    resp = modification_specialist(
        ModificationInput(
            reservation_id="4WQ150", change_kind="baggage",
            total_baggages=8, nonfree_baggages=8,  # LLM claims all 8 are paid
            payment_id=pid,
        ),
        store,
    )
    pa = store.pending_actions[resp.action_id]
    assert pa.nonfree_baggages == 0  # 8 <= 9 free → none paid, LLM input ignored
    assert pa.price_delta == 0  # no charge for bags within the free allowance


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
