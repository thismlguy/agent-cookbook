## 1. Pending-action store + execute helper

- [x] 1.1 Add `src/agents/v3/pending_actions.py` with shared typed
      primitives (`FlightRef`, `Passenger`, `PaymentRef`), `_PendingBase`,
      and the five `Pending*` subclasses (`PendingBook`, `PendingCancel`,
      `PendingModifyFlights`, `PendingModifyBaggage`,
      `PendingModifyPassengers`), each implementing `execute(self, store)`.
- [x] 1.2 Define the `PendingAction` discriminated union via
      `Annotated[Union[...], Field(discriminator="kind")]` and export it.
- [x] 1.3 Implement `execute_pending_action(action_id, store)` in the
      same file: lookup, status guard, call `pa.execute(store)`, flip to
      `executed`. Return structured `{ok: True, ...}` / `{error: "..."}`.
- [x] 1.4 Add `pending_actions: dict[str, PendingAction] = {}` field to
      `Store` in `src/domain/store.py` (default factory `dict`).
- [x] 1.5 Add the templated-message rendering helper
      `render_post_execute_message(pa, exec_result, store) -> str` (one
      per `kind`, plus the error template) alongside the schemas.

## 2. Specialist subagents

- [x] 2.1 Add `src/agents/v3/subagents/schemas.py` with `ReadyToAct`,
      `Deny`, `TransferRequired`, `CompensationOffer`,
      `CompensationDeny`, and the per-specialist input models
      (`BookingInput`, `ModificationInput`, `CancellationInput`,
      `CompensationInput`).
- [x] 2.2 Implement `booking_specialist(input, store)` in
      `src/agents/v3/subagents/booking_specialist.py`. Encode the
      5-passenger max, uniform cabin, payment-totals rules; on success,
      construct a `PendingBook`, stash in `store.pending_actions`,
      return `ReadyToAct(action_id)`. On deny, return `Deny(reason)`.
- [x] 2.3 Implement `cancellation_specialist(input, store)` in
      `src/agents/v3/subagents/cancellation_specialist.py`. Encode the
      24-hour / business cabin / insurance / airline-cancelled
      eligibility branches; return `TransferRequired` when any segment
      has `status == "flown"`. On eligible, construct `PendingCancel`.
- [x] 2.4 Implement `modification_specialist(input, store)` in
      `src/agents/v3/subagents/modification_specialist.py` covering the
      four sub-kinds (`change_flights`, `change_cabin`, `change_baggage`,
      `change_passengers`). Construct the matching `PendingModifyX` on
      eligible.
- [x] 2.5 Implement `compensation_specialist(input, store)` in
      `src/agents/v3/subagents/compensation_specialist.py`. Return
      `CompensationOffer` / `CompensationDeny` per the canonical logic
      in `architecture.md` §"Worked example". Do **not** add a pending
      row.
- [x] 2.6 Add `__init__.py` files for the `subagents/` package.

## 3. Orchestrator tools + graph

- [x] 3.1 Add `src/agents/v3/tools.py` exposing exactly the 8 LLM-facing
      tools: `get_user_details`, `get_reservation_details`,
      `search_route`, `check_booking_eligibility`,
      `check_modification_eligibility`,
      `check_cancellation_eligibility`,
      `check_compensation_eligibility`, `transfer_to_human_agents`.
      Each `check_*` tool validates the input against the specialist's
      Pydantic input model, calls the specialist, and returns a
      JSON-serializable dict of the response.
- [x] 3.2 Implement `search_route` as `search_direct_flight` with a
      one-stop hub fallback. Keep `search_direct_flight` internal —
      not on the tool surface.
- [x] 3.3 Add `src/agents/v3/prompt.py` with the orchestrator system
      prompt (under 400 words): conversation pattern, specialist input
      schemas, three response handlers (`ready_to_act` → emit
      confirmation_card, `deny` → relay reason, `transfer_required` →
      call `transfer_to_human_agents`), pending-action protocol, and
      the list of post-execute templated messages so the orchestrator
      knows the shape of confirmation user turns.
- [x] 3.4 Add `src/agents/v3/graph.py` with `make_agent(store, llm)` that
      binds the 8 tools to `llm`, wires `create_react_agent`, and
      returns a `CompiledStateGraph`. Mirror the v2 entry-point shape
      so the eval CLI and Chainlit app pick it up identically.
- [x] 3.5 Register `"v3": _v3_make_agent` in
      `src/agents/__init__.py`'s `VARIANTS` dict; remove the placeholder
      comment.

## 4. Runner integration (eval path)

- [x] 4.1 In `src/runner/runner.py`, after each orchestrator reply,
      detect a `<confirmation_card action_id="..." kind="..."/>` tag via
      regex (attribute-order-agnostic, whitespace-tolerant).
- [x] 4.2 Pass an instruction to the user simulator (sim prompt
      addendum, scoped to v3 runs) telling it that echoing the tag
      verbatim means accept.
- [x] 4.3 In the runner, when the sim's next reply contains the
      *same* tag verbatim: call `execute_pending_action(action_id,
      store)`, synthesize the templated user message via
      `render_post_execute_message`, and substitute that message for
      the echo before passing it to the orchestrator.
- [x] 4.4 When the sim's reply does **not** echo the tag, leave the
      pending row untouched and pass the sim's reply through unchanged
      (pivot/reject path).
- [x] 4.5 Make the v3 sim-prompt addendum a no-op for v1/v2 agents so
      existing eval rows are unaffected.

## 5. Chainlit UI integration (production path)

- [x] 5.1 In the Chainlit app entrypoint (`app.py`), detect when the
      active agent is `v3` and, on each agent message, parse for the
      `<confirmation_card>` tag.
- [x] 5.2 When a tag is present, suppress raw tag rendering in the
      message and render a confirmation card UI component: read
      `store.pending_actions[action_id]`, join with `store.flights`,
      `store.users`, `store.reservations` for derived fields, and show
      Accept / Cancel buttons.
- [x] 5.3 Bind the Accept button to call
      `execute_pending_action(action_id, store)` directly, then
      synthesize the templated user message and inject it into the
      Chainlit conversation as the next user turn (so the orchestrator
      replies with a natural-language confirmation).
- [x] 5.4 Bind the Cancel button to leave the pending row untouched
      and inject a short user turn ("Never mind.") so the orchestrator
      can pivot.

## 6. End-to-end tests

- [x] 6.1 Add `tests/test_v3_agent.py` with a shared `make_v3_with_mock_llm`
      fixture that wires a scripted `AIMessage` sequence (e.g., via
      `langchain_core.language_models.FakeMessagesListChatModel`) into
      `make_agent`.
- [x] 6.2 Implement **booking case 1** (happy path) per
      `testing.md` — assert pending row created, card tag survives,
      reservation appears in store after execute, templated message
      shape, pending → executed transition.
- [x] 6.3 Implement **booking case 2** (deny: 6 passengers) — assert
      no pending row, no card tag, `execute_pending_action` never
      called, deny reason referenced in reply.
- [x] 6.4 Implement **cancellation case 1** (happy path: business
      cabin) — assert reservation cancelled, refund summary in
      templated message, pending → executed.
- [x] 6.5 Implement **cancellation case 2** (transfer_required:
      already-flown segment) — assert `transfer_to_human_agents` tool
      call, summary contains specialist's reason, no `PendingCancel`
      created.
- [x] 6.6 Implement **modification case 1** (happy path:
      `modify_flights`) — assert reservation flights updated,
      templated message includes new flight summary + delta, pending →
      executed.
- [x] 6.7 Implement **modification case 2** (cross-flow pivot:
      modify → cancel without echo) — assert orphaned modify pending
      row stays `"pending"`, cancel pending row is `"executed"`, only
      `cancel_reservation` was called.
- [x] 6.8 Implement **compensation case 1** (offer: silver member) —
      assert `amount == 100 * n_passengers`, reason cites
      `"membership=silver"`, no pending row, no transfer call.
- [x] 6.9 Implement **compensation case 2** (deny: regular/no
      insurance/non-business) — assert reason mentions failed
      qualifiers, no transfer call, no pending row.

## 7. Documentation and finalization

- [x] 7.1 Update the top-level [CLAUDE.md](../../../CLAUDE.md) "Where
      to look" table with a row for `src/agents/v3/architecture.md`
      and `src/agents/v3/testing.md` (architecture row may already
      exist — verify).
- [x] 7.2 Update [README.md](../../../README.md) "Common commands"
      section with an example invocation:
      `uv run python -m src.eval.run --agent v3 --task-id 0`.
- [x] 7.3 Run `uv run pytest tests/test_v3_agent.py -v` and confirm
      all seven cases pass.
- [x] 7.4 Run `uv run python -m src.eval.run --agent v3 --task-id 0`
      against the default model and confirm the run produces a
      `results/<id>/` directory with no plumbing errors. (Judge
      scores are out of scope here.)
