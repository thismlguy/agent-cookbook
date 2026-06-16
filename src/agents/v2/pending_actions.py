"""Pending-action store + execute helper for v2.

v2 splits every policy-loaded write into:
  1. An eligibility-check tool the orchestrator (LLM) calls; on success it
     stashes a typed `Pending*` row keyed by `action_id`.
  2. A structural `execute_pending_action` step invoked by the UI's Accept
     button (or the eval runner after the sim echoes a confirmation_card
     tag). The LLM never invokes execute — that's load-bearing.

Rows store identifiers only — no denormalized fares, formatted times, or
display labels. Frontends re-read the store at render time;
`execute()` re-reads at write time. See `src/agents/v2/architecture.md`.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from src.domain.store import Store


# ───────────────────────── shared typed primitives ─────────────────────────


class FlightRef(BaseModel):
    """Pointer to a (flight_number, date) row in `store.flights`."""

    model_config = ConfigDict(extra="forbid")

    flight_number: str = Field(
        description="Flight number from search_route results (e.g., 'HAT287')."
    )
    date: str = Field(
        description="ISO date 'YYYY-MM-DD'; (flight_number, date) must exist in the flights DB with status='available'."
    )


class PendingPassenger(BaseModel):
    """Per-booking passenger details (not the same as a user's saved passenger)."""

    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(description="Passenger first name.")
    last_name: str = Field(description="Passenger last name.")
    dob: str = Field(
        description="Date of birth, ISO 'YYYY-MM-DD'. Asked per booking; NOT taken from the user profile."
    )


class PaymentRef(BaseModel):
    """Pointer to a payment method on `store.users[user_id].payment_methods`."""

    model_config = ConfigDict(extra="forbid")

    payment_id: str = Field(
        description="Must be a payment_id already on the user's profile (cannot add new methods here)."
    )
    amount: int = Field(
        ge=0,
        description=(
            "Whole dollars charged to this payment method. The sum across all "
            "payment_methods must equal the total booking price "
            "(flights*passengers + $50/nonfree_bag + $30/passenger if insurance)."
        ),
    )


# ───────────────────────── pending-action rows ─────────────────────────


def new_action_id() -> str:
    """Short, URL-safe action id. Collisions are astronomically unlikely
    within a single per-session store."""
    return f"act_{secrets.token_hex(6)}"


class _PendingBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: Literal["pending", "executed", "cancelled"] = "pending"

    def write_call(self) -> tuple[str, dict[str, Any]]:
        """(write_tool_name, kwargs) this action commits when executed.

        Single source of truth for the underlying v0 write: `execute()` invokes
        it, and the runner logs it into the transcript so the judge can see the
        structural write (tool name + args) that v2 keeps off the LLM surface.
        Overridden per kind.
        """
        raise NotImplementedError  # pragma: no cover - overridden

    def execute(self, store: Store) -> dict[str, Any]:
        """Run the underlying v0 write tool. Shared across kinds via write_call()."""
        from src.agents.v0.tools import make_tools as _v1_make_tools

        name, args = self.write_call()
        tool = {t.name: t for t in _v1_make_tools(store)}[name]
        return tool.invoke(args)


class PendingBook(_PendingBase):
    kind: Literal["book"] = "book"
    user_id: str
    origin: str
    destination: str
    flight_type: Literal["one_way", "round_trip"]
    cabin: Literal["basic_economy", "economy", "business"]
    flights: list[FlightRef]
    passengers: list[PendingPassenger]
    payment_methods: list[PaymentRef]
    total_baggages: int
    nonfree_baggages: int
    insurance: Literal["yes", "no"]

    def write_call(self) -> tuple[str, dict[str, Any]]:
        return "book_reservation", {
            "user_id": self.user_id,
            "origin": self.origin,
            "destination": self.destination,
            "flight_type": self.flight_type,
            "cabin": self.cabin,
            "flights": [f.model_dump() for f in self.flights],
            "passengers": [p.model_dump() for p in self.passengers],
            "payment_methods": [pm.model_dump() for pm in self.payment_methods],
            "total_baggages": self.total_baggages,
            "nonfree_baggages": self.nonfree_baggages,
            "insurance": self.insurance,
        }


class PendingCancel(_PendingBase):
    kind: Literal["cancel"] = "cancel"
    reservation_id: str

    def write_call(self) -> tuple[str, dict[str, Any]]:
        return "cancel_reservation", {"reservation_id": self.reservation_id}


class PendingModifyFlights(_PendingBase):
    kind: Literal["modify_flights"] = "modify_flights"
    reservation_id: str
    cabin: Literal["basic_economy", "economy", "business"]
    flights: list[FlightRef]
    payment_id: str
    # Charge (>0) or refund (<0) vs the reservation's current price, computed by
    # the specialist at eligibility time so the card can show the cost before the
    # write. The write tool recomputes the authoritative delta independently.
    price_delta: int = 0

    def write_call(self) -> tuple[str, dict[str, Any]]:
        return "update_reservation_flights", {
            "reservation_id": self.reservation_id,
            "cabin": self.cabin,
            "flights": [f.model_dump() for f in self.flights],
            "payment_id": self.payment_id,
        }


class PendingModifyBaggage(_PendingBase):
    kind: Literal["modify_baggage"] = "modify_baggage"
    reservation_id: str
    total_baggages: int
    nonfree_baggages: int
    payment_id: str
    # Charge for added paid bags vs the reservation's current paid-bag count,
    # computed by the specialist at eligibility time (see PendingModifyFlights).
    price_delta: int = 0

    def write_call(self) -> tuple[str, dict[str, Any]]:
        return "update_reservation_baggages", {
            "reservation_id": self.reservation_id,
            "total_baggages": self.total_baggages,
            "nonfree_baggages": self.nonfree_baggages,
            "payment_id": self.payment_id,
        }


class PendingModifyPassengers(_PendingBase):
    kind: Literal["modify_passengers"] = "modify_passengers"
    reservation_id: str
    passengers: list[PendingPassenger]

    def write_call(self) -> tuple[str, dict[str, Any]]:
        return "update_reservation_passengers", {
            "reservation_id": self.reservation_id,
            "passengers": [p.model_dump() for p in self.passengers],
        }


PendingAction = Annotated[
    Union[
        PendingBook,
        PendingCancel,
        PendingModifyFlights,
        PendingModifyBaggage,
        PendingModifyPassengers,
    ],
    Field(discriminator="kind"),
]


# ───────────────────────── execute step ─────────────────────────


def _err(msg: str) -> dict[str, Any]:
    return {"ok": False, "error": msg}


def execute_pending_action(action_id: str, store: Store) -> dict[str, Any]:
    """Run a pending action's underlying write tool.

    Not registered as a LangChain tool — only the UI Accept-button handler
    (production) and the eval runner (on confirmation_card echo) call this.
    """
    pa = store.pending_actions.get(action_id)  # type: ignore[attr-defined]
    if pa is None:
        return _err(f"no pending action with id '{action_id}'")
    if pa.status != "pending":
        return _err(f"action '{action_id}' is already {pa.status}")
    result = pa.execute(store)
    # the underlying write tools return either a dict or a string starting with
    # "Error:". Treat the error-string case as a failed write and don't flip status.
    if isinstance(result, str) and result.startswith("Error:"):
        return _err(result.removeprefix("Error: "))
    pa.status = "executed"
    return {"ok": True, "kind": pa.kind, "result": result}


# ───────────────────────── templated post-execute messages ─────────────────────────


def _payment_label(store: Store, user_id: str | None, payment_id: str) -> str:
    """Render a human-friendly label for a payment method, e.g. 'gift card ending 4567'."""
    if user_id is None:
        return payment_id
    user = store.users.get(user_id)
    if user is None:
        return payment_id
    pm = user.payment_methods.get(payment_id)
    if pm is None:
        return payment_id
    source = pm.source.replace("_", " ")
    if pm.last_four:
        return f"{source} ending {pm.last_four}"
    return source


def _flights_summary(flights: list[FlightRef]) -> str:
    return ", ".join(f"{f.flight_number} on {f.date}" for f in flights)


def render_post_execute_message(
    pa: PendingAction, exec_result: dict[str, Any], store: Store
) -> str:
    """One templated user message per pending kind (plus an error template).

    Called by the UI/runner after `execute_pending_action` returns; the
    string is appended as the next user turn so the orchestrator's reply
    can phrase a natural-language confirmation.
    """
    if not exec_result.get("ok"):
        return f"Action could not complete: {exec_result.get('error', 'unknown error')}."

    inner = exec_result.get("result", {})

    if pa.kind == "book":
        rid = inner.get("reservation_id", "?")
        route = f"{pa.origin}→{pa.destination}"
        n = len(pa.passengers)
        total = sum(pm.amount for pm in pa.payment_methods)
        pm_label = (
            _payment_label(store, pa.user_id, pa.payment_methods[0].payment_id)
            if pa.payment_methods
            else "the selected payment method"
        )
        return (
            f"Confirmed booking. Reservation {rid} created: {route} on "
            f"{_flights_summary(pa.flights)}, {n} passenger(s), ${total} "
            f"charged to {pm_label}."
        )

    if pa.kind == "cancel":
        refunds = inner.get("refunds") or []
        refund_total = sum(int(r.get("amount", 0)) for r in refunds)
        # find a representative payment method
        pm_label = (
            _payment_label(
                store,
                store.reservations.get(pa.reservation_id).user_id
                if store.reservations.get(pa.reservation_id)
                else None,
                refunds[0]["payment_id"],
            )
            if refunds
            else "the original payment methods"
        )
        return (
            f"Confirmed cancellation. Reservation {pa.reservation_id} cancelled; "
            f"${refund_total} refunded to {pm_label}."
        )

    if pa.kind == "modify_flights":
        # delta is whatever was appended to payment_history this turn — easiest
        # to read it from the returned reservation if present
        r = store.reservations.get(pa.reservation_id)
        delta = 0
        if r and r.payment_history:
            delta = int(r.payment_history[-1].amount)
        verb = "charged" if delta > 0 else ("refunded" if delta < 0 else "no change")
        pm_label = _payment_label(
            store, r.user_id if r else None, pa.payment_id
        )
        return (
            f"Confirmed change. Reservation {pa.reservation_id} updated to "
            f"{_flights_summary(pa.flights)}; ${abs(delta)} {verb} on {pm_label}."
        )

    if pa.kind == "modify_baggage":
        r = store.reservations.get(pa.reservation_id)
        delta = 0
        if r and r.payment_history:
            delta = int(r.payment_history[-1].amount)
        pm_label = _payment_label(
            store, r.user_id if r else None, pa.payment_id
        )
        return (
            f"Confirmed baggage update on reservation {pa.reservation_id}: "
            f"{pa.total_baggages} bags ({pa.nonfree_baggages} paid); "
            f"${abs(delta)} charged on {pm_label}."
        )

    if pa.kind == "modify_passengers":
        names = ", ".join(f"{p.first_name} {p.last_name}" for p in pa.passengers)
        return (
            f"Confirmed passenger update on reservation {pa.reservation_id}: "
            f"{names}."
        )

    return f"Confirmed {pa.kind} on action {pa.action_id}."  # pragma: no cover


def render_card_summary(pa: PendingAction, store: Store) -> str:
    """Human-readable PRE-execute proposal for a pending action.

    This is what the confirmation card renders for the user (and what the eval
    runner shows the simulator) BEFORE they accept — it must surface the cost so
    a user with a price threshold can decide. Distinct from
    `render_post_execute_message`, which describes an action that already ran.
    Unlike that function, the `book` summary renders the FULL payment split.
    """
    r = store.reservations.get(getattr(pa, "reservation_id", "")) if pa.kind != "book" else None

    if pa.kind == "book":
        total = sum(pm.amount for pm in pa.payment_methods)
        split = "; ".join(
            f"${pm.amount} to {_payment_label(store, pa.user_id, pm.payment_id)}"
            for pm in pa.payment_methods
        )
        return (
            f"[Confirmation requested] Book {pa.origin}→{pa.destination} on "
            f"{_flights_summary(pa.flights)}, {pa.cabin}, {len(pa.passengers)} "
            f"passenger(s). Total ${total} ({split})."
        )

    if pa.kind == "cancel":
        route = f"{r.origin}→{r.destination}" if r else "?"
        return (
            f"[Confirmation requested] Cancel reservation {pa.reservation_id} "
            f"({route}); any refund returns to your original payment methods."
        )

    if pa.kind == "modify_flights":
        pm_label = _payment_label(store, r.user_id if r else None, pa.payment_id)
        cost = _delta_phrase(pa.price_delta, pm_label)
        return (
            f"[Confirmation requested] Change reservation {pa.reservation_id} to "
            f"{pa.cabin} on {_flights_summary(pa.flights)}; {cost}."
        )

    if pa.kind == "modify_baggage":
        pm_label = _payment_label(store, r.user_id if r else None, pa.payment_id)
        cost = _delta_phrase(pa.price_delta, pm_label)
        return (
            f"[Confirmation requested] Update baggage on reservation "
            f"{pa.reservation_id}: {pa.total_baggages} bags "
            f"({pa.nonfree_baggages} paid); {cost}."
        )

    if pa.kind == "modify_passengers":
        names = ", ".join(f"{p.first_name} {p.last_name}" for p in pa.passengers)
        return (
            f"[Confirmation requested] Update passengers on reservation "
            f"{pa.reservation_id}: {names}; no charge."
        )

    return f"[Confirmation requested] {pa.kind} on reservation {getattr(pa, 'reservation_id', '?')}."  # pragma: no cover


def _delta_phrase(delta: int, pm_label: str) -> str:
    """'$80 charged to ...' / '$80 refunded to ...' / 'no price change'."""
    if delta > 0:
        return f"${delta} charged to {pm_label}"
    if delta < 0:
        return f"${abs(delta)} refunded to {pm_label}"
    return "no price change"


# Re-exported so other v2 modules can construct rows without a circular import path.
__all__ = [
    "FlightRef",
    "PendingPassenger",
    "PaymentRef",
    "PendingAction",
    "PendingBook",
    "PendingCancel",
    "PendingModifyFlights",
    "PendingModifyBaggage",
    "PendingModifyPassengers",
    "execute_pending_action",
    "new_action_id",
    "render_post_execute_message",
    "render_card_summary",
]
