"""Specialist input + response schemas for v2.

Inputs are validated by each `check_*_eligibility` tool wrapper before
the specialist function runs. Responses are discriminated unions on
`status` (mirrors the protocol described in
`src/agents/v2/architecture.md`).
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from src.agents.v2.pending_actions import (
    FlightRef,
    PaymentRef,
    PendingPassenger,
)


# ───────────────────────── generic response shapes ─────────────────────────


class ReadyToAct(BaseModel):
    """The specialist confirmed eligibility and stashed a pending row."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready_to_act"] = "ready_to_act"
    action_id: str


class Deny(BaseModel):
    """In-scope policy rejection. The orchestrator relays `reason` to the user."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["deny"] = "deny"
    reason: str


class TransferRequired(BaseModel):
    """Out-of-scope or already-flown — orchestrator must call transfer_to_human_agents."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["transfer_required"] = "transfer_required"
    reason: str


SpecialistResponse = Union[ReadyToAct, Deny, TransferRequired]


# ───────────────────────── compensation responses (asymmetric) ─────────────────────────


class CompensationOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["offer"] = "offer"
    amount: int
    reason: str


class CompensationDeny(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["deny"] = "deny"
    reason: str


CompensationResponse = Union[CompensationOffer, CompensationDeny]


# ───────────────────────── per-specialist input models ─────────────────────────


class BookingInput(BaseModel):
    """Proposed booking. Reservation is eligible iff:
    1 ≤ passengers ≤ 5; cabin uniform across all flights; payment mix
    ≤1 travel certificate + ≤1 credit card + ≤3 gift cards; all
    payment_ids on user profile; payment_methods sum equals
    (flights × passengers) + $50 × nonfree_baggages + $30 × passengers (if insurance).
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(
        description="The user's user_id (verified via get_user_details earlier in the turn)."
    )
    origin: str = Field(description="Origin airport code (e.g., 'SFO').")
    destination: str = Field(
        description=(
            "Farthest point of the trip. For a round_trip, the return leg "
            "ends back at `origin` — set `destination` to the apex airport."
        )
    )
    flight_type: Literal["one_way", "round_trip"] = Field(
        description="one_way: one outbound leg; round_trip: outbound + return ending at origin."
    )
    cabin: Literal["basic_economy", "economy", "business"] = Field(
        description=(
            "Single cabin applied uniformly to ALL flight segments. "
            "basic_economy is a distinct class from economy."
        )
    )
    flights: list[FlightRef] = Field(
        min_length=1,
        description=(
            "Ordered list of legs. For round_trip the return leg is included. "
            "Each (flight_number, date) must be 'available' in the DB."
        ),
    )
    passengers: list[PendingPassenger] = Field(
        min_length=1,
        max_length=5,
        description=(
            "1 to 5 passengers — a reservation can have at most 5 even via a "
            "human agent. Each passenger needs first_name, last_name, dob."
        ),
    )
    payment_methods: list[PaymentRef] = Field(
        min_length=1,
        description=(
            "Allowed mix: at most 1 travel certificate + 1 credit card + 3 "
            "gift cards. Every payment_id must already exist on the user's "
            "profile. amounts must sum to the total booking price."
        ),
    )
    total_baggages: int = Field(
        ge=0,
        description=(
            "Total checked bags requested (free + paid). Do NOT add bags the "
            "user did not request. Free allowance per passenger is a function "
            "of membership × cabin; see baggage policy."
        ),
    )
    nonfree_baggages: int = Field(
        ge=0,
        description="Number of paid bags ($50 each). 0 if all bags are within the free allowance.",
    )
    insurance: Literal["yes", "no"] = Field(
        description=(
            "Travel insurance: $30 per passenger; enables full refund only for "
            "health/weather cancellation reasons. Ask the user explicitly."
        )
    )


class CancellationInput(BaseModel):
    """Cancellation request. Eligibility (ANY ONE qualifies):
    booked <24h ago; reason='airline_cancelled'; cabin='business';
    insurance='yes' AND reason ∈ {health, weather}. Reservations with
    any already-flown segment return transfer_required.
    """

    model_config = ConfigDict(extra="forbid")

    reservation_id: str = Field(
        description="The reservation_id (verified via get_reservation_details earlier in the turn)."
    )
    reason: Literal[
        "change_of_plan", "airline_cancelled", "health", "weather", "other"
    ] = Field(
        description=(
            "Cancellation reason as classified by you from the user's words. "
            "'airline_cancelled' qualifies regardless of cabin/insurance; "
            "'health'/'weather' qualify only when the reservation has insurance; "
            "'change_of_plan' / 'other' qualify only when cabin=business or booked <24h."
        )
    )


class ModificationInput(BaseModel):
    """Modification request. Conditional fields by `change_kind`:
      flights:    new_flights, payment_id (cabin stays the same; basic_economy is denied)
      cabin:      new_cabin, payment_id (any flown segment → denied)
      baggage:    total_baggages, nonfree_baggages, payment_id (add-only, not remove)
      passengers: new_passengers (count CANNOT change; even a human agent cannot)
    For flights, the route endpoints cannot change — first leg's origin must
    equal reservation.origin, and last leg's destination must equal
    reservation.destination (or reservation.origin for round_trip).
    """

    model_config = ConfigDict(extra="forbid")

    reservation_id: str = Field(
        description="The reservation_id being modified."
    )
    change_kind: Literal["flights", "cabin", "baggage", "passengers"] = Field(
        description=(
            "Which modification sub-kind. Determines which other fields you must "
            "populate. Insurance CANNOT be added after initial booking."
        )
    )
    new_flights: list[FlightRef] | None = Field(
        default=None,
        description=(
            "Required when change_kind='flights'. Replacement legs preserving the "
            "reservation's origin and destination endpoints."
        ),
    )
    new_cabin: Literal["basic_economy", "economy", "business"] | None = Field(
        default=None,
        description=(
            "Required when change_kind='cabin'. Applies uniformly across all "
            "segments and all passengers."
        ),
    )
    total_baggages: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Required when change_kind='baggage'. The NEW total bag count. "
            "Must be ≥ the current total — bags can only be added, not removed."
        ),
    )
    nonfree_baggages: int | None = Field(
        default=None,
        ge=0,
        description="Required when change_kind='baggage'. New count of paid bags ($50 each).",
    )
    new_passengers: list[PendingPassenger] | None = Field(
        default=None,
        description=(
            "Required when change_kind='passengers'. Length MUST equal the "
            "reservation's current passenger count — passenger count is fixed."
        ),
    )
    payment_id: str | None = Field(
        default=None,
        description=(
            "Required when change_kind is 'flights', 'cabin', or 'baggage' "
            "(for the price diff: charge or refund). A single gift_card OR "
            "credit_card from the user's profile."
        ),
    )


class CompensationInput(BaseModel):
    """Compensation eligibility check. Call ONLY when the user has explicitly
    asked for compensation — do not proactively offer.

    Eligibility (ANY ONE qualifies): membership ∈ {silver, gold}; insurance=yes;
    cabin=business.

    Amounts: cancelled_flight → $100 × passengers; delayed_flight (only if the
    user also changed or cancelled the reservation) → $50 × passengers.
    Compensation has no DB write — relay the result to the user verbally.
    """

    model_config = ConfigDict(extra="forbid")

    reservation_id: str = Field(
        description="The reservation_id the complaint is about (verify the user's claim against the DB first)."
    )
    complaint_kind: Literal["cancelled_flight", "delayed_flight", "other"] = Field(
        description=(
            "How you classify the user's complaint. 'other' (e.g., bad meal, "
            "rude staff) is always denied."
        )
    )
    change_or_cancel_done: bool = Field(
        default=False,
        description=(
            "Only meaningful when complaint_kind='delayed_flight'. True iff a "
            "modify or cancel was already executed in THIS session (i.e., a "
            "'Confirmed change' or 'Confirmed cancellation' templated message "
            "appears earlier in the conversation). The $50 delay gesture "
            "requires this; otherwise it's denied."
        ),
    )


__all__ = [
    "BookingInput",
    "CancellationInput",
    "ModificationInput",
    "CompensationInput",
    "ReadyToAct",
    "Deny",
    "TransferRequired",
    "SpecialistResponse",
    "CompensationOffer",
    "CompensationDeny",
    "CompensationResponse",
]
