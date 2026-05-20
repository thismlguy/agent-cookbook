"""Cancellation specialist — encodes policy.md <cancellation>.

  if any flight has already flown → transfer_required
  else if booked < 24h OR airline_cancelled OR business cabin OR
       (has insurance AND reason in {health, weather}):
      ready_to_act
  else:
      deny  (in-scope policy denial — NOT a transfer)
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.agents.v3.pending_actions import (
    PendingCancel,
    new_action_id,
)
from src.agents.v3.subagents.schemas import (
    CancellationInput,
    Deny,
    ReadyToAct,
    SpecialistResponse,
    TransferRequired,
)
from src.domain.store import Store

# Pinned to the canonical scenario time used in v1/v2 prompts so the
# eligibility math is deterministic regardless of wall-clock.
SCENARIO_NOW = datetime(2024, 5, 15, 15, 0, 0)


def _flight_already_flown(store: Store, flight_number: str, date_str: str) -> bool:
    flight = store.flights.get(flight_number)
    if flight is None:
        return False
    ds = flight.dates.get(date_str)
    if ds is not None and ds.status in ("landed", "flying"):
        return True
    # fallback: date string comparison against scenario time
    try:
        flight_date = datetime.fromisoformat(date_str)
    except ValueError:
        return False
    return flight_date.date() < SCENARIO_NOW.date()


def cancellation_specialist(
    input: CancellationInput, store: Store
) -> SpecialistResponse:
    r = store.reservations.get(input.reservation_id)
    if r is None:
        return Deny(reason=f"reservation '{input.reservation_id}' not found")

    # any-portion-flown → transfer (policy explicitly requires this)
    for leg in r.flights:
        if _flight_already_flown(store, leg.flight_number, leg.date):
            return TransferRequired(
                reason=(
                    f"reservation {input.reservation_id} has at least one flight "
                    f"that has already flown ({leg.flight_number} on {leg.date}); "
                    "policy requires transfer to a human agent"
                )
            )

    # ANY-ONE-qualifies eligibility
    qualifiers: list[str] = []
    try:
        created = datetime.fromisoformat(r.created_at)
    except ValueError:
        created = None
    if created is not None and SCENARIO_NOW - created < timedelta(hours=24):
        qualifiers.append("booked within last 24 hours")
    if input.reason == "airline_cancelled":
        qualifiers.append("airline-cancelled flight")
    if r.cabin == "business":
        qualifiers.append("cabin=business")
    if r.insurance == "yes" and input.reason in ("health", "weather"):
        qualifiers.append(f"insurance covers reason={input.reason}")

    if not qualifiers:
        return Deny(
            reason=(
                f"reservation {input.reservation_id} does not qualify for "
                "cancellation: outside 24-hour window, not airline-cancelled, "
                "cabin is not business, and no insurance-covered reason"
            )
        )

    pa = PendingCancel(
        action_id=new_action_id(),
        reservation_id=input.reservation_id,
    )
    store.pending_actions[pa.action_id] = pa
    return ReadyToAct(action_id=pa.action_id)
