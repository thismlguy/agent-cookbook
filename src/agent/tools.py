"""Airline tools — langchain @tool wrappers bound to a Store instance.

Tool names and argument shapes match the tau2-bench action contract in
data/tasks.json so recorded ground-truth action sequences can be replayed
against these tools. Docstrings are ours.
"""
from __future__ import annotations

import ast
import operator
import random
import string
from datetime import datetime
from typing import Any

from langchain_core.tools import StructuredTool, tool

from src.domain.schemas import (
    PaymentHistoryEntry,
    Passenger,
    Reservation,
    ReservationFlight,
)
from src.domain.store import Store

# ───────────────────────── safe arithmetic eval ─────────────────────────

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


def _eval_expression(expr: str) -> float:
    tree = ast.parse(expr, mode="eval")
    return _safe_eval(tree)


# ───────────────────────── helpers ─────────────────────────

_ID_ALPHABET = string.ascii_uppercase + string.digits


def _new_reservation_id(taken: set[str]) -> str:
    while True:
        rid = "".join(random.choices(_ID_ALPHABET, k=6))
        if rid not in taken:
            return rid


def _err(msg: str) -> str:
    return f"Error: {msg}"


# ───────────────────────── factory ─────────────────────────


def make_tools(store: Store) -> list[StructuredTool]:
    """Build the 10 tau2-aligned airline tools bound to a Store instance.

    Each Chainlit session gets its own Store and its own tool set, so
    mutations from one session do not leak into another.
    """

    @tool
    def get_user_details(user_id: str) -> Any:
        """Look up a user profile by user_id.

        Returns the user's name, contact info, payment methods on file,
        saved passengers, membership tier, and list of reservation ids.
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
        """Find direct flights for a given origin, destination, and date.

        Only flights with status 'available' on the requested date are
        returned. Each result includes flight_number, scheduled times,
        available seats per cabin, and prices per cabin.
        """
        results = []
        for f in store.flights.values():
            if f.origin != origin or f.destination != destination:
                continue
            ds = f.dates.get(date)
            if ds is None or ds.status != "available":
                continue
            results.append(
                {
                    "flight_number": f.flight_number,
                    "origin": f.origin,
                    "destination": f.destination,
                    "scheduled_departure_time_est": f.scheduled_departure_time_est,
                    "scheduled_arrival_time_est": f.scheduled_arrival_time_est,
                    "date": date,
                    "status": ds.status,
                    "available_seats": ds.available_seats.model_dump() if ds.available_seats else None,
                    "prices": ds.prices.model_dump() if ds.prices else None,
                }
            )
        return results

    @tool
    def calculate(expression: str) -> Any:
        """Evaluate a basic arithmetic expression.

        Supports +, -, *, /, //, %, **, and parentheses. Variables and
        function calls are not allowed. Returns the numeric result.
        """
        try:
            value = _eval_expression(expression)
        except Exception as e:
            return _err(f"could not evaluate expression: {e}")
        return {"expression": expression, "result": value}

    @tool
    def book_reservation(
        user_id: str,
        origin: str,
        destination: str,
        flight_type: str,
        cabin: str,
        flights: list[dict[str, str]],
        passengers: list[dict[str, str]],
        payment_methods: list[dict[str, Any]],
        total_baggages: int,
        nonfree_baggages: int,
        insurance: str,
    ) -> Any:
        """Create a new reservation for the user.

        `flights` is a list of {flight_number, date} objects in order.
        `passengers` is a list of {first_name, last_name, dob}.
        `payment_methods` is a list of {payment_id, amount} drawn from
        the user's saved payment methods on file.
        `insurance` is 'yes' or 'no'.
        Returns the created reservation including reservation_id.
        """
        user = store.users.get(user_id)
        if user is None:
            return _err(f"user '{user_id}' not found")

        # validate payment ids exist on the user's profile
        for pm in payment_methods:
            pid = pm.get("payment_id")
            if pid not in user.payment_methods:
                return _err(f"payment method '{pid}' is not on user '{user_id}' profile")

        # resolve prices from the flight DB
        resolved_flights: list[ReservationFlight] = []
        for leg in flights:
            fn = leg.get("flight_number")
            date = leg.get("date")
            flight = store.flights.get(fn) if fn else None
            if flight is None:
                return _err(f"flight '{fn}' not found")
            ds = flight.dates.get(date)
            if ds is None or ds.status != "available":
                return _err(f"flight '{fn}' is not available on {date}")
            if ds.prices is None:
                return _err(f"flight '{fn}' on {date} has no price information")
            price = getattr(ds.prices, cabin, None)
            if price is None:
                return _err(f"no price for cabin '{cabin}' on flight '{fn}' {date}")
            resolved_flights.append(
                ReservationFlight(
                    origin=flight.origin,
                    destination=flight.destination,
                    flight_number=fn,
                    date=date,
                    price=price,
                )
            )

        rid = _new_reservation_id(set(store.reservations.keys()))
        reservation = Reservation(
            reservation_id=rid,
            user_id=user_id,
            origin=origin,
            destination=destination,
            flight_type=flight_type,
            cabin=cabin,
            flights=resolved_flights,
            passengers=[Passenger(**p) for p in passengers],
            payment_history=[
                PaymentHistoryEntry(payment_id=pm["payment_id"], amount=pm["amount"])
                for pm in payment_methods
            ],
            created_at=datetime.utcnow().isoformat(timespec="seconds"),
            total_baggages=int(total_baggages),
            nonfree_baggages=int(nonfree_baggages),
            insurance=insurance,
        )
        store.reservations[rid] = reservation
        user.reservations.append(rid)
        return reservation.model_dump()

    @tool
    def update_reservation_flights(
        reservation_id: str,
        cabin: str,
        flights: list[dict[str, str]],
        payment_id: str,
    ) -> Any:
        """Replace the flights on an existing reservation.

        `cabin` applies to all flights (cabin must be uniform).
        `flights` is the new ordered list of {flight_number, date}.
        `payment_id` is used for any price difference (charge or refund).
        Returns the updated reservation.
        """
        r = store.reservations.get(reservation_id)
        if r is None:
            return _err(f"reservation '{reservation_id}' not found")
        user = store.users.get(r.user_id)
        if user is None or payment_id not in user.payment_methods:
            return _err(f"payment method '{payment_id}' is not on user profile")

        old_total = sum(int(f.price) for f in r.flights)
        new_flights: list[ReservationFlight] = []
        for leg in flights:
            fn = leg.get("flight_number")
            date = leg.get("date")
            flight = store.flights.get(fn) if fn else None
            if flight is None:
                return _err(f"flight '{fn}' not found")
            ds = flight.dates.get(date)
            if ds is None or ds.status != "available":
                return _err(f"flight '{fn}' is not available on {date}")
            if ds.prices is None:
                return _err(f"flight '{fn}' on {date} has no price information")
            price = getattr(ds.prices, cabin, None)
            if price is None:
                return _err(f"no price for cabin '{cabin}' on flight '{fn}' {date}")
            new_flights.append(
                ReservationFlight(
                    origin=flight.origin,
                    destination=flight.destination,
                    flight_number=fn,
                    date=date,
                    price=price,
                )
            )

        new_total = sum(int(f.price) for f in new_flights)
        diff = new_total - old_total
        r.flights = new_flights
        r.cabin = cabin
        if diff != 0:
            r.payment_history.append(PaymentHistoryEntry(payment_id=payment_id, amount=diff))
        return r.model_dump()

    @tool
    def update_reservation_baggages(
        reservation_id: str,
        total_baggages: int,
        nonfree_baggages: int,
        payment_id: str,
    ) -> Any:
        """Update the baggage counts on a reservation.

        `total_baggages` is the new total. `nonfree_baggages` is the new
        count of paid bags (charged at $50 each). `payment_id` is used
        for the differential charge.
        """
        r = store.reservations.get(reservation_id)
        if r is None:
            return _err(f"reservation '{reservation_id}' not found")
        user = store.users.get(r.user_id)
        if user is None or payment_id not in user.payment_methods:
            return _err(f"payment method '{payment_id}' is not on user profile")

        old_paid = r.nonfree_baggages
        r.total_baggages = int(total_baggages)
        r.nonfree_baggages = int(nonfree_baggages)
        diff = (r.nonfree_baggages - old_paid) * 50
        if diff != 0:
            r.payment_history.append(PaymentHistoryEntry(payment_id=payment_id, amount=diff))
        return r.model_dump()

    @tool
    def update_reservation_passengers(
        reservation_id: str,
        passengers: list[dict[str, str]],
    ) -> Any:
        """Replace the passengers list on a reservation.

        The number of passengers cannot change — only the names/DOBs of
        existing passenger slots. Returns the updated reservation.
        """
        r = store.reservations.get(reservation_id)
        if r is None:
            return _err(f"reservation '{reservation_id}' not found")
        if len(passengers) != len(r.passengers):
            return _err(
                f"passenger count cannot change (reservation has "
                f"{len(r.passengers)}, got {len(passengers)})"
            )
        r.passengers = [Passenger(**p) for p in passengers]
        return r.model_dump()

    @tool
    def cancel_reservation(reservation_id: str) -> Any:
        """Cancel a reservation and refund payment history to original methods.

        Removes the reservation from the user's profile. Returns a
        confirmation with the refund summary.
        """
        r = store.reservations.pop(reservation_id, None)
        if r is None:
            return _err(f"reservation '{reservation_id}' not found")
        user = store.users.get(r.user_id)
        if user and reservation_id in user.reservations:
            user.reservations.remove(reservation_id)
        refunds = [{"payment_id": p.payment_id, "amount": p.amount} for p in r.payment_history]
        return {
            "reservation_id": reservation_id,
            "status": "cancelled",
            "refunds": refunds,
        }

    @tool
    def transfer_to_human_agents(summary: str) -> Any:
        """Transfer the conversation to a human agent.

        Use only when the user's request cannot be handled within policy.
        `summary` is a short note for the human agent describing the
        situation.
        """
        return {"status": "transferred", "summary": summary}

    return [
        get_user_details,
        get_reservation_details,
        search_direct_flight,
        calculate,
        book_reservation,
        update_reservation_flights,
        update_reservation_baggages,
        update_reservation_passengers,
        cancel_reservation,
        transfer_to_human_agents,
    ]
