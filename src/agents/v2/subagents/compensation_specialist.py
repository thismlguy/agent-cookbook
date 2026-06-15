"""Compensation specialist — the asymmetric flow.

No DB write, no pending action, no confirmation card. Returns either an
offer (amount + reason) or a deny (reason). The orchestrator phrases
the result to the user from the bare fields.

Eligibility (ANY ONE qualifies):
  - silver or gold membership
  - reservation.insurance == "yes"
  - reservation.cabin == "business"

Amounts:
  - cancelled_flight  → $100 × passengers
  - delayed_flight (only if user also changed/cancelled) → $50 × passengers
  - other             → no compensation
"""
from __future__ import annotations

from src.agents.v2.subagents.cancellation_specialist import _flight_already_flown
from src.agents.v2.subagents.schemas import (
    CompensationDeny,
    CompensationInput,
    CompensationOffer,
    CompensationResponse,
)
from src.domain.store import Store


def _has_cancelled_leg(store: Store, reservation) -> bool:
    """True iff any flight on the reservation is marked cancelled in the DB."""
    for leg in reservation.flights:
        flight = store.flights.get(leg.flight_number)
        if flight is None:
            continue
        ds = flight.dates.get(leg.date)
        if ds is not None and ds.status == "cancelled":
            return True
    return False


def _any_leg_departed(store: Store, reservation) -> bool:
    """True iff any flight on the reservation has actually departed.

    No tool exposes live flight status, so a delay can only be *confirmed*
    once a flight has departed (status flying/landed, or its scheduled time
    is in the past). A future flight cannot have been delayed.
    """
    return any(
        _flight_already_flown(store, leg.flight_number, leg.date)
        for leg in reservation.flights
    )


def compensation_specialist(
    input: CompensationInput, store: Store
) -> CompensationResponse:
    r = store.reservations.get(input.reservation_id)
    if r is None:
        return CompensationDeny(
            reason=f"reservation '{input.reservation_id}' not found"
        )
    user = store.users.get(r.user_id)
    if user is None:
        return CompensationDeny(reason=f"user for reservation '{input.reservation_id}' not found")

    qualifiers: list[str] = []
    if user.membership in ("silver", "gold"):
        qualifiers.append(f"membership={user.membership}")
    if r.insurance == "yes":
        qualifiers.append("has travel insurance")
    if r.cabin == "business":
        qualifiers.append("cabin=business")

    if not qualifiers:
        return CompensationDeny(
            reason=(
                f"regular member, no insurance, cabin={r.cabin}; none of the "
                "qualifying conditions met (silver/gold, insurance, or business cabin)"
            )
        )

    n = len(r.passengers)
    qualifier_str = ", ".join(qualifiers)

    if input.complaint_kind == "cancelled_flight":
        # Confirm the facts before offering (policy: "Always confirms the facts
        # before offering compensation"). A fabricated cancellation has no
        # cancelled leg in our records.
        if not _has_cancelled_leg(store, r):
            return CompensationDeny(
                reason=(
                    f"no flight in reservation {input.reservation_id} is cancelled "
                    "in our records; the cancellation claim cannot be confirmed"
                )
            )
        return CompensationOffer(
            amount=100 * n,
            reason=(
                f"cancelled flight; $100 × {n} passenger(s); qualifies via {qualifier_str}"
            ),
        )

    if input.complaint_kind == "delayed_flight":
        if not input.change_or_cancel_done:
            return CompensationDeny(
                reason=(
                    "delayed-flight gesture requires the user to also change "
                    "or cancel the reservation; not yet done"
                )
            )
        # Confirm the delay before offering: a flight that has not departed yet
        # cannot have been delayed.
        if not _any_leg_departed(store, r):
            return CompensationDeny(
                reason=(
                    f"no flight in reservation {input.reservation_id} has departed yet "
                    "(scheduled times are after the current time); the reported "
                    "delay cannot be confirmed"
                )
            )
        return CompensationOffer(
            amount=50 * n,
            reason=(
                f"delayed flight + change/cancel processed; $50 × {n} passenger(s); "
                f"qualifies via {qualifier_str}"
            ),
        )

    return CompensationDeny(
        reason="policy only covers compensation for cancelled or delayed flights"
    )
