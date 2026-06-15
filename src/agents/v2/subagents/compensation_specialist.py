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

from src.agents.v2.subagents.schemas import (
    CompensationDeny,
    CompensationInput,
    CompensationOffer,
    CompensationResponse,
)
from src.domain.store import Store


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
