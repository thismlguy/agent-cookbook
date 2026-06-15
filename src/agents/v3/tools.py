"""Orchestrator tool surface for v3 — exactly 9 LLM-callable tools.

Read tools (4):     get_user_details, get_reservation_details, search_route,
                    get_baggage_allowance
Specialist tools (4): check_{booking,modification,cancellation,compensation}_eligibility
Escape (1):          transfer_to_human_agents

NOT on the surface:
  - book_reservation, cancel_reservation, update_reservation_*  (writes
    happen via execute_pending_action, invoked by the UI/runner)
  - execute_pending_action itself
  - search_direct_flight (internal — used by search_route)
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool, tool

from src.agents.v3.subagents import (
    booking_specialist,
    cancellation_specialist,
    compensation_specialist,
    modification_specialist,
)
from src.agents.v3.subagents.schemas import (
    BookingInput,
    CancellationInput,
    CompensationInput,
    ModificationInput,
)
from src.domain.store import Store


def _err(msg: str) -> str:
    return f"Error: {msg}"


# Free baggage allowance per passenger, indexed by (membership, cabin).
# Source: data/policy.md <booking> "Free baggage allowance" table.
_BAGGAGE_TABLE: dict[str, dict[str, int]] = {
    "regular": {"basic_economy": 0, "economy": 1, "business": 2},
    "silver":  {"basic_economy": 1, "economy": 2, "business": 3},
    "gold":    {"basic_economy": 2, "economy": 3, "business": 4},
}


def make_tools(store: Store) -> list[StructuredTool]:
    """Build the 9 v3 orchestrator tools bound to a Store instance."""

    @tool
    def get_user_details(user_id: str) -> Any:
        """Look up a user profile by user_id.

        Returns name, contact info, payment methods, saved passengers,
        membership tier, and list of reservation_ids.
        """
        user = store.users.get(user_id)
        if user is None:
            return _err(f"user '{user_id}' not found")
        return user.model_dump()

    @tool
    def get_reservation_details(reservation_id: str) -> Any:
        """Look up a reservation by reservation_id.

        Returns the full reservation including flights, passengers,
        payment history, cabin class, baggage, and insurance status.
        """
        r = store.reservations.get(reservation_id)
        if r is None:
            return _err(f"reservation '{reservation_id}' not found")
        return r.model_dump()

    @tool
    def search_route(origin: str, destination: str, date: str) -> Any:
        """Find flights between origin and destination on a given date.

        Returns direct flights when available; otherwise returns
        one-stop options assembled by joining on any hub.
        Each result has flight_number(s), times, available seats, and prices.
        """
        directs: list[dict[str, Any]] = []
        for f in store.flights.values():
            if f.origin != origin or f.destination != destination:
                continue
            ds = f.dates.get(date)
            if ds is None or ds.status != "available":
                continue
            directs.append(
                {
                    "type": "direct",
                    "flight_number": f.flight_number,
                    "origin": f.origin,
                    "destination": f.destination,
                    "date": date,
                    "scheduled_departure_time_est": f.scheduled_departure_time_est,
                    "scheduled_arrival_time_est": f.scheduled_arrival_time_est,
                    "available_seats": (
                        ds.available_seats.model_dump() if ds.available_seats else None
                    ),
                    "prices": ds.prices.model_dump() if ds.prices else None,
                }
            )
        if directs:
            return directs

        # one-stop fallback
        legs1: list = []
        legs2: list = []
        for f in store.flights.values():
            ds = f.dates.get(date)
            if ds is None or ds.status != "available":
                continue
            if f.origin == origin:
                legs1.append((f, ds))
            if f.destination == destination:
                legs2.append((f, ds))
        stops: list[dict[str, Any]] = []
        for f1, ds1 in legs1:
            for f2, ds2 in legs2:
                if f1.destination == f2.origin and f1.flight_number != f2.flight_number:
                    stops.append(
                        {
                            "type": "one_stop",
                            "via": f1.destination,
                            "legs": [
                                {
                                    "flight_number": f1.flight_number,
                                    "origin": f1.origin,
                                    "destination": f1.destination,
                                    "date": date,
                                    "prices": ds1.prices.model_dump() if ds1.prices else None,
                                },
                                {
                                    "flight_number": f2.flight_number,
                                    "origin": f2.origin,
                                    "destination": f2.destination,
                                    "date": date,
                                    "prices": ds2.prices.model_dump() if ds2.prices else None,
                                },
                            ],
                        }
                    )
        return stops

    @tool
    def get_baggage_allowance(reservation_id: str) -> Any:
        """Compute the policy-defined free baggage allowance for a reservation.

        Use this for any user question about how many bags they can bring,
        free vs paid bags, or what their baggage limit is. The allowance is
        a deterministic function of (membership, cabin, passenger_count)
        per the airline's policy table — do NOT compute it yourself.

        Returns:
          {
            "reservation_id": "...",
            "membership": "regular" | "silver" | "gold",
            "cabin": "basic_economy" | "economy" | "business",
            "passenger_count": int,
            "free_per_passenger": int,
            "free_total": int,
            "current_total_baggages": int,    # already on the reservation
            "current_nonfree_baggages": int,
            "paid_extra_per_bag_usd": 50
          }
        """
        r = store.reservations.get(reservation_id)
        if r is None:
            return _err(f"reservation '{reservation_id}' not found")
        user = store.users.get(r.user_id)
        if user is None:
            return _err(f"user '{r.user_id}' on reservation not found")
        per_pax = _BAGGAGE_TABLE.get(user.membership, {}).get(r.cabin)
        if per_pax is None:
            return _err(
                f"no baggage rule for membership='{user.membership}', cabin='{r.cabin}'"
            )
        n_pax = len(r.passengers)
        return {
            "reservation_id": reservation_id,
            "membership": user.membership,
            "cabin": r.cabin,
            "passenger_count": n_pax,
            "free_per_passenger": per_pax,
            "free_total": per_pax * n_pax,
            "current_total_baggages": r.total_baggages,
            "current_nonfree_baggages": r.nonfree_baggages,
            "paid_extra_per_bag_usd": 50,
        }

    @tool(args_schema=BookingInput)
    def check_booking_eligibility(**kwargs: Any) -> Any:
        """Check whether a proposed booking is eligible under policy.

        Use this after you've gathered everything the user needs to book.
        Eligibility is decided in code from the inputs (see field
        descriptions for the per-field rules — passenger count 1-5,
        payment-method mix, payment-totals, etc.).

        Returns one of:
          {"status":"ready_to_act","action_id":"..."} — eligible. A pending
            booking row is stashed under action_id; reply with a brief
            intro + <confirmation_card action_id="..." kind="book"/>.
          {"status":"deny","reason":"..."} — in-scope policy denial; relay
            the reason to the user.
        """
        return booking_specialist(BookingInput(**kwargs), store).model_dump()

    @tool(args_schema=ModificationInput)
    def check_modification_eligibility(**kwargs: Any) -> Any:
        """Check eligibility for a reservation modification (4 sub-kinds).

        Pick `change_kind` from the user's intent and populate the matching
        conditional fields (see ModificationInput field descriptions for
        which fields each kind needs). Key rules per kind:
          - flights: basic_economy is denied; route endpoints cannot change.
          - cabin:   any already-flown segment denies the change.
          - baggage: bags can only be added, not removed.
          - passengers: count is fixed; only names/DOBs swap.

        Returns the same {"status": ...} shape as booking. On
        ready_to_act, emit a <confirmation_card kind="modify_..."/> tag.
        """
        return modification_specialist(ModificationInput(**kwargs), store).model_dump()

    @tool(args_schema=CancellationInput)
    def check_cancellation_eligibility(**kwargs: Any) -> Any:
        """Check whether a cancellation is allowed by policy.

        Classify the user's reason into one of the five categories (see
        field description). Eligibility (ANY ONE qualifies): booked <24h
        ago, airline_cancelled, business cabin, or insurance+(health|weather).
        Reservations with any already-flown segment force a transfer.

        Returns:
          {"status":"ready_to_act","action_id":"..."} — emit
            <confirmation_card action_id="..." kind="cancel"/>.
          {"status":"deny","reason":"..."} — in-scope denial; do NOT transfer.
          {"status":"transfer_required","reason":"..."} — call
            transfer_to_human_agents next.
        """
        return cancellation_specialist(CancellationInput(**kwargs), store).model_dump()

    @tool(args_schema=CompensationInput)
    def check_compensation_eligibility(**kwargs: Any) -> Any:
        """Check whether the user qualifies for a goodwill compensation offer.

        Call ONLY when the user has explicitly asked for compensation —
        do not proactively offer. Verify the user's claim (delay,
        cancellation, cabin, passenger count) against tool data before
        calling; correct false claims rather than acting on them.

        Returns:
          {"status":"offer","amount":N,"reason":"..."} — phrase the gesture
            to the user (no confirmation card needed — there is no DB write).
          {"status":"deny","reason":"..."} — relay the denial; do NOT transfer.
        """
        return compensation_specialist(CompensationInput(**kwargs), store).model_dump()

    @tool
    def transfer_to_human_agents(summary: str) -> Any:
        """Escalate the conversation to a human agent.

        `summary` is a short note for the human agent. Call only when a
        specialist returns transfer_required, the user explicitly asks
        for a supervisor, or the request is genuinely out of scope.
        """
        return {"status": "transferred", "summary": summary}

    return [
        get_user_details,
        get_reservation_details,
        search_route,
        get_baggage_allowance,
        check_booking_eligibility,
        check_modification_eligibility,
        check_cancellation_eligibility,
        check_compensation_eligibility,
        transfer_to_human_agents,
    ]
