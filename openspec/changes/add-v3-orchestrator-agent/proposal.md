## Why

v1 and v2 are single ReAct loops that carry the full airline policy in
the system prompt. They depend on the model to re-derive eligibility
rules every turn, which works on a strong model (K2.6) but is fragile
on small/fast models — and the prompt grows linearly with the policy.
The v3 design in `src/agents/v3/architecture.md` proposes a different
shape: one **orchestrator** that owns the conversation, plus typed
**specialist subagents** (pure code) that encode the policy as
functions, plus a **pending-action pattern** that takes write
operations off the LLM's tool surface entirely. This change
implements that design.

The structural win is that the "agent forgot to confirm before
writing" failure mode becomes impossible by construction: writes only
happen when the UI's Accept button (or the eval runner) invokes
`execute_pending_action` after the user confirms. Policy correctness
moves out of prose and into typed functions; the orchestrator's job
collapses to coordination and natural-language phrasing.

## What Changes

- Add a `v3` agent variant alongside `v1` and `v2`, registered in
  `src/agents/__init__.py` via `make_agent(store, llm)`.
- Add `src/agents/v3/subagents/` housing one Python file per
  specialist (`booking_specialist.py`, `modification_specialist.py`,
  `cancellation_specialist.py`, `compensation_specialist.py`) plus a
  shared `schemas.py` for response types
  (`ReadyToAct` / `Deny` / `TransferRequired`, plus the asymmetric
  `CompensationOffer` / `CompensationDeny`).
- Add a pending-action store as a new field on `Store`
  (`store.pending_actions: dict[str, PendingAction]`) with typed
  per-kind schemas (`PendingBook`, `PendingCancel`,
  `PendingModifyFlights`, `PendingModifyBaggage`,
  `PendingModifyPassengers`) discriminated by `kind`.
- Add `execute_pending_action(action_id, store)` as a plain Python
  helper — **not** an LLM-callable tool. It dispatches to per-kind
  `execute()` methods which call the existing write tools
  (`book_reservation`, `cancel_reservation`,
  `update_reservation_*`).
- Restrict the v3 orchestrator's tool surface to 8 tools: 3 info
  reads (`get_user_details`, `get_reservation_details`,
  `search_route`), 4 specialist-entry eligibility checks
  (`check_booking_eligibility`, `check_modification_eligibility`,
  `check_cancellation_eligibility`,
  `check_compensation_eligibility`), and `transfer_to_human_agents`.
  Write tools are **not** on the LLM's tool surface.
- Add the `<confirmation_card action_id="..." kind="..."/>` reply
  protocol. After a specialist returns `ReadyToAct`, the orchestrator
  emits a one-line intro plus the self-closing tag; user-facing card
  details are rendered by the frontend from the pending-action row.
- Add post-execute **templated user messages** (one per pending
  `kind`) that the UI/runner synthesizes from the execute result and
  appends to conversation history as the next user turn, so the
  orchestrator can phrase a natural-language confirmation.
- Wire up the eval runner's user simulator to echo
  `<confirmation_card>` tags verbatim to indicate acceptance; the
  runner intercepts the echo, calls `execute_pending_action`, and
  substitutes the templated user message before the orchestrator
  sees it.
- Add `tests/test_v3_agent.py` end-to-end tests covering the seven
  scripted cases in `src/agents/v3/testing.md` (booking happy/deny,
  cancellation happy/transfer, modify happy + cross-flow pivot,
  compensation offer/deny).

## Capabilities

### New Capabilities
- `v3-orchestrator-agent`: An orchestrator agent that owns the
  conversation and delegates policy-loaded decisions to typed
  specialist subagents via eligibility-check tools, with write
  operations gated by a structural confirmation step that runs
  outside the LLM loop.

### Modified Capabilities
<!-- None. No existing capability specs in openspec/specs/ today. -->

## Impact

- **Code (new):** `src/agents/v3/{graph.py,prompt.py,tools.py}`,
  `src/agents/v3/subagents/{booking,modification,cancellation,compensation,schemas}.py`,
  `src/agents/v3/pending_actions.py` (typed schemas +
  `execute_pending_action`), `tests/test_v3_agent.py`.
- **Code (modified):** `src/domain/store.py` (add
  `pending_actions: dict[str, PendingAction]` field);
  `src/agents/__init__.py` (register `v3`); `src/runner/runner.py`
  and the eval runner (intercept `<confirmation_card>` echoes and
  inject templated user messages); `app.py` / Chainlit UI layer to
  render the confirmation card and bind Accept → `execute_pending_action`.
- **Eval:** the existing eval suite gains a v3 row; ground-truth
  replay still works because the same underlying write tools fire
  with the same args — only the surface above them changes.
- **No breaking changes** to v1 or v2: they remain untouched and
  selectable via `--agent v1` / `--agent v2`.
- **Dependencies:** no new third-party libraries; reuses LangGraph,
  Pydantic, and the existing store layer.
