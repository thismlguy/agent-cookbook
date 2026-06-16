# v2 changes — chain of thought (presentation notes)

A running, narrative log of the fixes made to v2 *after* the first end-to-end
eval. Written for the talk: each entry is **symptom → root cause → fix →
evidence**, so the reasoning (not just the diff) is reusable on a slide.

For the design itself see [architecture.md](architecture.md). For dataset/tool
assertion history see [../../../data/CHANGES.md](../../../data/CHANGES.md).

---

## The arc (the slide-level story)

1. **We built v2** — one orchestrator LLM over typed, pure-Python specialist
   subagents; policy moved out of the prompt and into the specialists; every
   write split into an eligibility check + a structural `execute_pending_action`
   the LLM cannot call. Thesis: *this is the production shape when small/fast
   models are a hard constraint.*

2. **We eval'd it on both models** (50 tasks, audited 162-assertion set, Haiku
   sim+judge held constant):

   | | v1 (single agent) | v2 (orchestrator + specialists) |
   |---|---|---|
   | **Haiku** | 28% / 54.3% | **40% / 66.7%** ⬆ |
   | **Sonnet** | 62% / 82.7% | **52% / 75.0%** ⬇ |

   v2 *helped the small model and hurt the strong one.*

3. **The key realization:** the Sonnet regressions reproduced **on Sonnet**.
   A strong model failing the same way a weak one does is not a capability gap —
   it's a **plumbing bug in our harness/agent**. So they're fixable in code, and
   fixing them should lift *both* models. This reframed "v2 is worse" into "v2
   has a fixable bug list."

4. **We root-caused from the real transcripts, not the code alone.** Reading the
   code suggested one mechanism; reading the failing transcripts revealed a
   different, sharper one (see Fix 1). The transcript is the ground truth for
   *why* an agent failed.

Everything below is that bug list.

---

## Fix 1 — The confirmation-card execute loop (headline)

**Symptom.** Multi-write tasks (cancel A *and* B; downgrade then refund) completed
the **first** write and then stalled — the agent looped "please click Accept
above" for a dozen turns and finally transferred to a human. Single-write tasks
were fine.

**Root cause (from transcripts 42 & 11, not inferred from code).** The eval
runner only treated a confirmation card as acceptable while it sat in the
*immediately-preceding* agent message. Two ways that breaks:
- the agent **bundled two cards in one message** → only the first was ever
  consumable; the second was orphaned (task 42);
- the user **didn't accept on the very next turn** (asked a question / pushed back
  first) → the card went stale and could never be accepted (task 11).
Once the agent's latest reply was tag-free, the simulator (told to act on the
*latest* reply) stopped offering to accept, and the write could never commit.

**Why it mattered for the thesis.** This is the load-bearing mechanism of v2 — the
structural confirmation gate. A bug here undercuts the whole "take the write off
the LLM's tool surface" claim. And it was invisible at the design level; only the
transcript showed the 13-turn death-loop.

**Fix.**
- Runner: replace last-message scanning with `_open_card()` — the most-recent
  *still-pending* presented card (scans all history, skips already-executed
  siblings). Re-surface it to the sim each turn so it stays acceptable after a
  pause/pushback. (`src/runner/runner.py`)
- Prompt: present exactly **one** card per message; **re-emit the tag** whenever
  re-asking — never "click Accept above" without the tag.
  (`src/agents/v2/prompt.py`)

**Evidence.** Mocked tests for both failure shapes
(`tests/test_runner_cards.py::test_runner_executes_two_bundled_cards`,
`::test_runner_executes_card_after_pushback`). Sonnet spot-check: **task 42 flips
FAIL→PASS**; the agent now says *"I'll present them one at a time"* and the loop
is gone.

---

## Fix 2 — Structural writes were invisible to the judge

**Symptom.** Assertions like "agent should call `update_reservation_flights` with
the original `payment_id`" failed even when v2 did exactly that.

**Root cause.** v2's whole point is that writes run via `execute_pending_action`
(off the LLM tool surface). But that means the write never appears in the judged
transcript — the judge sees only a "Confirmed change" message. It can't credit a
tool call it can't see. (A measurement mismatch, ~5/162 assertions.)

**Fix.** Add `Pending.write_call()` (also DRYs `execute()`); the runner logs each
executed write — tool name + args — into the transcript, and the judge renders
tool args. The write hits the LLM surface nowhere; it's visible to the judge
everywhere. (`src/agents/v2/pending_actions.py`, `src/runner/runner.py`,
`src/eval/judge.py`)

**Evidence.** Saved spot-check transcripts show
`update_reservation_flights({…payment_id…})`; the judge marked task 11's
API-syntax assertion satisfied.

---

## Fix 3 — Bookings stalled on missing passenger DOB

**Symptom.** Booking tasks never completed; the agent got blocked needing a
passenger date of birth (tasks 8, 17, 24, 29).

**Root cause.** `PendingPassenger.dob` / `BookingInput` require `dob`, but the v2
orchestrator prompt said "gather: … passengers" without naming it. v1's prompt
explicitly listed "first_name, last_name, dob." When policy moved out of the
prompt into the schemas, the *instruction to collect* a required field got
dropped — the schema enforced it, but nothing told the agent to ask.

**Lesson for the talk.** Moving policy into typed specialists is right, but the
orchestrator still needs to know *what to gather*. Schema-required ≠ agent knows
to ask.

**Fix.** Name `dob` explicitly in the booking-gather step.
(`src/agents/v2/prompt.py`) — verified on next eval.

---

## Fix 4 — Over-escalation: the transfer rule was policy-misaligned

**Symptom.** The agent transferred on in-scope denials under user pressure — the
biggest cross-cutting failure cluster on *both* v1 and v2 (tasks 5, 6, 26, 27,
46, 47).

**Root cause (confirmed against `policy.md` + the assertion set).** Two layers:
1. A first pass added *"NEVER transfer on a deny verdict"* to the deny case —
   necessary but not sufficient.
2. The real driver was the orchestrator's **step-0 short-circuits**, which fired
   *before* the specialist ran and transferred on (a) any explicit
   supervisor/human request and (b) any unverifiable prior-interaction claim.
   `policy.md` line 15 is strict: *transfer if and only if the request cannot be
   handled within scope.* A bare supervisor demand on an in-scope matter does
   **not** change scope → that trigger was policy-ungrounded and wrong.

**The detour that mattered (keep this on the slide — it's the honest part).**
A middle draft tried to preserve a third trigger: an **unverifiable
prior-interaction claim** ("a previous agent approved this") → transfer, because
"only a human has call-history access." Our own tasks 0/1 encoded exactly that
and called it *"Option B."* Then we **diffed our `policy.md` against the upstream
tau2-bench source** — and Option B is **nowhere in the real policy**. The
upstream transfer rule is a verbatim match to ours ("if and only if the request
cannot be handled within scope") with **no** supervisor clause and **no**
prior-interaction clause. "Option B" was a local invention in our task data, and
it even contradicted our own `CHANGES.md`, which already said tasks 0/1 must
*not* transfer.

**Decision: align to canonical.** An unverifiable prior-approval claim about an
in-scope cancellation is still in scope — the agent *can* handle it by denying it
(policy eligibility doesn't bend to an unverifiable prior approval). So: **hold,
don't transfer.** There are exactly **two** triggers — out-of-scope request, and
already-flown leg. A misremembered fact you *can* check against tool data
(`created_at`, `payment_history`, flight date) is verified and *corrected*, not
transferred (tasks 48, 49, 16, 2).

**Fix.** Rewrote step 0, the deny case, and the invariants to encode the
two-trigger rule; removed both the bare supervisor-request trigger and the
Option-B prior-interaction trigger. Corrected **tasks 0/1** (purpose + assertions)
from "should transfer" → "deny, do not transfer." Reconciled `data/CHANGES.md`
G1. Applied the **same fix to v1** (`operating_principles` #4 had the identical
"user demands a supervisor → transfer" case a); **v0 needs nothing** — it serves
`policy.md` verbatim, which is already canonical. (`src/agents/v2/prompt.py`,
`src/agents/v1/prompt.py`, `data/tasks.json`, `data/CHANGES.md`)

**Lessons for the talk.**
- "Don't over-escalate" is too blunt; the policy is a precise *scope* test, and a
  bare supervisor demand doesn't change scope.
- **Diff your translated artifacts against the source.** A plausible-sounding
  rule ("a human can check call history") had been baked into our task data and
  even our prompt — and it simply wasn't in the upstream policy. The same diff
  also caught the per-passenger refund bug (Fix 6). Translation drift cuts both
  ways: a missing `* passengers`, and an *added* transfer rule.

---

## Fix 5 — Judge crashed on stringified-list output

**Symptom.** 2 tasks scored ERROR (unjudged) instead of pass/fail.

**Root cause.** The Haiku judge occasionally returns `assertions` as a JSON
**string** instead of a list; pydantic rejected it and the whole task errored.

**Fix.** `field_validator(mode="before")` on `JudgeResult.assertions` json-parses a
string, else falls through. (`src/eval/schemas.py`) Unit-tested. Harness
robustness, not a v2-agent issue.

---

## Fix 6 — Cabin/flight-change refund not passenger-multiplied

**Symptom.** Task 11's spot-check still failed after Fix 1: the cabin downgrade
*executed*, but refunded **$1,748** where the assertion wanted **$5,244**.
$5,244 ÷ 3 passengers = $1,748 — an exact per-passenger vs. total mismatch.

**Root cause.** Fares are stored **per passenger** on the reservation. Both the v0
write tool (`update_reservation_flights`) and the v2 card-delta
(`_flights_delta`) computed `new_total − old_total` over the legs and **never
multiplied by the passenger count**. Policy: all passengers share the same
flights/cabin, so "pay/refund the difference" is the difference for *every*
passenger. `data/CHANGES.md` had already *flagged* this (tasks 11/18) but left the
tool unchanged — the assertions were known-correct, the tool known-wrong.

**Lesson for the talk.** Not every v2 "failure" is a v2 bug — this one was a
pre-existing bug in the shared write tool, surfaced only because we chased a real
dollar figure to ground. Fixing it helps **v0/v1/v2** alike.

**Fix.** Multiply the fare difference by `len(reservation.passengers)` in both the
authoritative write (`src/agents/v0/tools.py`) and the confirmation-card delta
(`src/agents/v2/.../modification_specialist.py`) so the card shows exactly what
gets charged. (`data/CHANGES.md` updated: flagged → fixed.)

**Evidence.** `tests/test_runner_cards.py::test_cabin_change_refund_is_passenger_multiplied`
— GV1N64 (business→basic_economy, 3 pax) now yields **−$5,244** on both the card
delta and the written `payment_history`.

---

## Where we are

- **Full mocked suite: green** (regression tests for every fix above).
- **Sonnet spot-check (tasks 42, 11):** 42 PASS; 11's card executes and now
  refunds the correct $5,244 (its earlier miss was Fix 6, not the card loop).
- **Pending:** full 50-task re-runs on both models (deferred for token cost). The
  Sonnet number is the one to watch — these were plumbing bugs, so it should now
  clear the v1 baseline it previously trailed.

## Talk takeaways

1. *A strong model failing like a weak one = a harness bug, not a model limit.*
   That single observation turned "v2 regressed" into a fixable list.
2. *Root-cause from transcripts, not code.* The code suggested "multiple cards in
   one message"; the transcript revealed the sharper "stale card after pushback."
3. *Moving policy into specialists still leaves the orchestrator owning
   "what to gather."* (Fix 3.)
4. *Taking writes off the LLM surface needs a parallel path to keep them
   observable* — to the judge (Fix 2) and to the user via the card, which must
   match the write (Fix 6).
