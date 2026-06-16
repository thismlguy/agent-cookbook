# Airline agent v1 — XML-structured prompt with operating principles

**v1 is structurally identical to v0.** Same LangGraph ReAct loop, same 10 tools bound to the same `Store`, same model (Kimi K2.6 via OpenRouter). The only thing that changes is the system prompt.

This file is also the v0→v1 narrative for the workshop. v2 will live in a sibling directory once we build it.

---

## What changed from v0, layer by layer

### Layer A — Policy is now XML-structured (`data/policy.md`)

**Before (v0):** `policy.md` was flat markdown with `##` and `###` headers for sections (Domain Basic, Book flight, Modify flight, etc.). The system prompt was the file's contents verbatim.

**After (v1):** Same policy text wrapped in semantic XML tags around each section:

```xml
<role>...</role>
<general_rules>...</general_rules>
<domain>
  <users>...</users>
  <flights>...</flights>
  <reservations>...</reservations>
</domain>
<booking>...</booking>
<modification>
  <change_flights>...</change_flights>
  <change_cabin>...</change_cabin>
  <change_baggage_and_insurance>...</change_baggage_and_insurance>
  <change_passengers>...</change_passengers>
  <payment_for_modifications>...</payment_for_modifications>
</modification>
<cancellation>...</cancellation>
<refunds_and_compensation>...</refunds_and_compensation>
```

**Why:** Models attend more reliably to clearly delimited sections than to markdown headers. XML tags are a widely-tested structural convention across model families (Anthropic Claude, OpenAI GPT, Moonshot Kimi, Google Gemini). The nested structure inside `<modification>` matters: previously the agent conflated "basic economy can't modify flights" with "all reservations can change cabin" (policy lines 110 and 117). Putting each rule in its own tag makes the distinction structurally explicit.

No new policy text was added. Same content, different markup.

### Layer B — `<operating_principles>` injected (`src/agents/v1/prompt.py`)

Four broad principles inserted between `</general_rules>` and `<domain>`. They are *not* in `policy.md` because they aren't airline policy — they're agent-engineering meta-skills that apply to any tool-using support agent:

1. **Verify with tools, not user assertions.** Treat tool output as the source of truth.
2. **Reason from the data you already have.** Use the current time against flight dates; don't claim limitations without checking.
3. **Try alternatives before transferring or denying.** Empty search → try other hubs. Last-resort transfer only.
4. **Use what the user has already told you.** Extract identifiers from prior turns. Execute on confirmation.

**Why:** v0's eval and v1's first eval pass surfaced five recurring failure trends (see `prompting-best-practices.md` for the analysis). Four of them are addressable at the prompt level by these principles. The fifth — fabrication of rules/coverage — is a tools/process problem, not a prompt one; it's deferred to v2.

### Layer C — `<response_style>` appended (`src/agents/v1/prompt.py`)

Three-line tone block at the end of the prompt:

- State outcomes plainly; do not quote eligibility rules as bulleted lists
- Be concise; don't restate the user's words
- Acknowledge briefly when appropriate; don't over-apologize or over-promise

**Why:** The policy is silent on tone. v0's tone failure rate was 44/50 — mostly the agent quoting eligibility criteria back to users as numbered lists. Adding this tag moved tone passing from 6 to 25.

---

## What did NOT change from v0

- Tools: same 10 (`get_user_details`, `get_reservation_details`, `search_direct_flight`, `calculate`, `book_reservation`, four `update_reservation_*`, `cancel_reservation`, `transfer_to_human_agents`). `v1/tools.py` re-exports v0's factory.
- Tool schemas: same. `cabin` is still a string, not a `Literal[...]`. Airport codes are not validated. (These are v2's territory.)
- Graph: same `create_react_agent(...)` call.
- Model and provider: Kimi K2.6 via OpenRouter, temperature 0.
- Store and DB: same.

---

## Eval signal across iterations (running tally)

| | Main eval (assertions) | Tone eval |
|---|---|---|
| v0 (rejudge with augmented assertions) | 16 PASS / 34 FAIL | 6 PASS / 44 FAIL |
| v1 — first pass (structured policy + response_style) | 20 PASS / 30 FAIL | 25 PASS / 25 FAIL |
| v1 — second pass (above + operating_principles) | **TBD — pending re-run** | TBD |

What v1's first pass demonstrated: structure and tone guidance alone fix ~9 failures (mostly over-transfer cases) and 19 tone fails. They don't fix reasoning errors (G3 incomplete policy reasoning, G4 rule disambiguation), tool-arg bugs (G8), or search-strategy gaps (G9).

What the operating principles are predicted to fix: P1 (verify user claims), P2 (reason over current-time vs flight dates), P3 (try alternatives), P4 (use info from prior turns). What they won't fix: P5 (fabrication) — that's v2.

---

## File map

```
src/agents/v1/
├── prompt.py                       # load policy.md, inject operating_principles,
│                                   #   append response_style
├── tools.py                        # re-exports v0's make_tools
├── graph.py                        # make_agent(store, llm) — create_react_agent
├── __init__.py                     # exports make_agent
├── architecture.md                 # this file — v0→v1 narrative
└── prompting-best-practices.md     # references + practices + failure-trend analysis
```

---

## Workshop progression notes (v0 → v1 → v2 → ...)

The cookbook walks the audience through progressively-more-capable agents on the same eval set. Each step changes one axis at a time so the audience can attribute the lift.

**v0 — baseline.** Single ReAct loop, flat-markdown policy as system prompt, default tool schemas. The cleanest possible thing. Used to establish the eval signal and the failure taxonomy.

**v1 — better-prompted (this version).** Three pure prompting changes: structured policy, operating principles, response style. Nothing else moves. Lift measured against v0.

**v2 — orchestrator + specialists (what shipped).** v2 took a different shape
than the tool-tweaks anticipated during v1: instead of bolting validation tools
onto the v1 prompt, it moves policy *out* of the prompt entirely. A thin,
rule-free orchestrator drives four pure-Python **specialist** functions (booking,
modification, cancellation, compensation) that own the policy; writes never
happen on the LLM tool surface but through a **pending-action store** gated by a
confirmation card. Search is the upstream two-tool surface
(`search_direct_flight` + `search_onestop_flight`), and the eligibility/arithmetic
that `validate_action`/`compute_compensation` would have done lives inside the
specialists. See [src/agents/v2/architecture.md](../v2/architecture.md) for the
design and [src/agents/v2/changes.md](../v2/changes.md) for the build narrative.

The workshop point: each layer is independently measurable, and the audience can see which class of failure each layer addresses.
