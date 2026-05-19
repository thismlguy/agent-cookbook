
# code testing

this document covers how to test the agent code (not the AI logic). for this, we will write a few end-to-end tests which would mock the AI response and return a fixed response. 

Note: we will err on the side of NOT writing unit tests and only a few end to end test.

i'd say pick a few cases for booking, cancellation, modification and compensation from tasks.json itself and mock the conversation. the idea is to test only the code and not whether the AI works.

Each case is designed to hit a *distinct* code path — eligible /
deny / transfer_required / pivot / compensation-offer /
compensation-deny — so there's no overlap. The AI is mocked: each
case scripts the exact AIMessage sequence the orchestrator should
emit, and the test asserts on what the v3 plumbing did with it
(specialist verdicts, pending-action rows, store mutations, templated
user messages, tool calls).

## Test cases - Booking:

### case 1 - happy-path booking

Tau2 task ref: task 20 ("Book a flight with time and payment constraints").

Mocked LLM script:
1. AIMessage with a `check_booking_eligibility(...)` tool call carrying
   valid args (≤5 passengers, uniform cabin, payment methods totalling
   the computed price).
2. After the specialist returns `ReadyToAct(action_id)`, AIMessage with
   a short intro + `<confirmation_card action_id="..." kind="book"/>`.
   The runner echoes the tag back; the templated user message for
   `kind=book` is synthesized from the execute result and appended as
   the next user turn.
3. AIMessage with the natural-language confirmation.

Code paths covered: `booking_specialist` eligible branch;
`PendingBook` construction including `FlightRef` / `Passenger` /
`PaymentRef`; `execute_pending_action` happy path; `pa.execute()` →
`book_reservation`; template synthesis for `kind=book`.

Asserts:
- `pending_actions[action_id]` exists with `kind="book"` after step 1
- `<confirmation_card>` tag survives the orchestrator's reply in step 2
- after execute, `store.reservations` contains a new reservation
- templated user message in history substitutes the new
  `reservation_id` and total correctly
- pending row's `status` transitions `pending → executed`

### case 2 - eligibility deny

Scenario: 6 passengers on one reservation (over the policy max).
(Constructed scenario; tasks.json doesn't have a clean "over-cap" case,
but the rule is in the booking subtree of decision-tree.md.)

Mocked LLM script:
1. AIMessage with a `check_booking_eligibility(...)` tool call carrying
   a 6-passenger payload.
2. After the specialist returns `Deny(reason=...)`, AIMessage relaying
   the denial in prose.

Code paths covered: `booking_specialist` deny branch (passenger-count
check).

Asserts:
- no `PendingBook` row ever created
- no `<confirmation_card>` tag emitted
- `execute_pending_action` never called
- denial reason from the specialist is referenced (loosely, substring
  match) in the orchestrator's final reply

## Test cases - Cancellations:

### case 1 - happy-path cancellation

Scenario: business-cabin reservation (qualifies for free cancellation
regardless of 24h window).

Mocked LLM script:
1. AIMessage with `check_cancellation_eligibility(reservation_id, reason="change_of_plan")`.
2. After `ReadyToAct(action_id)`, AIMessage with intro +
   `<confirmation_card action_id="..." kind="cancel"/>`. Echo → execute
   → templated user message for `kind=cancel`.
3. AIMessage with the natural-language confirmation.

Code paths covered: `cancellation_specialist` eligible branch (business
cabin); `PendingCancel`; `pa.execute()` → `cancel_reservation`;
template synthesis for `kind=cancel`.

Asserts:
- `store.reservations[res_id].status == "cancelled"` after execute
- templated message includes the refund summary (amount + payment label)
- pending row status `pending → executed`

### case 2 - transfer_required path

Tau2 task ref: scenarios where a reservation has an already-flown
segment (any task whose reservation initial state has
`flights[0].status="flown"`).

Mocked LLM script:
1. AIMessage with `check_cancellation_eligibility(...)`.
2. After `TransferRequired(reason=...)`, AIMessage with a
   `transfer_to_human_agents(summary=...)` tool call.
3. AIMessage with the standard transfer message to the user.

Code paths covered: `cancellation_specialist` transfer branch;
orchestrator's `TransferRequired` handler invoking
`transfer_to_human_agents`.

Asserts:
- `transfer_to_human_agents` tool was called once
- its `summary` argument contains the specialist's `reason` substring
- no `PendingCancel` row created
- `store.reservations[res_id].status` unchanged

(This is the only case in the set that exercises `TransferRequired`;
Deny is already covered by booking case 2.)

## Test cases - Modifications:

### case 1 - happy-path modify_flights

Tau2 task ref: task 33's first leg ("User wants change flight dates"),
before the user pivots to business class.

Mocked LLM script:
1. AIMessage with `check_modification_eligibility(reservation_id, change_kind="flights", new_flights=[...])`.
2. After `ReadyToAct(action_id)`, AIMessage with intro +
   `<confirmation_card action_id="..." kind="modify_flights"/>`. Echo →
   execute → templated user message for `kind=modify_flights`.
3. AIMessage with the natural-language confirmation.

Code paths covered: `modification_specialist` eligible branch for
`change_flights`; `PendingModifyFlights` with typed `FlightRef`;
`pa.execute()` → `update_reservation_flights`; template synthesis for
`kind=modify_flights`.

Asserts:
- `store.reservations[res_id].flights` updated to the new flights
- templated message includes the new flight summary and the price delta
  + payment label
- pending row status `pending → executed`

### case 2 - cross-flow pivot (modify → cancel)

Tau2 task ref: task 7 ("introducing new user intent in the middle of
the conversation").

Mocked LLM script:
1. AIMessage with `check_modification_eligibility(...)` → `ReadyToAct(action_id="m1")`.
2. AIMessage with intro + `<confirmation_card action_id="m1" kind="modify_flights"/>`.
3. *Without* the runner echoing back, the user pivots: "actually just
   cancel it." (Test runner injects this user turn directly instead of
   echoing the tag.)
4. AIMessage with `check_cancellation_eligibility(...)` → `ReadyToAct(action_id="c1")`.
5. AIMessage with intro + `<confirmation_card action_id="c1" kind="cancel"/>`.
   Echo → execute on `c1`.
6. AIMessage with natural-language confirmation.

Code paths covered: orphaned pending action (`m1` stays unreferenced);
TTL/GC behavior on cross-specialist pivot; second pending action
executes cleanly.

Asserts:
- `pending_actions["m1"].status` is `"pending"` (or `"cancelled"` if
  TTL fires on specialist switch — assert against whichever the design
  picked)
- `pending_actions["c1"].status == "executed"`
- only one write happened: `cancel_reservation`; no
  `update_reservation_flights` ever called

## Test cases - Compensation:

### case 1 - offer (eligible)

Scenario: silver-member user complaining about a cancelled flight.
(Closest tau2 framing: task 5 if it were honest about membership;
construct a clean scenario from db.json directly.)

Mocked LLM script:
1. AIMessage with `check_compensation_eligibility(reservation_id, complaint_kind="cancelled_flight", change_or_cancel_done=False)`.
2. After `CompensationOffer(amount, reason)`, AIMessage phrasing the
   offer to the user.

Code paths covered: `compensation_specialist` offer branch;
qualifier-string assembly (membership / insurance / business cabin).

Asserts:
- returned `amount == 100 * n_passengers`
- returned `reason` cites the qualifying condition (e.g.,
  `"membership=silver"`)
- no pending action created (compensation is the asymmetric one)
- no `transfer_to_human_agents` call

### case 2 - deny (ineligible)

Tau2 task ref: task 4 ("User tries to get compensation by lying about
flight cancellation and cabin").

Mocked LLM script:
1. AIMessage with `check_compensation_eligibility(...)` against a
   regular-member / no-insurance / non-business reservation.
2. After `CompensationDeny(reason=...)`, AIMessage relaying the
   denial.

Code paths covered: `compensation_specialist` deny branch.

Asserts:
- returned `reason` mentions the three failed qualifiers
- no `transfer_to_human_agents` call (deny ≠ transfer — important
  because v1/v2 conflated the two)
- no pending action created

## Out of scope (by design)

Things deliberately not in this set:

- **TTL expiry** on a pending action (user takes too long, then clicks
  Accept). Exercises `_expired(pa)` in `execute_pending_action`. Add
  a narrow case here if TTL behavior changes.
- **Re-clicking Accept on an already-executed action**. Exercises
  `pa.status != "pending"` branch.
- **Card-echo edge cases in the eval runner** (sim partially echoes,
  echoes a different `action_id`). Not v3-code; lives in the eval
  runner.
- **`modify_baggage` and `modify_passengers` happy paths.** Structurally
  identical to modify_flights (same `PendingModify*` plumbing with a
  different write tool). Add only if a pydantic-serialization regression
  is suspected.
