# Airline agent v2 — orchestrator + specialist subagents

v2 is the first version that **splits the agent into multiple agents**. v0
and v1 were single ReAct loops with progressively better prompts; the
shape v2 targets is *production with small/fast models*, where two
properties matter that v0/v1 don't optimize for:

1. **Per-call prompts must stay short.** Small models lose accuracy as
   prompt length and rule density grow. v1's ~1500-word system prompt
   is fine for K2.6 but punishing for a 7B.
2. **Cross-flow pivots are common.** Real users say "cancel this…
   actually just change the date" and "I want a refund and rebook on
   the same day." The agent has to preserve gathered context
   (user_id, reservation_id) across pivots without re-asking.

The shape that falls out of those two constraints is **one orchestrator
agent that owns the conversation, plus a handful of specialist
"subagent" functions that the orchestrator consults for policy-loaded
decisions**. Specialists never talk to the user; they receive typed
inputs and return structured verdicts. Each specialist declares its
required input schema; the orchestrator gathers those inputs before
invoking.

This document is the design. Implementation lands in follow-up files
(`prompt.py`, `tools.py`, `subagents/`, `graph.py`).

---

## Roles

### Orchestrator

A single LangGraph ReAct agent. Owns:
- the conversation with the user
- basic info-gathering tool calls (`get_user_details`, `get_reservation_details`, `search_direct_flight`/`search_onestop_flight`)
- routing decisions ("this is a cancellation request → invoke cancellation specialist")
- relaying specialist verdicts to the user (deny/transfer as prose;
  ready_to_act as a confirmation-card tag — see *Confirmation card protocol*)
- phrasing the natural-language follow-up after an action executes
  (using the templated user message that the UI/runner injects into
  conversation history; see *Confirmation card protocol*)

The orchestrator does **not** execute writes itself. The execute step is
structural — the UI's Accept-button handler (or the eval runner)
invokes it; the LLM is not on the tool surface for it. See
*Pending-action pattern*.

The orchestrator's prompt is short. It does **not** carry the policy
text. It carries the conversation pattern, the available specialists,
each specialist's required-input schema, and the pending-action
protocol. The goal is to keep it short — the policy lives in the
specialist functions, not the prompt — but there's no hard word cap;
length is whatever cleanly expresses the coordination logic.

The orchestrator runs on a small model (target: 7B-class fast inference;
could also be a tiny model with structured-output mode).

### Specialist subagents

One per policy-loaded flow:

- **booking_specialist**
- **modification_specialist**
- **cancellation_specialist**
- **compensation_specialist**

Each specialist is a function (initially pure code; LLM-backed later if a
flow needs fuzzy reasoning). From the orchestrator's perspective each
specialist is a typed tool with a strict input schema and a discriminated
union of response shapes.

Specialists **never talk to the user**. They never call other
specialists. They never write to the DB. They produce a pending action;
something else (the UI's Accept button, the eval runner) decides whether
to execute it. See *Pending-action pattern* below.

### Read-only info queries: handled by the orchestrator directly

"When does my flight depart?" / "How many bags can I check?" — the
orchestrator looks up the answer via `get_*` tools and replies. No
specialist needed. Reason: there's no eligibility decision to make,
and round-tripping through a specialist would waste a hop.

---

## Specialist contract

Each specialist declares two things up front:

1. A **required input schema** (Pydantic model). The orchestrator sees
   the schema as part of the tool description and is responsible for
   populating every required field before invoking. If the orchestrator
   doesn't have a field, it asks the user, then calls — no back-and-forth
   with the specialist over missing inputs.

2. A **response type**, a discriminated union of three shapes:

```python
class ReadyToAct(BaseModel):
    status: Literal["ready_to_act"]
    action_id: str                # pointer into pending_actions

class Deny(BaseModel):
    status: Literal["deny"]
    reason: str            # give reason while citing policy citations

class TransferRequired(BaseModel):
    status: Literal["transfer_required"]
    reason: str
```

Specialists return exactly one of these. The orchestrator's prompt has
three small handlers, one per shape:

- `ready_to_act` → reply with a short one-line intro and a self-closing
  confirmation-card tag carrying the `action_id` (see
  *Confirmation card protocol* below). The orchestrator does not
  execute — the UI/runner does that structurally when the user
  confirms. The orchestrator's next involvement is phrasing the
  follow-up reply once it sees the templated user message in
  conversation history.
- `deny` → relay `reason` to the user in plain language; hold the
  position; do not transfer (this is an in-scope policy denial).
- `transfer_required` → call `transfer_to_human_agents` with a summary
  built from `reason`, then send the standard transfer message.

The pattern: the specialist returns just enough for the orchestrator to
either present-for-confirmation, deny, or escalate. User-facing language
is the orchestrator's job for `deny` and `transfer_required` — it has
the conversation context to phrase things appropriately. For
`ready_to_act` the orchestrator does *not* phrase the action's details;
the full action data already lives on the pending-action row, and the
frontend renders it as a structured card by looking it up via
`action_id`. The commit step is performed by the user (Accept click)
via `execute_pending_action`, not by the orchestrator.

Compensation is an exception to this shape (see below).

---

## Pending-action pattern

The defining design decision in v2.

Each policy-loaded write operation is split into:

1. An **eligibility-check tool** the orchestrator calls
   (`check_X_eligibility`). On success it returns
   `ReadyToAct(action_id)` and stashes the full action payload in
   `pending_actions[action_id]`.
2. A **structural execute step** that runs when the user confirms.
   The LLM never invokes this. The UI's Accept-button handler (in
   production) or the eval runner (in batch eval) calls
   `execute_pending_action(action_id)` directly, then synthesizes a
   **templated user message** from the result and appends it to the
   conversation history. The orchestrator's next reply phrases the
   confirmation to the user in natural language. See *Confirmation
   card protocol* for the templates and the eval echo mechanic.

```
   check_X_eligibility(...)                       ← orchestrator tool (LLM)
        │
        ├── (eligible)   → returns ReadyToAct with action_id
        │                  pending_actions[action_id] = full args
        │
        ├── (denied)     → returns Deny
        │
        └── (transfer)   → returns TransferRequired

   execute_pending_action(action_id)              ← NOT a tool
        │                                            invoked by UI/runner
        │                                            on user confirmation
        ├── looks up pending_actions[action_id]
        ├── if expired or unknown id → Error
        ├── calls pa.execute(store)   (per-kind: cancel / book / modify_*)
        └── caller synthesizes a templated user message from the
            result and appends it as the next user turn
```

The orchestrator's flow becomes:

1. Gather the specialist's required inputs (universals from state, the rest
   from the user).
2. Call `check_X_eligibility(...)`. Get back a `ReadyToAct` with an
   `action_id`.
3. Reply with a brief one-line intro followed by a self-closing
   `<confirmation_card action_id="..." kind="..."/>` tag. The frontend
   fetches the pending action by id and renders the card with
   Accept / Cancel controls.
4. *(Outside the orchestrator's loop.)* The UI/runner invokes
   `execute_pending_action(action_id)` on Accept (or when the eval
   user-simulator echoes the card tag back). It then synthesizes a
   templated user message from the execute result and appends it as
   the next user turn (see *Confirmation card protocol* for templates).
5. On the next turn the orchestrator sees that templated user message
   and replies in natural language ("Your reservation REZ123 is
   booked. Anything else?"). No tool call from the LLM was needed for
   the write.
6. On Cancel / non-echo reply / any pivot: the pending action is left
   as-is and GC-eligible.

**Why this shape:**

- The orchestrator never has to remember the action's full arguments to
  pass them back on the next turn. The action_id is a one-token pointer.
  Small models lose data in long arg lists; they don't lose an id.
- **The confirmation gate is fully structural.** `execute_pending_action`
  is not on the LLM's tool surface at all. Writes happen only on user
  click (or sim affirmation in eval) — never by the LLM directly. The
  "agent forgot to confirm before writing" failure mode is impossible
  by construction, not by prompt rule.
- It cleanly separates three responsibilities: the specialist owns
  policy correctness, the user owns intent (via the Accept button),
  the orchestrator owns conversational phrasing.
- Eval can hook on `execute_pending_action` and verify args match the
  recorded ground truth, without having to thread the specialist's
  internal state.

### The pending-actions store

In-memory dict, scoped per Chainlit session, same lifecycle as the
existing `Store`. One typed schema per pending-action kind, sharing a
common metadata base. The shared base carries the action_id and
lifecycle bookkeeping; each subclass carries only the identifiers its
underlying write tool needs (refs only — no denormalized fares, times,
or display labels). Discriminated by `kind`.

```python
from typing import Annotated, Literal, Union
from datetime import datetime
from pydantic import BaseModel, Field

# ──────── shared typed primitives ────────
# Identifiers only. Anything derivable from the store at action time
# (fares, times, payment-method labels, baggage/insurance pricing) is
# NOT persisted here — the frontend hydrates from the DB when rendering
# the confirmation card, and execute() hydrates again when writing.

class FlightRef(BaseModel):
    flight_number: str
    date: str                  # ISO date — (flight_number, date) keys store.flights

class Passenger(BaseModel):
    first_name: str
    last_name: str
    dob: str                   # per-booking; NOT in the user profile

class PaymentRef(BaseModel):
    payment_id: str            # → store.users[user_id].payment_methods for display label
    amount: int                # cents; user-chosen split

# ──────── pending-action rows ────────

class _PendingBase(BaseModel):
    action_id: str
    created_at: datetime
    status: Literal["pending", "executed", "cancelled"] = "pending"

    def execute(self, store: Store) -> dict:
        raise NotImplementedError   # overridden per kind

class PendingCancel(_PendingBase):
    kind: Literal["cancel"]
    reservation_id: str        # frontend looks up the reservation to render the card

    def execute(self, store: Store) -> dict:
        return cancel_reservation(store, reservation_id=self.reservation_id)

class PendingBook(_PendingBase):
    kind: Literal["book"]
    user_id: str
    origin: str
    destination: str
    flight_type: Literal["one_way", "round_trip"]
    cabin: Literal["basic_economy", "economy", "business"]
    flights: list[FlightRef]
    passengers: list[Passenger]
    payment_methods: list[PaymentRef]
    total_baggages: int
    nonfree_baggages: int
    insurance: Literal["yes", "no"]

    def execute(self, store: Store) -> dict:
        return book_reservation(
            store, user_id=self.user_id, origin=self.origin,
            destination=self.destination, flight_type=self.flight_type,
            cabin=self.cabin,
            flights=[f.model_dump() for f in self.flights],
            passengers=[p.model_dump() for p in self.passengers],
            payment_methods=[pm.model_dump() for pm in self.payment_methods],
            total_baggages=self.total_baggages,
            nonfree_baggages=self.nonfree_baggages, insurance=self.insurance,
        )

class PendingModifyFlights(_PendingBase):
    kind: Literal["modify_flights"]
    reservation_id: str
    cabin: Literal["basic_economy", "economy", "business"]
    flights: list[FlightRef]
    payment_id: str            # single payment for modifications

    def execute(self, store: Store) -> dict:
        return update_reservation_flights(
            store, reservation_id=self.reservation_id, cabin=self.cabin,
            flights=[f.model_dump() for f in self.flights],
            payment_id=self.payment_id,
        )

class PendingModifyBaggage(_PendingBase):
    kind: Literal["modify_baggage"]
    reservation_id: str
    total_baggages: int
    nonfree_baggages: int
    payment_id: str

    def execute(self, store: Store) -> dict:
        return update_reservation_baggages(
            store, reservation_id=self.reservation_id,
            total_baggages=self.total_baggages,
            nonfree_baggages=self.nonfree_baggages, payment_id=self.payment_id,
        )

class PendingModifyPassengers(_PendingBase):
    kind: Literal["modify_passengers"]
    reservation_id: str
    passengers: list[Passenger]

    def execute(self, store: Store) -> dict:
        return update_reservation_passengers(
            store, reservation_id=self.reservation_id,
            passengers=[p.model_dump() for p in self.passengers],
        )

PendingAction = Annotated[
    Union[
        PendingCancel,
        PendingBook,
        PendingModifyFlights,
        PendingModifyBaggage,
        PendingModifyPassengers,
    ],
    Field(discriminator="kind"),
]
```

The pending-action row **is** the confirmation-card summary. There is no
separate `user_facing_recap` — every field needed to render the card is
either present as an identifier on the row or derivable from the store
at render time. Same applies symmetrically to `execute()`: the write
tool also re-reads what it needs.

There is no `PendingCompensation` — compensation has no DB write, so it
never enters the pending-actions store (see "Compensation is the
exception" below).

`execute_pending_action(action_id)` is a plain Python helper, not an
LLM-callable tool. It's invoked by the UI's Accept-button handler in
production and by the eval runner when the user simulator affirms a
confirmation card. It dispatches via the per-kind `execute`:

```python
def execute_pending_action(action_id: str, store: Store) -> dict:
    pa = store.pending_actions.get(action_id)
    if pa is None:
        return _err(f"no pending action with id '{action_id}'")
    if pa.status != "pending":
        return _err(f"action '{action_id}' is already {pa.status}")
    if _expired(pa):
        return _err(f"action '{action_id}' has expired; re-check eligibility")
    result = pa.execute(store)
    pa.status = "executed"
    return result
```

After it returns, the caller (UI or runner) synthesizes a templated
user message from the result and appends it to the orchestrator's
conversation history as the next user turn — see *Confirmation card
protocol* for the per-kind templates. The orchestrator's next reply
uses that message as context.

Why per-kind schemas instead of `args: dict[str, Any]`:
- Type checking catches arg-shape bugs at the specialist (where
  `PendingX(...)` is constructed) instead of at execution time.
- The pending action becomes self-describing: a reader can see exactly
  which fields a cancel needs vs a book, no cross-reference to the
  write tool's signature.
- `execute()` lives on the class, so the dispatcher doesn't need a
  registry of write functions. Adding a new pending kind = add a class
  with its own `execute`; nothing else to wire.
- Pydantic's discriminated union round-trips cleanly through JSON if
  we ever want to serialize pending actions to disk or to a trace.

TTL is a session-level concern. Default: action expires when the
orchestrator changes specialist (cross-flow pivot) or after N turns of
inactivity. The orchestrator does not need to manage this — the store
does.

### Confirmation card protocol

How the orchestrator hands a `ReadyToAct` verdict to the user.

After receiving `ReadyToAct(action_id=...)` from a specialist, the
orchestrator's reply contains two things:

1. A short one-line intro ("Here's your booking summary — please review
   and confirm.").
2. Exactly one self-closing tag:
   `<confirmation_card action_id="..." kind="..."/>`.

The orchestrator does **not** narrate any of the action's contents —
not the route, not the price, not the passengers. The frontend reads
the tag, looks up `pending_actions[action_id]`, joins against the
store for any derived fields (fares, times, payment-method labels,
reservation snapshot for modifications/cancels), and renders the card
with Accept / Cancel controls.

Why a self-closing tag rather than inlined JSON in the reply:

- **One source of truth.** The pending-action row already has every
  identifier needed. Re-emitting the summary in the reply would
  duplicate state and create a divergence surface ("the card said X,
  the prose said Y").
- **Short orchestrator outputs.** The reply is ~20 tokens regardless of
  action complexity. Small models stay reliable.
- **Greppable for eval.** Test transcripts can match on the
  `action_id` to verify the agent went through the confirmation gate
  before any write.

The `kind` attribute mirrors `pending_actions[action_id].kind`
(`book` / `cancel` / `modify_flights` / `modify_baggage` /
`modify_passengers`). It's redundant with the row's own discriminator
but lets the frontend pick a renderer before the store fetch returns.

Accept-button binding: a click invokes `execute_pending_action(action_id)`
directly — no LLM round-trip. After execute returns, the UI synthesizes
a **templated user message** describing the action and its result, and
appends it to conversation history as the next user turn. The
orchestrator's next reply phrases the confirmation in natural language.

Why a user-turn message instead of a system message: it uses an existing
channel — no new message type for the orchestrator's prompt to learn —
and it keeps the conversation transcript readable. The message is
templated per action `kind` so the orchestrator can rely on a stable
shape:

| kind | templated user message (post-execute) |
|---|---|
| `book` | `Confirmed booking. Reservation {reservation_id} created: {route} on {date(s)}, {N} passenger(s), ${total} charged to {payment_label}.` |
| `cancel` | `Confirmed cancellation. Reservation {reservation_id} cancelled; ${refund} refunded to {payment_label}.` |
| `modify_flights` | `Confirmed change. Reservation {reservation_id} updated to {new_flight_summary}; ${delta} {charged\|refunded} on {payment_label}.` |
| `modify_baggage` | `Confirmed baggage update on reservation {reservation_id}: {N} bags ({M} paid); ${cost} charged on {payment_label}.` |
| `modify_passengers` | `Confirmed passenger update on reservation {reservation_id}: {passenger_list}.` |
| any kind, error | `Action could not complete: {error_reason}.` |

Eval mechanic: the user simulator is instructed that when the agent's
reply contains a `<confirmation_card>` tag, it should respond by
**echoing the tag back verbatim** to indicate acceptance (or reply
with normal text to reject / pivot). The eval runner sees the echoed
tag in the sim's reply, calls `execute_pending_action(action_id)`,
synthesizes the same templated user message from the result, and
substitutes that message for the echo before passing it to the
orchestrator. From the orchestrator's view, production and eval are
indistinguishable.

This protocol is uniform across all four card kinds — the orchestrator
emits the same tag shape regardless of action; only the frontend
renderer (or eval template) differs.

### Compensation is the exception

Compensation has no DB write tool (the policy says the agent "offers" a
certificate verbally; no `issue_certificate` tool exists in the tau2
contract). So the compensation specialist returns a different shape:

```python
class CompensationOffer(BaseModel):
    status: Literal["offer"]
    amount: int    # dollars
    reason: str    # why the user qualifies; orchestrator phrases the offer
```

No `action_id`, no entry in `pending_actions`, no `execute_pending_action`
step, no confirmation card. The orchestrator composes the offer to the
user from `amount` and `reason` ("we can offer you a $X travel certificate
because …") and the flow ends there. The asymmetry is real and worth
documenting rather than papering over.

---

## Orchestrator tool surface

Total: 10 tools.

| Tool | Kind | Notes |
|---|---|---|
| `get_user_details(user_id)` | info | look up user profile |
| `get_reservation_details(reservation_id)` | info | look up reservation |
| `search_direct_flight(origin, destination, date)` | info | nonstop flights on a date (each carries `total_duration_min`) |
| `search_onestop_flight(origin, destination, date)` | info | one-stop connecting itineraries (with combined `total_duration_min`) |
| `get_baggage_allowance(reservation_id OR user_id, cabin, passenger_count)` | info | policy-driven free-bag allowance; the second form answers pre-booking |
| `check_booking_eligibility(...)` | specialist | invokes booking subagent |
| `check_modification_eligibility(...)` | specialist | invokes modification subagent |
| `check_cancellation_eligibility(reservation_id, reason)` | specialist | invokes cancellation subagent |
| `check_compensation_eligibility(reservation_id, complaint_kind, change_or_cancel_done)` | specialist | invokes compensation subagent |
| `transfer_to_human_agents(summary)` | escape | unchanged |

Search mirrors upstream tau2-bench's two tools (`search_direct_flight` +
`search_onestop_flight`). An earlier v2 merged them into one `search_route`
with a direct-XOR-one-stop fallback; the eval showed that hid the
direct/one-stop distinction and dropped per-leg times, so it was reverted (see
changes.md "Fix 8"). `book_reservation`, `cancel_reservation`,
`update_reservation_*` are not on the LLM's tool surface at all —
they're invoked only inside `pa.execute(store)`, which itself runs only
when the UI/runner calls `execute_pending_action(action_id)` after user
confirmation.

---

## Cross-flow pivot handling

Pivots become trivial in this design because the orchestrator owns all
state.

```
turn 1  user:  "Cancel reservation XYZ"
turn 2  agent: get_reservation_details(XYZ) → gets cabin, insurance, etc.
turn 3  agent: "What's the reason for cancellation?"
turn 4  user:  "Change of plan"
turn 5  agent: check_cancellation_eligibility(XYZ, "change_of_plan")
               → Deny(reason="booking is older than 24 hours; cabin not
                              business; no insurance covering health/weather")
turn 6  agent: "I can't cancel this — booking is past the 24-hour window
                and the standard exceptions don't apply."

(user pivots)
turn 7  user:  "OK then can I just change the date?"
turn 8  agent: (recognizes pivot, intent now = modify_flights)
               (reservation_id XYZ already gathered — no re-ask)
turn 9  agent: "What new date?"
turn 10 user:  "May 25"
turn 11 agent: check_modification_eligibility(reservation_id=XYZ,
                                              change_kind="flights",
                                              new_flights=[{...date=2024-05-25}])
               → ReadyToAct(action_id="abc")
               (pending_actions["abc"] = PendingModifyFlights(
                  reservation_id="XYZ", cabin="economy",
                  flights=[FlightRef(flight_number="HAT041", date="2024-05-25")],
                  payment_id="gift_card_4567"))
turn 12 agent: "Here's the proposed change — please confirm.
                <confirmation_card action_id=\"abc\" kind=\"modify_flights\"/>"
               (frontend fetches pending_actions["abc"], joins against
                store.reservations[XYZ] + store.flights for the new
                flight's details + payment-method label, renders card
                with Accept / Cancel.)
turn 13 user:  clicks Accept on the card
               (UI calls execute_pending_action("abc") directly;
                update_reservation_flights runs; UI synthesizes a
                templated user turn from the result and appends it:
                "Confirmed change. Reservation XYZ updated to flight
                HAT041 on 2024-05-25; $80 charged on gift card
                ending 4567.")
turn 14 agent: "Done — your flight is changed to May 25 and $80 was
                charged to your gift card ending 4567. Anything else?"
```

No handoff protocol, no state migration. The orchestrator detected the
intent shift because it's reading the conversation. The reservation_id
was in conversation state from turn 2; the new specialist call reused
it. The denied cancellation's pending state (if any) is unreferenced
and will be GC'd.

---

## Worked example: compensation subagent

Compensation is the simplest specialist (no DB write, one-tool flow)
and the one most often mis-applied in v0/v1 evals, so it's the
strongest worked example.

### Required input schema

```python
class CompensationInput(BaseModel):
    reservation_id: str
    complaint_kind: Literal["cancelled_flight", "delayed_flight", "other"]
    change_or_cancel_done: bool = False   # only meaningful if delayed_flight
```

Three fields, all mandatory except `change_or_cancel_done` which has a
sensible default. The orchestrator's responsibility is:

- Gather `reservation_id` (from conversation history or by asking).
- Identify `complaint_kind` from the user's complaint ("my flight was
  cancelled" → cancelled_flight; "delayed for 4 hours" → delayed_flight).
- Track `change_or_cancel_done` based on what's happened in the
  conversation so far (true only if a prior cancel/modify completed
  via `execute_pending_action` in this session — i.e., the
  conversation history contains a `Confirmed cancellation` /
  `Confirmed change` templated user message for that prior action).

The orchestrator does **not** check eligibility itself — it just gathers
inputs and calls.

**Pre-condition the orchestrator handles outside the specialist:** the
user must have explicitly asked for compensation. The policy says do
not proactively offer. The orchestrator's prompt encodes this — only
calls compensation_specialist when the user has asked.

### Response type

```python
class CompensationOffer(BaseModel):
    status: Literal["offer"]
    amount: int     # dollars
    reason: str     # why the user qualifies; orchestrator phrases the offer

class CompensationDeny(BaseModel):
    status: Literal["deny"]
    reason: str     # why no compensation; orchestrator phrases the denial

CompensationResponse = CompensationOffer | CompensationDeny
```

Both variants carry a single `reason` string. The orchestrator owns
phrasing for the user, the specialist owns policy correctness. This
mirrors the simplified `Deny` shape in the generic specialist contract.

### Internal logic (pure code, no LLM)

```python
def compensation_specialist(input: CompensationInput, store: Store) -> CompensationResponse:
    r = store.reservations.get(input.reservation_id)
    if r is None:
        return CompensationDeny(
            status="deny",
            reason=f"reservation '{input.reservation_id}' not found",
        )
    user = store.users.get(r.user_id)

    # Eligibility: ANY ONE qualifies. Build a short citation we can pass back.
    qualifiers: list[str] = []
    if user.membership in ("silver", "gold"):
        qualifiers.append(f"membership={user.membership}")
    if r.insurance == "yes":
        qualifiers.append("has travel insurance")
    if r.cabin == "business":
        qualifiers.append("cabin=business")

    if not qualifiers:
        return CompensationDeny(
            status="deny",
            reason=(
                f"regular member, no insurance, cabin={r.cabin}; "
                f"none of the qualifying conditions met "
                f"(silver/gold, insurance, or business cabin)"
            ),
        )

    n = len(r.passengers)
    qualifier_str = ", ".join(qualifiers)

    if input.complaint_kind == "cancelled_flight":
        return CompensationOffer(
            status="offer",
            amount=100 * n,
            reason=f"cancelled flight; ${100} × {n} passengers; qualifies via {qualifier_str}",
        )

    if input.complaint_kind == "delayed_flight":
        if not input.change_or_cancel_done:
            return CompensationDeny(
                status="deny",
                reason=(
                    "delayed-flight gesture requires the user to also "
                    "change or cancel the reservation; not yet done"
                ),
            )
        return CompensationOffer(
            status="offer",
            amount=50 * n,
            reason=f"delayed flight + change/cancel processed; ${50} × {n} passengers; qualifies via {qualifier_str}",
        )

    # complaint_kind == "other"
    return CompensationDeny(
        status="deny",
        reason="policy only covers compensation for cancelled or delayed flights",
    )
```

That's the whole specialist. No LLM call. The "agent" is a 50-line
deterministic function. It's still called a "specialist subagent" by
convention because from the orchestrator's perspective it's
indistinguishable from one (typed input, structured output, owns its
policy section).

> **Implementation note — fact confirmation.** The shipped specialist adds
> one step the sketch above omits: before *offering*, it confirms the
> complaint against the DB (policy: "Always confirms the facts before
> offering compensation"). A `cancelled_flight` offer requires a leg whose
> stored status is `cancelled`; a `delayed_flight` offer requires a flight
> that has actually departed (no tool exposes live status, so a future
> flight cannot have been delayed). This guards against a *fabricated*
> complaint from an otherwise-eligible member. Crucially the check sits only
> on the offer path — it never replaces the existing deny reasons (e.g.
> "delay gesture requires a change/cancel first"), so the orchestrator's
> phrasing for those cases is unchanged.

### Where the LLM does the work

The orchestrator's LLM does the parts that need fuzzy reasoning:

- Decide that the user is complaining (not just informing)
- Decide that the user has implicitly or explicitly asked for compensation
- Classify the complaint as `cancelled_flight` vs `delayed_flight` vs
  `other` based on what the user actually said
- Decide whether `change_or_cancel_done` is true based on what's
  happened earlier in this conversation
- Phrase the offer or denial for the user from the specialist's
  `reason` string (and `amount` for offers) — the specialist returns
  the bare facts; the orchestrator handles tone, context, and
  follow-up questions

None of those decisions need policy knowledge. They need conversation
understanding, which is what the LLM is good at.

---

## What stays from v0/v1

- LangGraph runtime; `langgraph.prebuilt.create_react_agent` for the
  orchestrator. (Specialists are not LangGraph nodes; they're functions
  invoked by tools.)
- Per-session `Store` (in-memory, mutable). v2 adds `Store.pending_actions`
  alongside `flights`/`users`/`reservations`.
- Tau2-compatible *write* tool names (`book_reservation`, `cancel_reservation`,
  `update_reservation_*`) — they're called inside `pa.execute(store)`,
  which the UI/runner triggers via `execute_pending_action`. The
  orchestrator never calls them. Ground-truth replay still works
  because the same write calls happen with the same args; only the
  surface above changes.
- Chainlit lifecycle, Langfuse observability.

## What changes from v0/v1

- Orchestrator's system prompt is substantially shorter than v1's
  (~1500 words) because the policy is no longer in the prompt; it's
  encoded in the specialist functions.
- Tool surface differs: write tools are not on the LLM's tool surface
  at all. Specialists are top-level tools; the write step happens
  outside the LLM loop via `execute_pending_action`, triggered by the
  UI's Accept button or the eval runner.
- New per-session state: `pending_actions` dict.
- New `<confirmation_card>` tag convention in orchestrator replies for
  presenting `ReadyToAct` verdicts; UI/runner injects a templated user
  message back into history after the user confirms (eval mechanic:
  user simulator echoes the tag verbatim to indicate acceptance).
- New subdirectory: `src/agents/v2/subagents/` housing one Python file
  per specialist plus a shared `schemas.py` for response types. The
  `execute_pending_action` helper lives alongside the pending-action
  schemas (not in `subagents/` — it's not a specialist).

---

## Workshop progression notes (v0 → v1 → v2)

- **v0 — baseline.** Single ReAct loop, flat-markdown policy, 10 tools.
- **v1 — better-prompted.** Same loop. XML-structured policy, operating
  principles, response style. Pure prompting changes.
- **v2 — orchestrator + specialists (this version).** Single ReAct loop
  becomes a single ReAct *orchestrator* over specialist subagents. The
  policy moves out of the prompt and into typed specialist functions.
  Each policy-loaded write becomes an eligibility-check tool plus a
  structural execute step the LLM cannot invoke; the UI's Accept
  button (or the eval runner) drives the write directly.

The workshop point lands as three claims:

1. *v1 demonstrated the ceiling of pure prompting on a strong model.*
   Tone and routing move; rule application largely doesn't.
2. *v2 demonstrates the production shape when small/fast models are a
   hard constraint.* Specialists collapse rule application into typed
   functions; the orchestrator's job becomes coordination, not policy
   recall.
3. *Taking the write off the LLM's tool surface is the load-bearing
   detail.* Confirmation is gated by a button click, not a prompt
   rule. A whole class of small-model failure ("the agent forgot to
   confirm before writing") stops mattering because the LLM can't
   write at all.
