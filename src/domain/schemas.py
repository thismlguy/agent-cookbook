"""Pydantic models for the airline domain — round-trip with data/db.json."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Permissive(BaseModel):
    model_config = ConfigDict(extra="allow")


class Name(_Permissive):
    first_name: str
    last_name: str


class Address(_Permissive):
    address1: str
    address2: str | None = None
    city: str
    country: str
    state: str
    zip: str


class Passenger(_Permissive):
    first_name: str
    last_name: str
    dob: str


class PaymentMethod(_Permissive):
    source: Literal["credit_card", "certificate", "gift_card"]
    id: str
    brand: str | None = None
    last_four: str | None = None
    amount: float | None = None


class User(_Permissive):
    user_id: str
    name: Name
    address: Address
    email: str
    dob: str
    payment_methods: dict[str, PaymentMethod]
    saved_passengers: list[Passenger] = []
    membership: Literal["regular", "silver", "gold"]
    reservations: list[str] = []


class CabinAvailability(_Permissive):
    basic_economy: int
    economy: int
    business: int


class FlightDateStatus(_Permissive):
    status: Literal["available", "landed", "cancelled", "delayed", "on time", "flying"]
    available_seats: CabinAvailability | None = None
    prices: CabinAvailability | None = None
    actual_departure_time_est: str | None = None
    actual_arrival_time_est: str | None = None


class Flight(_Permissive):
    flight_number: str
    origin: str
    destination: str
    scheduled_departure_time_est: str
    scheduled_arrival_time_est: str
    dates: dict[str, FlightDateStatus]


class ReservationFlight(_Permissive):
    origin: str
    destination: str
    flight_number: str
    date: str
    price: int | float


class PaymentHistoryEntry(_Permissive):
    payment_id: str
    amount: int | float


class Reservation(_Permissive):
    reservation_id: str
    user_id: str
    origin: str
    destination: str
    flight_type: Literal["one_way", "round_trip"]
    cabin: Literal["basic_economy", "economy", "business"]
    flights: list[ReservationFlight]
    passengers: list[Passenger]
    payment_history: list[PaymentHistoryEntry]
    created_at: str
    total_baggages: int
    nonfree_baggages: int
    insurance: Literal["yes", "no"]
