"""Orchestrator tool surface for v2 — exactly 10 LLM-callable tools.

Read tools (5):     get_user_details, get_reservation_details,
                    search_direct_flight, search_onestop_flight,
                    get_baggage_allowance
Specialist tools (4): check_{booking,modification,cancellation,compensation}_eligibility
Escape (1):          transfer_to_human_agents

NOT on the surface:
  - book_reservation, cancel_reservation, update_reservation_*  (writes
    happen via execute_pending_action, invoked by the UI/runner)
  - execute_pending_action itself

Search mirrors upstream tau2-bench: a nonstop search plus a separate
one-stop search (an earlier v2 merged them into one `search_route`, which hid
the direct/one-stop distinction and dropped per-leg times — see changes.md).
"""
from __future__ import annotations

from datetime import date as _date
from datetime import timedelta
from typing import Any

from langchain_core.tools import StructuredTool, tool

from src.agents.v2.subagents import (
    booking_specialist,
    cancellation_specialist,
    compensation_specialist,
    modification_specialist,
)
from src.agents.v2.subagents.baggage import (
    EXTRA_BAG_FEE_USD,
    free_allowance_per_passenger,
)
from src.agents.v2.subagents.schemas import (
    BookingInput,
    CancellationInput,
    CompensationInput,
    ModificationInput,
)
from src.domain.store import Store


def _err(msg: str) -> str:
    return f"Error: {msg}"


# ───────────────────────── flight-search helpers ─────────────────────────
# Module-level (take `store`) so search_direct_flight and search_onestop_flight
# share one result shape. Mirrors upstream tau2-bench search semantics.


def _next_day(date_str: str) -> str:
    y, m, d = (int(x) for x in date_str.split("-"))
    return (_date(y, m, d) + timedelta(days=1)).isoformat()


def _time_to_min(t: str | None) -> int | None:
    """Minutes-since-midnight for an 'HH:MM:SS' string, +1440 if it carries a
    '+1' overnight marker. None if unparseable."""
    if not t:
        return None
    extra = 1440 if "+1" in t else 0
    base = t.replace("+1", "").strip()
    parts = base.split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1]) + extra
    except ValueError:
        return None


def _abs_min(date_str: str, time_str: str | None) -> int | None:
    """Absolute minute timestamp = date_ordinal*1440 + time-of-day, so two
    legs on different dates can be subtracted to get elapsed duration."""
    tod = _time_to_min(time_str)
    if tod is None:
        return None
    y, m, d = (int(x) for x in date_str.split("-"))
    return _date(y, m, d).toordinal() * 1440 + tod


def _flight_dict(f: Any, ds: Any, date: str) -> dict[str, Any]:
    """One search result: times + per-cabin seats + per-cabin prices, plus the
    flight's elapsed gate-to-gate duration in minutes (so the agent can rank by
    speed without doing time arithmetic itself)."""
    dep = f.scheduled_departure_time_est
    arr = f.scheduled_arrival_time_est
    dep_min, arr_min = _time_to_min(dep), _time_to_min(arr)
    duration = arr_min - dep_min if dep_min is not None and arr_min is not None else None
    return {
        "flight_number": f.flight_number,
        "origin": f.origin,
        "destination": f.destination,
        "date": date,
        "status": ds.status,
        "scheduled_departure_time_est": dep,
        "scheduled_arrival_time_est": arr,
        "total_duration_min": duration,
        "available_seats": ds.available_seats.model_dump() if ds.available_seats else None,
        "prices": ds.prices.model_dump() if ds.prices else None,
    }


def _direct_flights(
    store: Store, origin: str, destination: str, date: str, leave_after: str | None = None
) -> list[dict[str, Any]]:
    """Available nonstops origin→destination on `date`. `leave_after` (an
    'HH:MM:SS' time) keeps only flights departing at/after it — used to assemble
    feasible connections."""
    out: list[dict[str, Any]] = []
    for f in store.flights.values():
        if f.origin != origin or f.destination != destination:
            continue
        ds = f.dates.get(date)
        if ds is None or ds.status != "available":
            continue
        if leave_after is not None and (f.scheduled_departure_time_est or "") < leave_after:
            continue
        out.append(_flight_dict(f, ds, date))
    return out


def _combine_prices(p1: Any, p2: Any) -> dict[str, int] | None:
    """Per-cabin total across two legs, for cabins priced on both."""
    if not p1 or not p2:
        return None
    return {
        c: p1[c] + p2[c]
        for c in p1
        if c in p2 and p1.get(c) is not None and p2.get(c) is not None
    }


def make_tools(store: Store) -> list[StructuredTool]:
    """Build the 10 v2 orchestrator tools bound to a Store instance."""

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
    def search_direct_flight(origin: str, destination: str, date: str) -> Any:
        """Find NONSTOP (direct) flights between two airports on a given date.

        Pass airport codes (e.g. 'JFK'), not city names. Returns every available
        nonstop, each with flight_number, scheduled departure/arrival times,
        total_duration_min (gate-to-gate minutes, for ranking by speed),
        available seats per cabin, and prices per cabin. Returns an empty list if
        no nonstop exists on that date — when that happens, try
        search_onestop_flight before telling the user the route is unavailable.
        """
        return _direct_flights(store, origin, destination, date)

    @tool
    def search_onestop_flight(origin: str, destination: str, date: str) -> Any:
        """Find ONE-STOP (single-connection) itineraries between two airports.

        Use when no suitable nonstop exists, or when the user wants more options
        to compare (e.g. 'cheapest' / 'second cheapest' / 'fastest'). Joins on any
        hub: each result is {via, legs: [leg1, leg2], total_duration_min, prices}
        where both legs are full flight records (times, seats, per-cabin prices),
        `total_duration_min` is the whole itinerary's elapsed minutes including the
        layover (rank by this for 'fastest'), and `prices` is the per-cabin total
        across both legs. Only feasible connections are returned — the second leg
        departs at/after the first leg arrives (and on the next day when the first
        leg lands after midnight).
        """
        options: list[dict[str, Any]] = []
        for f1 in store.flights.values():
            if f1.origin != origin or f1.destination in (origin, destination):
                continue
            ds1 = f1.dates.get(date)
            if ds1 is None or ds1.status != "available":
                continue
            hub = f1.destination
            arr = f1.scheduled_arrival_time_est or ""
            date2 = _next_day(date) if "+1" in arr else date
            leave_after = arr.replace("+1", "")
            leg1 = _flight_dict(f1, ds1, date)
            for leg2 in _direct_flights(store, hub, destination, date2, leave_after=leave_after):
                start = _abs_min(leg1["date"], leg1["scheduled_departure_time_est"])
                end = _abs_min(leg2["date"], leg2["scheduled_arrival_time_est"])
                options.append(
                    {
                        "type": "one_stop",
                        "via": hub,
                        "legs": [leg1, leg2],
                        # total elapsed incl. layover (leg1 departure → leg2 arrival)
                        "total_duration_min": (end - start)
                        if start is not None and end is not None
                        else None,
                        "prices": _combine_prices(leg1["prices"], leg2["prices"]),
                    }
                )
        return options

    @tool
    def get_baggage_allowance(
        reservation_id: str | None = None,
        user_id: str | None = None,
        cabin: str | None = None,
        passenger_count: int | None = None,
    ) -> Any:
        """Compute the policy-defined free baggage allowance.

        Use this for any "how many bags?" / free-vs-paid question, AND when
        booking to learn how many bags are free for the cabin the user is about
        to buy (so "use all my free allowance" maps to a concrete bag count). The
        allowance is a deterministic function of (membership, cabin,
        passenger_count) — do NOT compute it yourself.

        Two ways to call it:
          - existing reservation: pass `reservation_id`.
          - a not-yet-booked trip: pass `user_id` and `cabin` (and
            `passenger_count`, default 1) — the membership comes from the user.

        Returns: membership, cabin, passenger_count, free_per_passenger,
        free_total, paid_extra_per_bag_usd, and (reservation form only)
        current_total_baggages / current_nonfree_baggages.
        """
        if reservation_id is not None:
            r = store.reservations.get(reservation_id)
            if r is None:
                return _err(f"reservation '{reservation_id}' not found")
            user = store.users.get(r.user_id)
            if user is None:
                return _err(f"user '{r.user_id}' on reservation not found")
            membership, cabin_, n_pax = user.membership, r.cabin, len(r.passengers)
            current = {
                "current_total_baggages": r.total_baggages,
                "current_nonfree_baggages": r.nonfree_baggages,
            }
        else:
            if user_id is None or cabin is None:
                return _err(
                    "pass either `reservation_id`, or `user_id` and `cabin` "
                    "(for a not-yet-booked trip)"
                )
            user = store.users.get(user_id)
            if user is None:
                return _err(f"user '{user_id}' not found")
            membership, cabin_, n_pax = user.membership, cabin, passenger_count or 1
            current = {}

        per_pax = free_allowance_per_passenger(membership, cabin_)
        if per_pax is None:
            return _err(
                f"no baggage rule for membership='{membership}', cabin='{cabin_}'"
            )
        return {
            "reservation_id": reservation_id,
            "membership": membership,
            "cabin": cabin_,
            "passenger_count": n_pax,
            "free_per_passenger": per_pax,
            "free_total": per_pax * n_pax,
            **current,
            "paid_extra_per_bag_usd": EXTRA_BAG_FEE_USD,
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
        search_direct_flight,
        search_onestop_flight,
        get_baggage_allowance,
        check_booking_eligibility,
        check_modification_eligibility,
        check_cancellation_eligibility,
        check_compensation_eligibility,
        transfer_to_human_agents,
    ]
