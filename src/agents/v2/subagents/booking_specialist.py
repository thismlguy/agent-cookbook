"""Booking specialist — encodes policy.md <booking> as pure code.

Rules enforced here:
  - 1 to 5 passengers
  - cabin uniform across all flight segments (enforced by the LLM at gather
    time; the specialist re-checks the cabin literal is one of the three)
  - payment methods all live on the user's profile
  - allowed payment-method mix: ≤1 travel_certificate + ≤1 credit_card +
    ≤3 gift_cards
  - all referenced flight/date rows exist and are available
  - payment amounts sum to the price of (flights × passengers) + extras
"""
from __future__ import annotations

from src.agents.v2.pending_actions import (
    PendingBook,
    new_action_id,
)
from src.agents.v2.subagents.baggage import (
    EXTRA_BAG_FEE_USD,
    free_allowance_per_passenger,
)
from src.agents.v2.subagents.schemas import (
    BookingInput,
    Deny,
    ReadyToAct,
    SpecialistResponse,
)
from src.domain.store import Store


def booking_specialist(input: BookingInput, store: Store) -> SpecialistResponse:
    user = store.users.get(input.user_id)
    if user is None:
        return Deny(reason=f"user '{input.user_id}' not found")

    if not 1 <= len(input.passengers) <= 5:
        return Deny(
            reason=(
                "a reservation can have at most 5 passengers; "
                f"got {len(input.passengers)}"
            )
        )

    # all payment methods must exist on the user's profile
    for pm in input.payment_methods:
        if pm.payment_id not in user.payment_methods:
            return Deny(
                reason=f"payment method '{pm.payment_id}' is not on user '{input.user_id}' profile"
            )

    # allowed mix: ≤1 travel certificate + ≤1 credit_card + ≤3 gift_cards
    counts = {"certificate": 0, "credit_card": 0, "gift_card": 0}
    for pm in input.payment_methods:
        method = user.payment_methods[pm.payment_id]
        counts[method.source] = counts.get(method.source, 0) + 1
    if counts["certificate"] > 1 or counts["credit_card"] > 1 or counts["gift_card"] > 3:
        return Deny(
            reason=(
                "payment methods exceed the allowed mix: at most 1 travel "
                "certificate, 1 credit card, and 3 gift cards"
            )
        )

    # compute total price from store
    total_price = 0
    for leg in input.flights:
        flight = store.flights.get(leg.flight_number)
        if flight is None:
            return Deny(reason=f"flight '{leg.flight_number}' not found")
        ds = flight.dates.get(leg.date)
        if ds is None or ds.status != "available":
            return Deny(
                reason=f"flight '{leg.flight_number}' is not available on {leg.date}"
            )
        if ds.prices is None:
            return Deny(
                reason=f"flight '{leg.flight_number}' on {leg.date} has no price information"
            )
        price = getattr(ds.prices, input.cabin, None)
        if price is None:
            return Deny(
                reason=f"no price for cabin '{input.cabin}' on flight '{leg.flight_number}' {leg.date}"
            )
        total_price += int(price) * len(input.passengers)

    # Baggage pricing is policy-DERIVED, not taken from the LLM. The free
    # allowance is a function of (membership, cabin, passenger_count); any bag
    # beyond it is a $50 paid bag. We compute the paid-bag count here so the
    # orchestrator cannot undercharge by miscounting free bags — book_reservation
    # itself does no baggage pricing, so this is the only guard. The LLM's
    # `nonfree_baggages` input is advisory and intentionally ignored.
    free_per_pax = free_allowance_per_passenger(user.membership, input.cabin)
    if free_per_pax is None:
        return Deny(
            reason=f"no baggage rule for membership='{user.membership}', cabin='{input.cabin}'"
        )
    free_total = free_per_pax * len(input.passengers)
    paid_bags = max(0, int(input.total_baggages) - free_total)
    total_price += EXTRA_BAG_FEE_USD * paid_bags
    if input.insurance == "yes":
        total_price += 30 * len(input.passengers)

    paid = sum(pm.amount for pm in input.payment_methods)
    if paid != total_price:
        return Deny(
            reason=(
                f"payment amounts (${paid}) must total the booking price (${total_price})"
            )
        )

    # eligible — construct and stash the pending row
    pa = PendingBook(
        action_id=new_action_id(),
        user_id=input.user_id,
        origin=input.origin,
        destination=input.destination,
        flight_type=input.flight_type,
        cabin=input.cabin,
        flights=list(input.flights),
        passengers=list(input.passengers),
        payment_methods=list(input.payment_methods),
        total_baggages=int(input.total_baggages),
        nonfree_baggages=paid_bags,
        insurance=input.insurance,
    )
    store.pending_actions[pa.action_id] = pa
    return ReadyToAct(action_id=pa.action_id)
