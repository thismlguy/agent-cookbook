## Context

The canonical v2 design lives in
[`src/agents/v2/architecture.md`](../../../src/agents/v2/architecture.md);
the test plan lives in
[`src/agents/v2/testing.md`](../../../src/agents/v2/testing.md). This
document is **not** a re-derivation — it captures the implementation
decisions that the canonical design assumes but doesn't always
spell out, and the integration points that touch code outside
`src/agents/v2/`.

The earlier `propose-v2-architecture` change explored three shapes
(validator tools, supervisor + specialists, hybrid subgraphs) and
recommended validators (Option A). The architecture.md in v2/
supersedes that recommendation: it adopts the supervisor +
specialists shape (Option B), but adds a load-bearing twist —
**writes are not on the LLM's tool surface**. The orchestrator only
runs an eligibility check; a structural execute step outside the LLM
loop performs the write. That twist is what makes Option B worth
preferring over Option A here: it eliminates the "agent forgot to
confirm before writing" failure class by construction, which Option
A could only enforce via prompt discipline.

Constraints:

- Must coexist with `v0` and `v1`. Both remain selectable; no shared
  prompt, no shared graph.
- Per-session `Store` is mutable and in-memory; v2 adds
  `pending_actions` alongside `flights`/`users`/`reservations`.
- Eval must continue to replay tau2 ground truth. The same write
  tools (`book_reservation`, `cancel_reservation`,
  `update_reservation_*`) fire with the same arguments — only the
  caller above them changes.
- Chainlit UI must render confirmation cards from the pending-action
  store and bind the Accept button to `execute_pending_action`.

## Goals / Non-Goals

**Goals:**

- Implement v2 exactly as described in `src/agents/v2/architecture.md`:
  one orchestrator (LangGraph `create_react_agent`) + four typed
  specialist functions + pending-action store + confirmation-card
  protocol.
- Keep the orchestrator's system prompt under ~400 words. Policy
  text does **not** live in the prompt; it lives in the specialists.
- Make `execute_pending_action` invisible to the LLM (not registered
  as a tool, not in the prompt). Writes happen only on user
  confirmation, via UI button click in production and via the eval
  runner intercepting `<confirmation_card>` echoes in batch eval.
- Cover the seven scripted end-to-end cases in `testing.md` with
  mocked-LLM tests in `tests/test_v2_agent.py`.
- Register `v2` in `src/agents/__init__.py` so it's selectable via
  `uv run python -m src.eval.run --agent v2`.

**Non-Goals:**

- Replacing v0 or v1. Both continue to ship.
- Re-running or updating any published-runs evaluation rows. v2's
  eval signal is captured in a fresh run, not by retro-judging.
- LLM-backed specialists. Specialists are pure Python in this
  change. The architecture allows them to become LLM-backed later
  if a flow needs fuzzy reasoning; that's out of scope here.
- TTL / GC of stale pending actions beyond "left on the row,
  status stays `pending`". The architecture mentions session-level
  TTL (specialist switch or N idle turns) but the test plan
  explicitly defers TTL expiry to a future change.
- A final-message critic (the v1 prompting-best-practices document
  raised this; it stays out of scope for v2).

## Decisions

### D1. Specialists are pure-code functions, not LangGraph nodes

Each specialist (`booking_specialist`, `modification_specialist`,
`cancellation_specialist`, `compensation_specialist`) is a plain
Python function taking a Pydantic input model and returning a
discriminated-union response (`ReadyToAct` / `Deny` /
`TransferRequired`, plus the compensation-specific
`CompensationOffer` / `CompensationDeny`). From the orchestrator's
perspective each is exposed as a single LangChain tool
(`check_*_eligibility`) wrapping the function.

**Why not LangGraph nodes:** specialists never talk to the user,
never call other specialists, never persist state of their own.
They're stateless eligibility checkers. Making them graph nodes
would add ceremony (state schemas, edges) without buying anything.
The "subagent" naming is intentional — they have the typed-input /
structured-output contract of a subagent, but the implementation is
a function call.

**Alternative considered:** wrap each specialist in
`create_react_agent` with its own LLM. Rejected for this change:
the policy logic is closed-form (no fuzzy reasoning needed),
adding a second LLM call per flow doubles eval cost, and the test
plan would balloon. Leave the door open by writing the orchestrator
side as if specialists were LLM-backed (typed I/O, dispatch via
`status` discriminator), so swapping a specialist for an LLM agent
later is a local change.

### D2. Pending-action rows store identifiers only, not denormalized state

`PendingBook`, `PendingCancel`, `PendingModifyFlights`,
`PendingModifyBaggage`, `PendingModifyPassengers` carry only the
identifiers the underlying write tool needs (flight numbers,
dates, payment IDs, reservation IDs). They do **not** carry
denormalized fares, formatted times, or payment-method display
labels. The frontend re-reads the store at card-render time;
`execute()` re-reads at write time.

**Why:** a single source of truth. If we cached the price on the
row and the underlying fare changed, the card would show stale
data. With identifiers only, the card and the write are
guaranteed to read the same DB state. Cost: the frontend has to
do a join. That's cheap and local to the UI layer.

### D3. `<confirmation_card>` is a self-closing tag, not inlined JSON

The orchestrator's reply on `ReadyToAct` is:

```
Here's your booking summary — please review and confirm.
<confirmation_card action_id="abc123" kind="book"/>
```

No JSON in the reply. The frontend reads the tag, looks up
`pending_actions["abc123"]`, joins the store, renders the card.

**Why:** keeps orchestrator outputs short and constant-length
regardless of action complexity. Small models stay reliable on
short outputs. Also greppable for eval: tests can match on the
`action_id` to verify the confirmation gate fired before any
write.

### D4. Eval simulator echoes the tag verbatim to indicate acceptance

In production, an Accept-button click invokes
`execute_pending_action(action_id)` directly. In batch eval, the
sim doesn't have a button. The protocol: when the agent's reply
contains a `<confirmation_card>` tag, the sim's reply echoing the
same tag verbatim **means accept**; any other reply means
reject/pivot. The eval runner intercepts the echo, calls
`execute_pending_action(action_id)`, synthesizes a templated user
message from the result, and substitutes that message for the
echo before passing it to the orchestrator. From the
orchestrator's perspective production and eval are
indistinguishable.

**Alternative considered:** a separate "accept" tool the sim
calls. Rejected: it would require a new tool surface for the sim
and a way for the runner to bridge sim-side tools to agent-side
state. Echoing a tag is simpler and uses the existing
text-message channel.

### D5. Compensation is the asymmetric specialist

Compensation has no DB write (the policy says the agent "offers"
a certificate verbally; no `issue_certificate` tool exists in
tau2). The compensation specialist returns
`CompensationOffer(amount, reason)` or
`CompensationDeny(reason)` — no `action_id`, no entry in
`pending_actions`, no `execute_pending_action` step, no
confirmation card. The orchestrator phrases the offer or denial
directly to the user from the specialist's fields.

This is asymmetric on purpose and documented in
architecture.md §"Compensation is the exception". Codifying it
here so it doesn't get "fixed" into the generic shape later.

### D6. Tests mock the LLM entirely

The seven cases in `testing.md` are end-to-end through the v2
plumbing with the LLM stubbed via a scripted `AIMessage` sequence
(LangGraph supports plugging a `FakeMessagesListChatModel` or
similar). Tests assert on plumbing behavior: specialist verdicts,
pending-action row state, store mutations, templated user
messages, tool-call sequencing. They do **not** assert on
LLM-generated prose beyond substring sanity checks
(e.g., "reply mentions refund amount").

**Why:** the "did the AI work" question lives in the eval harness
(`uv run python -m src.eval.run --agent v2`), not in pytest. The
test suite's job is to catch code-path regressions cheaply and
deterministically.

### D7. Pending-action store lifecycle == `Store` lifecycle

`pending_actions: dict[str, PendingAction]` is a field on `Store`,
which is already per-session. No new singleton, no global registry.
Sessions reset → pending actions go with them.

TTL (the "GC on specialist switch or N idle turns" notion from
architecture.md) is **not implemented in this change**. Pending
rows are left at `status="pending"` if abandoned. Tests assert
that orphaned rows from a cross-flow pivot stay `pending` (matching
the simpler implementation; if TTL ships later, the assertion
flips to `cancelled`).

## Risks / Trade-offs

- **[Risk] LLM emits malformed `<confirmation_card>` tag** (e.g.,
  missing `action_id`, extra attributes, wraps in code fence) →
  Mitigation: regex-extract on the runner side accepts any
  attribute order and tolerates whitespace; on parse failure,
  treat as "no card" and pass the reply through unchanged. The
  orchestrator's prompt includes one example.
- **[Risk] Small model invokes `check_X_eligibility` with missing
  required args** (the specialist's input schema rejects) →
  Mitigation: each specialist returns a clear
  `tool_error: missing field 'X'` when args fail Pydantic
  validation, so the next ReAct turn sees the error and the LLM
  re-asks the user. No silent failures.
- **[Risk] Cross-flow pivot leaves stale pending row that gets
  Accept-clicked later** (e.g., the user pivots from modify to
  cancel, then accidentally clicks Accept on the stale modify
  card UI from earlier in the chat) → Mitigation: the UI only
  renders the latest tag; on Accept, `execute_pending_action`
  still runs and writes the modify. **This change does not fix
  this.** Documented as a known limitation; TTL would address it
  in a follow-up.
- **[Trade-off] Doubles the work for a new flow.** Adding a
  fifth flow (e.g., "loyalty status query") requires a new
  specialist file, a new pending-action class, a new template, a
  new test case. Compared to v0/v1 where adding a flow was just
  more prompt text. This is the price of policy-as-code.
- **[Trade-off] Frontend has to join the store at card-render
  time.** Card rendering reads the store directly (or via a
  read-only API), which couples the UI to the data layer more
  tightly than v0/v1's "agent narrates everything". Acceptable
  because the existing Chainlit UI already imports from
  `src.domain` for other displays.

## Migration Plan

- v2 ships alongside v0 and v1. No code is removed.
- New `Store.pending_actions` field defaults to `{}` so existing
  v0/v1 sessions are unaffected.
- Eval CLI: `--agent v2` becomes available; the default agent
  remains `v0`.
- Chainlit UI: a feature-flag check (`agent_variant == "v2"`)
  switches the message-render path to look for
  `<confirmation_card>` tags. v0/v1 sessions go through the
  existing prose-only path.
- No data migration. `published-runs/` is unaffected.
- Rollback: revert this change. v0/v1 keep working; the
  `pending_actions` field on `Store` becomes unused (no removal
  needed for rollback).

## Open Questions

- **TTL policy.** Should pending actions expire on specialist
  switch, after N idle turns, or never? Deferred — out of scope
  for this change; current behavior is "never, until session
  ends".
- **Confirmation card on the orchestrator's tool side vs reply
  side.** Currently the orchestrator emits the tag in its reply
  text. An alternative is a `confirm` tool the orchestrator calls,
  whose return value is the templated user message. Rejected for
  now (replies stay text; the tag is greppable) but worth
  revisiting if eval shows the LLM struggling to emit the tag
  reliably.
- **Should compensation be a tool at all**, given it has no
  write? Keeping it as a tool for surface symmetry with the other
  three; the orchestrator's prompt is shorter when all four flows
  go through the same `check_*_eligibility(...)` pattern.
