"""End-to-end tests for the v3 agent — LLM mocked, plumbing real.

Each test scripts the AIMessage sequence the orchestrator should emit
and asserts on what the v3 plumbing did with it: specialist verdicts,
pending-action rows, store mutations, templated user messages, and
tool-call sequencing. No real LLM calls are made.

See `src/agents/v3/testing.md` for the case-by-case rationale.
"""
from __future__ import annotations

import re
from typing import Iterable

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from src.agents import get_variant
from src.agents.v3.pending_actions import (
    execute_pending_action,
    render_post_execute_message,
)
from src.config import DB_PATH
from src.domain.store import Store


class ScriptedChatModel(FakeMessagesListChatModel):
    """Fake chat model that satisfies create_react_agent's bind_tools call."""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


def _make_agent(store: Store, script: Iterable[AIMessage]):
    fake = ScriptedChatModel(responses=list(script))
    return get_variant("v3")(store, fake)


def _tool_call(name: str, args: dict, id_: str) -> dict:
    return {"name": name, "args": args, "id": id_}


def _drive(agent, history: list, expected_turns: int = 1) -> list:
    """Invoke the agent once and return the messages added this turn."""
    prev_len = len(history)
    result = agent.invoke({"messages": history})
    history[:] = list(result["messages"])
    return history[prev_len:]


def _find_card(text: str) -> dict[str, str] | None:
    m = re.search(r'<confirmation_card\s+([^>]*?)/>', text)
    if not m:
        return None
    attrs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', m.group(1)))
    return attrs if "action_id" in attrs else None


def _final_text(new_msgs: list) -> str:
    for m in reversed(new_msgs):
        if isinstance(m, AIMessage):
            return m.content if isinstance(m.content, str) else str(m.content)
    return ""


def _tool_calls(new_msgs: list) -> list[dict]:
    out = []
    for m in new_msgs:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                out.append({"name": tc.get("name"), "args": tc.get("args")})
    return out


# ─────────────────────────────── booking ───────────────────────────────


def test_booking_happy_path():
    """case 1 — eligible booking → confirmation_card → execute → reply."""
    store = Store.load_from_path(DB_PATH)
    # Use an existing user with a credit card; book HAT287 on 2024-05-25 economy.
    user_id = "lei_rossi_3206"
    user = store.users[user_id]
    payment_id = next(iter(user.payment_methods))

    # Compute expected price: HAT287 econ on 2024-05-25 = 171, × 2 passengers = 342
    booking_args = {
        "user_id": user_id,
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

    # Turn 1: tool_call → eligibility → emit confirmation_card
    # Turn 2: see templated user message → natural-language reply
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("check_booking_eligibility", booking_args, "c1")],
        ),
        AIMessage(
            content=(
                "Here's your booking summary — please review and confirm. "
                '<confirmation_card action_id="__ACTID__" kind="book"/>'
            )
        ),
        AIMessage(
            content="Your reservation is booked. Anything else I can help with?"
        ),
    ]

    agent = _make_agent(store, script)

    history: list = [HumanMessage(content="Book me a flight please.")]

    # Turn 1 drives the eligibility-check + reply with confirmation_card
    _drive(agent, history)
    # After turn 1, two AIMessages were consumed but our second AIMessage has
    # a placeholder action_id. We need to patch it to the real one from the
    # pending row before serializing. Let's check the store state instead:
    assert len(store.pending_actions) == 1
    action_id = next(iter(store.pending_actions))
    pa = store.pending_actions[action_id]
    assert pa.kind == "book"
    assert pa.status == "pending"

    # The scripted second AIMessage had a placeholder action_id; in a real
    # run the LLM would substitute the real id. Patch it in the history to
    # mimic that.
    for m in history:
        if isinstance(m, AIMessage) and "__ACTID__" in (m.content or ""):
            m.content = m.content.replace("__ACTID__", action_id)
            break

    last_agent = _final_text(history)
    card = _find_card(last_agent)
    assert card is not None and card["action_id"] == action_id
    assert card["kind"] == "book"

    # Simulate user accepting → runner-side: execute + templated message
    exec_result = execute_pending_action(action_id, store)
    assert exec_result["ok"] is True
    templated = render_post_execute_message(pa, exec_result, store)
    assert "Confirmed booking." in templated
    assert "Reservation " in templated
    # row flipped
    assert pa.status == "executed"
    # store now has the new reservation
    new_rid = exec_result["result"]["reservation_id"]
    assert new_rid in store.reservations
    assert templated.split("Reservation ")[1].split(" ")[0] == new_rid

    # Turn 2: orchestrator sees the templated message, replies in NL
    history.append(HumanMessage(content=templated))
    _drive(agent, history)
    final = _final_text(history)
    assert "reservation" in final.lower() or "booked" in final.lower()


def test_booking_deny_too_many_passengers():
    """case 2 — 6 passengers → Deny; no pending row, no card."""
    store = Store.load_from_path(DB_PATH)
    user_id = "lei_rossi_3206"
    user = store.users[user_id]
    payment_id = next(iter(user.payment_methods))

    booking_args = {
        "user_id": user_id,
        "origin": "CLT",
        "destination": "BOS",
        "flight_type": "one_way",
        "cabin": "economy",
        "flights": [{"flight_number": "HAT287", "date": "2024-05-25"}],
        "passengers": [
            {"first_name": f"P{i}", "last_name": "X", "dob": "1990-01-01"}
            for i in range(6)
        ],
        "payment_methods": [{"payment_id": payment_id, "amount": 999}],
        "total_baggages": 0,
        "nonfree_baggages": 0,
        "insurance": "no",
    }

    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("check_booking_eligibility", booking_args, "c1")],
        ),
        AIMessage(content="Sorry, we can only book up to 5 passengers per reservation."),
    ]

    agent = _make_agent(store, script)
    history: list = [HumanMessage(content="Book a trip for 6.")]
    new_msgs = _drive(agent, history)

    assert len(store.pending_actions) == 0
    final = _final_text(history)
    assert _find_card(final) is None
    assert "5 passengers" in final or "5" in final
    # The 6-passenger payload is rejected at the Pydantic boundary (max_length=5)
    # before reaching the specialist. The tool result is a structured validation
    # error citing the constraint — a strictly better signal for the LLM than
    # the specialist's Deny string would have been.
    tool_msg = next(
        m for m in new_msgs if m.__class__.__name__ == "ToolMessage"
    )
    content = tool_msg.content
    assert "5" in content and ("most" in content or "deny" in content), content


# ─────────────────────────────── cancellation ───────────────────────────────


def test_cancellation_happy_path_business_cabin():
    """case 1 — business-cabin reservation cancels via confirmation card."""
    store = Store.load_from_path(DB_PATH)
    rid = "4WQ150"  # business cabin reservation found via probe
    assert store.reservations[rid].cabin == "business"

    script = [
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "check_cancellation_eligibility",
                    {"reservation_id": rid, "reason": "change_of_plan"},
                    "c1",
                )
            ],
        ),
        AIMessage(
            content=(
                "Here's your cancellation summary — please confirm. "
                '<confirmation_card action_id="__ACTID__" kind="cancel"/>'
            )
        ),
        AIMessage(content="Your cancellation is complete and the refund is on its way."),
    ]

    agent = _make_agent(store, script)
    history: list = [HumanMessage(content="Please cancel reservation 4WQ150.")]
    _drive(agent, history)

    assert len(store.pending_actions) == 1
    action_id, pa = next(iter(store.pending_actions.items()))
    assert pa.kind == "cancel"
    assert pa.reservation_id == rid

    # patch placeholder + simulate accept
    for m in history:
        if isinstance(m, AIMessage) and "__ACTID__" in (m.content or ""):
            m.content = m.content.replace("__ACTID__", action_id)
            break

    exec_result = execute_pending_action(action_id, store)
    assert exec_result["ok"] is True
    assert rid not in store.reservations  # cancelled removes it from store
    templated = render_post_execute_message(pa, exec_result, store)
    assert "Confirmed cancellation." in templated
    assert rid in templated
    assert "refunded" in templated
    assert pa.status == "executed"


def test_cancellation_transfer_required_already_flown():
    """case 2 — already-flown segment → TransferRequired → transfer tool call."""
    store = Store.load_from_path(DB_PATH)
    rid = "I6M8JQ"  # has HAT115/2024-05-09 with status=landed
    # verify the test fixture
    leg = store.reservations[rid].flights[0]
    assert store.flights[leg.flight_number].dates[leg.date].status == "landed"

    script = [
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "check_cancellation_eligibility",
                    {"reservation_id": rid, "reason": "change_of_plan"},
                    "c1",
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "transfer_to_human_agents",
                    {
                        "summary": (
                            f"reservation {rid} has a flown segment; requires human "
                            "agent to handle cancellation"
                        )
                    },
                    "c2",
                )
            ],
        ),
        AIMessage(content="YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."),
    ]

    agent = _make_agent(store, script)
    history: list = [HumanMessage(content=f"Cancel {rid}")]
    new_msgs = _drive(agent, history)

    calls = _tool_calls(new_msgs)
    names = [c["name"] for c in calls]
    assert names == ["check_cancellation_eligibility", "transfer_to_human_agents"]
    transfer_call = next(c for c in calls if c["name"] == "transfer_to_human_agents")
    assert rid in transfer_call["args"]["summary"]
    assert rid in store.reservations  # NOT cancelled
    assert store.reservations[rid].cabin  # still present
    # no pending cancel created
    assert all(pa.kind != "cancel" for pa in store.pending_actions.values())


# ─────────────────────────────── modification ───────────────────────────────


def test_modification_happy_path_flights():
    """case 1 — modify_flights happy path."""
    store = Store.load_from_path(DB_PATH)
    rid = "VAAOXJ"
    user = store.users[store.reservations[rid].user_id]
    payment_id = next(iter(user.payment_methods))
    new_flights = [
        {"flight_number": "HAT287", "date": "2024-05-25"},
        {"flight_number": "HAT235", "date": "2024-05-25"},
    ]

    args = {
        "reservation_id": rid,
        "change_kind": "flights",
        "new_flights": new_flights,
        "payment_id": payment_id,
    }
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("check_modification_eligibility", args, "c1")],
        ),
        AIMessage(
            content=(
                "Here's the proposed change — please confirm. "
                '<confirmation_card action_id="__ACTID__" kind="modify_flights"/>'
            )
        ),
        AIMessage(content="Done — your flight is updated."),
    ]

    agent = _make_agent(store, script)
    history: list = [HumanMessage(content=f"Change reservation {rid} to the 25th.")]
    _drive(agent, history)

    assert len(store.pending_actions) == 1
    action_id, pa = next(iter(store.pending_actions.items()))
    assert pa.kind == "modify_flights"

    exec_result = execute_pending_action(action_id, store)
    assert exec_result["ok"] is True
    r = store.reservations[rid]
    assert [(f.flight_number, f.date) for f in r.flights] == [
        ("HAT287", "2024-05-25"),
        ("HAT235", "2024-05-25"),
    ]
    templated = render_post_execute_message(pa, exec_result, store)
    assert "Confirmed change." in templated
    assert "HAT287" in templated
    assert pa.status == "executed"


def test_modification_cross_flow_pivot():
    """case 2 — modify→cancel pivot leaves modify pending, executes cancel."""
    store = Store.load_from_path(DB_PATH)
    rid = "4WQ150"  # business so cancel will be eligible
    user = store.users[store.reservations[rid].user_id]
    payment_id = next(iter(user.payment_methods))

    # 4WQ150 is a DFW→LAX round-trip; modify with alternates that preserve the
    # endpoints (DFW→LAX out, LAX→DFW back).
    new_flights = [
        {"flight_number": "HAT124", "date": "2024-05-22"},
        {"flight_number": "HAT022", "date": "2024-05-26"},
    ]
    modify_args = {
        "reservation_id": rid,
        "change_kind": "flights",
        "new_flights": new_flights,
        "payment_id": payment_id,
    }
    cancel_args = {"reservation_id": rid, "reason": "change_of_plan"}

    script = [
        # turn 1 — try modify
        AIMessage(
            content="",
            tool_calls=[
                _tool_call("check_modification_eligibility", modify_args, "c1")
            ],
        ),
        AIMessage(
            content=(
                "Here's the proposed change. "
                '<confirmation_card action_id="__ACTID_MOD__" kind="modify_flights"/>'
            )
        ),
        # turn 2 — user pivoted to cancel; orchestrator calls cancel
        AIMessage(
            content="",
            tool_calls=[
                _tool_call("check_cancellation_eligibility", cancel_args, "c2")
            ],
        ),
        AIMessage(
            content=(
                "Got it — here's the cancellation summary. "
                '<confirmation_card action_id="__ACTID_CAN__" kind="cancel"/>'
            )
        ),
        # turn 3 — confirmation of cancel
        AIMessage(content="Your reservation has been cancelled."),
    ]

    agent = _make_agent(store, script)
    history: list = [HumanMessage(content=f"Change reservation {rid}.")]
    _drive(agent, history)

    # After turn 1: one pending modify row
    assert len(store.pending_actions) == 1
    modify_id, modify_pa = next(iter(store.pending_actions.items()))
    assert modify_pa.kind == "modify_flights"

    # User pivots — no echo, just a new instruction
    history.append(HumanMessage(content="Actually just cancel it."))
    _drive(agent, history)

    # Now two pending rows; modify is still pending
    assert len(store.pending_actions) == 2
    cancel_entry = next(
        (aid, pa)
        for aid, pa in store.pending_actions.items()
        if pa.kind == "cancel"
    )
    cancel_id, cancel_pa = cancel_entry
    assert modify_pa.status == "pending"  # orphaned but not auto-cancelled

    # patch placeholder for cancel and accept it
    for m in history:
        if isinstance(m, AIMessage) and "__ACTID_CAN__" in (m.content or ""):
            m.content = m.content.replace("__ACTID_CAN__", cancel_id)

    exec_result = execute_pending_action(cancel_id, store)
    assert exec_result["ok"] is True
    assert cancel_pa.status == "executed"
    assert modify_pa.status == "pending"  # unaffected
    assert rid not in store.reservations

    # Verify only cancel_reservation fired — no update_reservation_flights
    # (we can check this by confirming the templated message is a cancel one)
    templated = render_post_execute_message(cancel_pa, exec_result, store)
    assert "Confirmed cancellation." in templated


# ─────────────────────────────── compensation ───────────────────────────────


def test_compensation_offer_silver_member():
    """case 1 — silver member, cancelled-flight complaint → offer."""
    store = Store.load_from_path(DB_PATH)
    rid = "4WQ150"  # silver user, business cabin (extra qualifier), 3 passengers
    n = len(store.reservations[rid].passengers)

    args = {
        "reservation_id": rid,
        "complaint_kind": "cancelled_flight",
        "change_or_cancel_done": False,
    }
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("check_compensation_eligibility", args, "c1")],
        ),
        AIMessage(
            content=(
                f"We can offer you a $${100 * n} travel certificate as a goodwill gesture."
            )
        ),
    ]
    agent = _make_agent(store, script)
    history: list = [HumanMessage(content="I want compensation for the cancellation.")]
    new_msgs = _drive(agent, history)

    # No pending row — compensation is the asymmetric flow
    assert len(store.pending_actions) == 0
    # No transfer call
    assert all(c["name"] != "transfer_to_human_agents" for c in _tool_calls(new_msgs))

    # The tool response carried the offer payload
    import json
    tool_msg = next(m for m in new_msgs if m.__class__.__name__ == "ToolMessage")
    payload = json.loads(tool_msg.content)
    assert payload["status"] == "offer"
    assert payload["amount"] == 100 * n
    assert "membership=silver" in payload["reason"] or "membership=gold" in payload["reason"]


def test_compensation_deny_regular_member():
    """case 2 — regular member, no insurance, non-business → deny."""
    store = Store.load_from_path(DB_PATH)
    rid = "VAAOXJ"  # regular, no insurance, economy
    args = {
        "reservation_id": rid,
        "complaint_kind": "cancelled_flight",
        "change_or_cancel_done": False,
    }
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("check_compensation_eligibility", args, "c1")],
        ),
        AIMessage(content="I'm sorry, this situation does not qualify for compensation."),
    ]
    agent = _make_agent(store, script)
    history: list = [HumanMessage(content="Compensation please.")]
    new_msgs = _drive(agent, history)

    assert len(store.pending_actions) == 0
    assert all(c["name"] != "transfer_to_human_agents" for c in _tool_calls(new_msgs))

    import json
    tool_msg = next(m for m in new_msgs if m.__class__.__name__ == "ToolMessage")
    payload = json.loads(tool_msg.content)
    assert payload["status"] == "deny"
    # The reason should reference the three failed qualifiers (membership,
    # insurance, cabin) — the specialist phrases membership as
    # "regular member" and lists the policy categories explicitly.
    reason = payload["reason"]
    assert "regular" in reason  # membership=regular
    assert "insurance" in reason
    assert "cabin" in reason
