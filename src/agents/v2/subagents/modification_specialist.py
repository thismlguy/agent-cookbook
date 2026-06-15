"""Modification specialist — encodes policy.md <modification> sub-sections.

Four sub-kinds:
  - "flights"     → update_reservation_flights
  - "cabin"       → update_reservation_flights with new cabin
  - "baggage"     → update_reservation_baggages  (add-only)
  - "passengers"  → update_reservation_passengers  (count fixed)
"""
from __future__ import annotations

from src.agents.v2.pending_actions import (
    PendingModifyBaggage,
    PendingModifyFlights,
    PendingModifyPassengers,
    new_action_id,
)
from src.agents.v2.subagents.cancellation_specialist import (
    _flight_already_flown,
)
from src.agents.v2.subagents.schemas import (
    Deny,
    ModificationInput,
    ReadyToAct,
    SpecialistResponse,
)
from src.domain.store import Store


def _legs_total(store: Store, legs, cabin: str) -> int | None:
    """Sum the cabin price of each leg from the flights DB; None if any is
    missing (date unavailable / no price for the cabin). Each leg needs
    `.flight_number` and `.date`."""
    total = 0
    for leg in legs:
        flight = store.flights.get(leg.flight_number)
        if flight is None:
            return None
        ds = flight.dates.get(leg.date)
        if ds is None or ds.prices is None:
            return None
        price = getattr(ds.prices, cabin, None)
        if price is None:
            return None
        total += int(price)
    return total


def _flights_delta(store: Store, reservation, new_legs, cabin: str) -> int:
    """Charge(+)/refund(-) for swapping `reservation`'s flights to `new_legs` at
    `cabin`, vs its current per-leg prices. 0 if new prices can't be resolved."""
    new_total = _legs_total(store, new_legs, cabin)
    if new_total is None:
        return 0
    old_total = sum(int(leg.price) for leg in reservation.flights)
    return new_total - old_total


def modification_specialist(
    input: ModificationInput, store: Store
) -> SpecialistResponse:
    r = store.reservations.get(input.reservation_id)
    if r is None:
        return Deny(reason=f"reservation '{input.reservation_id}' not found")

    if input.change_kind == "flights":
        if input.new_flights is None or input.payment_id is None:
            return Deny(
                reason="modify flights requires `new_flights` and `payment_id`"
            )
        if r.cabin == "basic_economy":
            return Deny(reason="basic economy flights cannot be modified")
        # origin/destination/trip_type cannot change — must use cancel + new booking
        if input.new_flights:
            first_origin = None
            last_destination = None
            for leg in input.new_flights:
                f = store.flights.get(leg.flight_number)
                if f is None:
                    return Deny(reason=f"flight '{leg.flight_number}' not found")
                if first_origin is None:
                    first_origin = f.origin
                last_destination = f.destination
            # round trips return home; one-way ends at the destination
            expected_last = r.origin if r.flight_type == "round_trip" else r.destination
            if first_origin != r.origin or last_destination != expected_last:
                return Deny(
                    reason=(
                        "origin and destination cannot be modified — "
                        "cancel and rebook instead"
                    )
                )
        pa = PendingModifyFlights(
            action_id=new_action_id(),
            reservation_id=input.reservation_id,
            cabin=r.cabin,  # cabin change uses sub-kind "cabin"; here cabin stays
            flights=list(input.new_flights),
            payment_id=input.payment_id,
            price_delta=_flights_delta(store, r, input.new_flights, r.cabin),
        )
        store.pending_actions[pa.action_id] = pa
        return ReadyToAct(action_id=pa.action_id)

    if input.change_kind == "cabin":
        if input.new_cabin is None or input.payment_id is None:
            return Deny(
                reason="cabin change requires `new_cabin` and `payment_id`"
            )
        for leg in r.flights:
            if _flight_already_flown(store, leg.flight_number, leg.date):
                return Deny(
                    reason=(
                        "cabin cannot be changed once any flight in the "
                        "reservation has been flown"
                    )
                )
        pa = PendingModifyFlights(
            action_id=new_action_id(),
            reservation_id=input.reservation_id,
            cabin=input.new_cabin,
            flights=[
                __import__(
                    "src.agents.v2.pending_actions", fromlist=["FlightRef"]
                ).FlightRef(flight_number=leg.flight_number, date=leg.date)
                for leg in r.flights
            ],
            payment_id=input.payment_id,
            price_delta=_flights_delta(store, r, r.flights, input.new_cabin),
        )
        store.pending_actions[pa.action_id] = pa
        return ReadyToAct(action_id=pa.action_id)

    if input.change_kind == "baggage":
        if (
            input.total_baggages is None
            or input.nonfree_baggages is None
            or input.payment_id is None
        ):
            return Deny(
                reason=(
                    "baggage change requires `total_baggages`, "
                    "`nonfree_baggages`, and `payment_id`"
                )
            )
        if input.total_baggages < r.total_baggages:
            return Deny(reason="can only add bags, not remove")
        pa = PendingModifyBaggage(
            action_id=new_action_id(),
            reservation_id=input.reservation_id,
            total_baggages=int(input.total_baggages),
            nonfree_baggages=int(input.nonfree_baggages),
            payment_id=input.payment_id,
            price_delta=(int(input.nonfree_baggages) - r.nonfree_baggages) * 50,
        )
        store.pending_actions[pa.action_id] = pa
        return ReadyToAct(action_id=pa.action_id)

    if input.change_kind == "passengers":
        if input.new_passengers is None:
            return Deny(reason="passenger change requires `new_passengers`")
        if len(input.new_passengers) != len(r.passengers):
            return Deny(
                reason=(
                    "the number of passengers cannot be changed; even a human "
                    "agent cannot do this"
                )
            )
        pa = PendingModifyPassengers(
            action_id=new_action_id(),
            reservation_id=input.reservation_id,
            passengers=list(input.new_passengers),
        )
        store.pending_actions[pa.action_id] = pa
        return ReadyToAct(action_id=pa.action_id)

    return Deny(reason=f"unknown change_kind '{input.change_kind}'")
