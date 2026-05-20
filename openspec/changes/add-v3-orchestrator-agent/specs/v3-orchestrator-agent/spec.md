## ADDED Requirements

### Requirement: Orchestrator agent owns the conversation and routes to specialists

The system SHALL provide a `v3` agent variant whose orchestrator is a
single LangGraph ReAct agent. The orchestrator SHALL own the user
conversation, perform read-only lookups directly, and delegate every
policy-loaded decision (booking, modification, cancellation,
compensation) to a corresponding specialist via a typed
`check_*_eligibility` tool. The orchestrator's system prompt MUST NOT
contain the airline policy text; it SHALL contain only the conversation
pattern, the list of specialists with their input schemas, and the
pending-action / confirmation-card protocol. The orchestrator's prompt
SHALL be under 400 words.

#### Scenario: Variant is registered

- **WHEN** the eval CLI is invoked with `--agent v3`
- **THEN** `src.agents.get_variant("v3")` returns the v3 factory and the
  CLI proceeds without an "unknown variant" error

#### Scenario: Orchestrator delegates a policy decision

- **WHEN** the user asks the v3 agent to cancel a reservation
- **THEN** the orchestrator calls `check_cancellation_eligibility(reservation_id, reason)`
  rather than reasoning about the 24-hour / insurance / business-cabin
  rules in prose

#### Scenario: Read-only info lookups bypass specialists

- **WHEN** the user asks "when does my flight depart?"
- **THEN** the orchestrator calls `get_reservation_details(...)` directly
  and replies, **without** invoking any `check_*_eligibility` tool

### Requirement: Specialist subagents return a typed discriminated-union response

The system SHALL implement four specialists (`booking_specialist`,
`modification_specialist`, `cancellation_specialist`,
`compensation_specialist`) as pure Python functions. Each specialist
SHALL declare a Pydantic input schema and SHALL return exactly one of
the typed response shapes:

- `ReadyToAct(status="ready_to_act", action_id: str)` — eligible; full
  payload stashed in `pending_actions[action_id]`.
- `Deny(status="deny", reason: str)` — in-scope policy denial.
- `TransferRequired(status="transfer_required", reason: str)` —
  out-of-scope or already-flown; orchestrator must escalate.

Compensation is the documented asymmetric exception and SHALL return
either `CompensationOffer(status="offer", amount: int, reason: str)`
or `CompensationDeny(status="deny", reason: str)` — no `action_id`, no
pending-action row.

Specialists MUST NOT call other specialists, MUST NOT write to the
store, and MUST NOT produce user-facing prose. They SHALL only compute
verdicts.

#### Scenario: Eligible booking returns ReadyToAct with a pending row

- **WHEN** `booking_specialist` receives a valid 2-passenger
  economy-cabin booking request
- **THEN** it returns `ReadyToAct(action_id=...)` and
  `store.pending_actions[action_id]` is a `PendingBook` with the
  passed-in flight refs, passengers, and payment refs

#### Scenario: Booking with too many passengers is denied

- **WHEN** `booking_specialist` receives a booking request with 6
  passengers
- **THEN** it returns `Deny(reason=...)` referencing the 5-passenger
  policy maximum, and no row is added to `store.pending_actions`

#### Scenario: Cancellation of already-flown reservation requires transfer

- **WHEN** `cancellation_specialist` receives a reservation whose
  `flights[0].status == "flown"`
- **THEN** it returns `TransferRequired(reason=...)` and no
  `PendingCancel` row is created

#### Scenario: Compensation offer for qualifying user

- **WHEN** `compensation_specialist` receives a silver-member user
  complaining about a cancelled flight
- **THEN** it returns `CompensationOffer(amount=100 * n_passengers,
  reason="...membership=silver...")`

#### Scenario: Compensation denied for ineligible user

- **WHEN** `compensation_specialist` receives a regular-member user
  with no insurance and non-business cabin
- **THEN** it returns `CompensationDeny(reason=...)` mentioning the
  failed qualifiers (membership, insurance, cabin)

### Requirement: Write operations are not on the LLM's tool surface

The orchestrator's tool surface SHALL be exactly the following 8 tools
and no others:

- 3 info reads: `get_user_details`, `get_reservation_details`,
  `search_route`
- 4 specialist entries: `check_booking_eligibility`,
  `check_modification_eligibility`, `check_cancellation_eligibility`,
  `check_compensation_eligibility`
- 1 escape: `transfer_to_human_agents`

`book_reservation`, `cancel_reservation`,
`update_reservation_flights`, `update_reservation_baggages`,
`update_reservation_passengers`, and `execute_pending_action` MUST NOT
be registered as LLM-callable tools for the v3 agent.

#### Scenario: LLM cannot directly invoke a write tool

- **WHEN** the v3 graph is compiled and its bound tool list is inspected
- **THEN** none of the tool names include `book_reservation`,
  `cancel_reservation`, `update_reservation_*`, or
  `execute_pending_action`

### Requirement: Pending-action store with typed per-kind schemas

The system SHALL extend `Store` with a `pending_actions: dict[str, PendingAction]`
field, where `PendingAction` is a Pydantic discriminated union over
`kind`:

- `PendingBook` (kind="book")
- `PendingCancel` (kind="cancel")
- `PendingModifyFlights` (kind="modify_flights")
- `PendingModifyBaggage` (kind="modify_baggage")
- `PendingModifyPassengers` (kind="modify_passengers")

Each row SHALL carry `action_id: str`, `created_at: datetime`,
`status: Literal["pending", "executed", "cancelled"]` (default
`"pending"`), and the **identifiers only** required by its underlying
write tool. Rows MUST NOT carry denormalized fares, formatted times,
or display labels — those are derived at render-time and write-time
by re-reading the store.

Each subclass SHALL implement `execute(self, store) -> dict` which
calls the corresponding write tool with the row's fields.

#### Scenario: PendingBook is constructed with identifiers only

- **WHEN** an eligible booking produces `PendingBook`
- **THEN** the row contains `user_id`, `origin`, `destination`,
  `flight_type`, `cabin`, `flights: list[FlightRef]`,
  `passengers: list[Passenger]`, `payment_methods: list[PaymentRef]`,
  `total_baggages`, `nonfree_baggages`, `insurance`, **and nothing else**
  — no fares, no airport-name strings, no payment-method labels

#### Scenario: Discriminated union round-trips through JSON

- **WHEN** a `PendingModifyFlights` row is serialized via
  `model_dump_json()` and parsed back via
  `PendingAction(...).model_validate_json(...)`
- **THEN** the resulting object is a `PendingModifyFlights` (kind
  discriminator preserved), not the abstract `PendingAction`

### Requirement: `execute_pending_action` is a structural step outside the LLM loop

The system SHALL provide `execute_pending_action(action_id: str, store: Store) -> dict`
as a plain Python helper invoked by the Chainlit UI's Accept-button
handler in production and by the eval runner when the sim echoes a
confirmation card. It MUST NOT be registered as a LangChain tool and
MUST NOT appear in the orchestrator's prompt as a callable.

It SHALL:
1. Look up `store.pending_actions[action_id]`; return an error if
   missing.
2. Reject if `pa.status != "pending"`.
3. Call `pa.execute(store)`; on success, mark `pa.status = "executed"`
   and return the underlying write tool's result.

#### Scenario: Successful execution flips status

- **WHEN** `execute_pending_action(action_id, store)` is called for a
  pending `PendingCancel` row
- **THEN** the corresponding reservation is cancelled in the store and
  the row's `status` becomes `"executed"`

#### Scenario: Re-executing an already-executed action errors

- **WHEN** `execute_pending_action(action_id, store)` is called twice
  for the same action_id
- **THEN** the second call returns an error referencing the row's
  current status; no second write occurs

#### Scenario: Unknown action_id errors out

- **WHEN** `execute_pending_action("nonexistent", store)` is called
- **THEN** the call returns an error referencing the missing id;
  no store mutation occurs

### Requirement: Confirmation-card protocol on `ReadyToAct`

The orchestrator SHALL use a self-closing `<confirmation_card>` tag
to present a `ReadyToAct` verdict to the user. When a specialist
returns `ReadyToAct(action_id=...)`, the orchestrator's reply MUST
contain:

1. A short one-line natural-language intro (e.g., "Here's your booking
   summary — please review and confirm.").
2. Exactly one self-closing tag of the form
   `<confirmation_card action_id="..." kind="..."/>`, where
   `kind` matches the pending-action row's `kind` field.

The orchestrator MUST NOT narrate the action's contents (route,
price, passengers, etc.) in the reply prose — the frontend renders
those by joining the store against the pending-action row.

#### Scenario: Reply contains exactly one confirmation_card tag

- **WHEN** the orchestrator receives `ReadyToAct(action_id="abc")` from
  `booking_specialist`
- **THEN** its next reply contains exactly one
  `<confirmation_card action_id="abc" kind="book"/>` tag

### Requirement: Post-execute templated user message rejoins conversation

The system SHALL inject a templated user message into the
orchestrator's conversation history after every write executes. After
`execute_pending_action` returns successfully, the caller (UI or eval
runner) MUST synthesize a templated user message from the execute
result and append it to the orchestrator's conversation history as the
next user turn. There SHALL be exactly one template
per pending `kind`, plus an error template. The orchestrator's prompt
SHALL document these template shapes so it knows what shape of user
message to expect after a confirmation.

#### Scenario: Successful booking yields the book template

- **WHEN** `execute_pending_action` succeeds on a `PendingBook` row
- **THEN** the appended user message matches the shape
  `Confirmed booking. Reservation {reservation_id} created: ...`

#### Scenario: Failed execute yields the error template

- **WHEN** `execute_pending_action` returns an error (e.g., expired
  fare, missing reservation)
- **THEN** the appended user message matches the shape
  `Action could not complete: {error_reason}.`

### Requirement: Eval runner intercepts confirmation_card echoes

The eval runner SHALL detect when the agent's reply contains a
`<confirmation_card>` tag and instruct the user simulator that echoing
the same tag verbatim means **accept**. When the simulator's reply
echoes the tag, the runner SHALL:

1. Extract the `action_id` from the echoed tag.
2. Call `execute_pending_action(action_id, store)`.
3. Synthesize the templated user message from the execute result
   (using the same template the production UI would use).
4. Substitute that synthesized message for the echoed tag before
   appending it to the orchestrator's conversation history.

If the simulator's reply does not echo the tag, the pending action
is left untouched and the conversation continues normally (allowing
pivots and rejections).

#### Scenario: Echo triggers execute and templated message substitution

- **WHEN** the agent's reply contains
  `<confirmation_card action_id="abc" kind="book"/>` and the sim's
  reply is the same tag verbatim
- **THEN** `execute_pending_action("abc", store)` is called once and
  the templated `book` message replaces the echo in the next user
  turn that the orchestrator sees

#### Scenario: Non-echo reply leaves pending row untouched

- **WHEN** the agent emits a `confirmation_card` tag and the sim
  replies with a pivot like "actually just cancel it"
- **THEN** `execute_pending_action` is not called, the pending row's
  status remains `"pending"`, and the pivot text passes through to the
  orchestrator unchanged

### Requirement: Cross-flow pivots preserve gathered context

The orchestrator SHALL preserve user/reservation identifiers across
specialist switches. When the user pivots mid-flow (e.g., from
modification to cancellation), the orchestrator SHALL NOT re-ask for
identifiers already present in conversation history. Any pending
action from the prior flow that the user did not confirm SHALL be
left in `status="pending"` (no automatic cancellation in this change).

#### Scenario: Pivot from modify to cancel re-uses reservation_id

- **WHEN** the user says "actually just cancel it" after a pending
  `PendingModifyFlights` row has been created for reservation `XYZ`
- **THEN** the orchestrator calls `check_cancellation_eligibility(reservation_id="XYZ", ...)`
  without re-asking for the reservation id, and the prior pending
  modify row remains at `status="pending"`

### Requirement: End-to-end tests cover the seven canonical cases

The system SHALL include `tests/test_v3_agent.py` with tests
exercising the seven scripted cases from
`src/agents/v3/testing.md`:

1. Booking — happy path (eligible → confirm → execute → reply).
2. Booking — eligibility deny (6 passengers).
3. Cancellation — happy path (business cabin → confirm → execute).
4. Cancellation — transfer required (already-flown segment).
5. Modification — happy path (`modify_flights` → confirm → execute).
6. Modification — cross-flow pivot (modify → cancel without echoing
   the modify card).
7. Compensation — offer (eligible) and deny (ineligible).

Tests SHALL mock the LLM with a scripted `AIMessage` sequence and
assert on plumbing behavior (specialist verdicts, pending-action row
state, store mutations, templated messages, tool-call sequencing).
They SHALL NOT call any real LLM provider.

#### Scenario: Happy-path booking test asserts the full chain

- **WHEN** the booking happy-path test runs
- **THEN** it asserts that (a) `pending_actions[action_id].kind == "book"`
  exists after the first AI tool-call turn, (b) the reply with the
  `<confirmation_card>` tag survives, (c) the booked reservation
  appears in `store.reservations` after execute, (d) the templated
  user message substitutes the new `reservation_id`, and (e) the
  pending row transitions `pending → executed`

#### Scenario: Cross-flow pivot test verifies orphaned row

- **WHEN** the cross-flow pivot test runs
- **THEN** it asserts that (a) only `cancel_reservation` was called
  (no `update_reservation_flights`), (b) the modify pending row's
  status remained `"pending"`, and (c) the cancel pending row's
  status is `"executed"`
