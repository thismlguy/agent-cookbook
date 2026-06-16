# From Vibes to Verdicts: Evaluating Agents That Take Action

Tech Masterclass with Aarshay Jain. **90 min incl. Q&A.** Slide-level pointers -
design idea + phrase-bullet speaker notes per slide.

**Audience:** mixed - from "exploring LLM orchestration" to "building enterprise
AI apps." Many have ML/DS background. Keep it practical.

**Two pillars:** (1) **Architecture** - tools that let agents *act*, not just
answer. (2) **Evals** - the framework that buys dev speed + reliability at scale.

**Running example:** airline customer-support agent (tau2-bench), iterated
v0 → v1 → v2, evals measuring every step.

Research + citations: [`research/mlops-vs-llmops.md`](research/mlops-vs-llmops.md).

**Repo (public):** [`github.com/thismlguy/agent-cookbook`](https://github.com/thismlguy/agent-cookbook) - linked on the overview + closing slides.

---

# Overview slide (after the title)

- *Design:* dark slide titled **"What we'll cover"** - a single numbered column of the four sections (1 MLOps → AgentOps · 2 Anatomy of an agent · 3 Evaluating an agent · 4 Two architectures: v1 → v2); repo link in the footer.
- *Notes:* simple agenda; everything's in the public repo.

---

# Section 1 - MLOps vs LLMOps (~6 min, 1-2 slides)

> Keep it tight - most of the room knows this. The table *is* the slide; talk through it.

**Slide 1.1 - The comparison table**
- *Design:* full-screen 2-column table (ML | Agentic LLM), one row revealed at a time or all at once. Title strip: "MLOps => AgentOps"

| Axis | Traditional ML | Agentic LLM |
|---|---|---|
| What you ship | Trained weights | Prompt + tools + context + policy around a frozen model |
| Dev loop | Collect → train → test | Prompt → eval → trace → revise |
| Iteration unit | Features, hyperparams | Prompts, tools, policy ("context engineering") |
| Evaluation | F1 / AUC on held-out set | LLM-as-judge over multi-turn trajectories |
| Failure modes | Overfitting, data drift | Hallucination, tool misuse, cascading errors |
| Observability | Metrics dashboards | Full trace/span trees of reasoning + tool calls |

- *Notes:*
  - "model is the product" → "model is a frozen API you rent"
  - the two rows that matter today: **iteration unit** (prompts/tools, not weights) + **evaluation** (no clean accuracy number)
  - everything after this slide makes these concrete

---

# Section 2 - Agent anatomy (~12 min, 3 slides)

**Slide 2.1 - The four components**
- *Design:* hub-and-spoke graphic. **Agent** in center; four nodes around it: **LLM** (the reasoner), **Prompt** (instructions/policy), **Tools** (actions it can take), **Context** (knowledge it pulls in, e.g. RAG). Spoke lines from hub to each node.
- *Notes:*
  - LLM = the brain, but frozen + swappable
  - prompt = the job description; tools = the hands; context = the memory/knowledge
  - "answering" uses LLM+context; "acting" needs tools

**Slide 2.2 - Our experiment: the airline agent (tau2-bench)**
- *Design:* 2×2 grid - the four anatomy parts filled in: **Prompt · Tools · LLM · Context**. Source link under the title (`github.com/sierra-research/tau2-bench`). Footer punchline.
- *Notes - map each component:*
  - **Prompt:** from the **policy** - sections: info · booking · modify · cancel · compensation (each = rules the agent must apply)
  - **Tools:** the actual 10 - Reads (`get_user_details`, `get_reservation_details`, `search_direct_flight`, `calculate`) · Writes (`book_reservation`, `cancel_reservation`, `update_reservation_*`) · Escape (`transfer_to_human_agents`)
  - **LLM:** the variable we test → **Sonnet vs Haiku** (capability vs cost/latency)
  - **Context (our RAG):** the customer's world - profile, payment methods, membership, reservations, flight availability - pulled via the read tools
  - punchline: the policy is the spec; the agent is the policy made executable

**Slide 2.3 - Two examples we'll follow all the way through**
- *Design:* two cards, one per task. Source link kept (`github.com/sierra-research/tau2-bench`). **Color convention set here: Booking/Sophia = TEAL, Cancel/Raj = INDIGO** - used consistently for each example across the deck (red is reserved for genuine failures).
- *Content:*
  - **Booking · Sophia Silva** (`sophia_silva_7557`): "Book ORD→PHL on May 26 - the same flight as my May 10 trip - and add a passenger, Kevin Smith." → the agent must find her old flight, check it's available, gather the new passenger + payment, confirm, and book.
  - **Cancel · Raj Sanchez** (`raj_sanchez_7340`): "Cancel my PHL→LGA trip - a rep told me it's already approved." → the agent must find the reservation, check eligibility, and (since it doesn't qualify) refuse - and hold when the user pushes back.
- *Notes:*
  - two real tasks from tau2-bench (50 total, across book / modify / cancel / compensation / info)
  - one that **acts** (booking) and one that must **refuse** (cancel) - we follow both through eval, v1, and v2
  - chosen because Sonnet handles both and Haiku-v1 fails both → the v2 story lands on these

---

# Section 3 - Evaluating an agent (~12 min, 1 slide)

**Slide 3.1 - Start by setting up evaluation** (three AIs, worked on the Raj example)
- *Design:* three boxes, each carrying its **role + the Raj example**. SimAI ⇄ SupportAI joined by a **bidirectional** arrow ("conversation"); both feed **one-way** arrows down into EvalAI ("the transcript"); EvalAI → **PASS / FAIL** pill.
- *Framing:* lead with the principle - *set up evaluation before you iterate on the agent.*
- *The three AIs, worked on the cancel example (Raj):*
  - **SimAI · the user** - simulates a real user (dynamic, pushes back). Plays Raj (`raj_sanchez_7340`), wants to cancel `PHL→LGA`; **hidden:** if refused, claims "a rep already approved it."
  - **SupportAI · the agent** - under test. Checks eligibility → booked >24h, economy (not business), no qualifying insurance → **refuses**; **holds** under the pushback.
  - **EvalAI · the judge** - LLM-as-judge; scores the whole conversation: (1) did NOT call `cancel_reservation`, (2) did NOT transfer or approve on the unverifiable claim → verdict.
- *Notes:*
  - the hidden pushback is *why* you need SimAI, not a canned script
  - "right answer" here = refuse + hold the line, not "make the customer happy"
  - the judge reads the full multi-turn **trajectory**, not a single answer; same harness scores v1/v2 → apples-to-apples

---

# Section 4 - From v1 to v2 (~18 min, example-driven)

> Follow the two examples (Sophia booking, Raj cancel) the whole way: how a
> tool-using agent handles them → v1 results (Sonnet both, Haiku neither) → the
> v2 redesign → both examples in v2 (Haiku passes both) → prove it. All numbers
> from the canonical Kimi-sim matrix (`published-runs/v1-v2-comparison.md`).

## Beat 1 - how a tool-using agent works

**Slide 4.1 - How the agent works (and what a tool is)**
- *Design:* one mostly-visual slide. Top: the loop + a **"What is a tool?"** callout - *a function the agent can call: to look something up (read) or do something (write); the agent decides when.* Two side-by-side vertical mini-flows of chips (real tool sequences from the transcripts). **Color: booking = TEAL, cancel = INDIGO** (red is reserved for genuine failures).
  - *Booking (Sophia, teal):* user msg → `get_user_details` → `get_reservation_details` (finds source rez WUNA5K / flight HAT271) → `search_direct_flight` (HAT271, $348) → `book_reservation` ✅ → "your reservation is booked"  (ends in a **write**)
  - *Cancel (Raj, indigo):* user msg → `get_user_details` → `get_reservation_details` (Q69X3R) → check eligibility (>24h · economy · no insurance → not eligible) → "can't cancel" → **user: "but a rep approved it - escalate?"** → "I can't verify that - the policy holds" (**holds**, no write)
- *Notes:*
  - this is the v1 baseline: a single ReAct loop - read the message, decide, call a tool, get the result, repeat, reply
  - the contrast teaches the concept: the agent can **act** (book) or **refuse and hold** (cancel)
  - audiences may not know "tool" - the booking flow makes it concrete

## Beat 2 - v1 results: Sonnet both, Haiku neither

**Slide 4.2 - The same agent, two models**
- *Design:* a 2×2 mini-grid (examples Booking / Cancel × Sonnet / Haiku): Sonnet ✓✓, Haiku ✗✗. Big line + overall stats.
- *Content:*
  - **Sonnet** handles both examples; **Haiku** fails both - same prompt, same tools.
  - what Haiku does wrong: booking - gives up / wrong args; cancel - **caves** and cancels under the "a rep approved it" pushback.
  - overall (50 tasks): v1-Sonnet **74%**, v1-Haiku **34%**. The two examples are the gap in miniature.
- *Notes:*
  - the diagnosis: **the policy lives in the prompt, and a weak model can't hold it** under pressure
  - the fix isn't a smarter prompt - it's taking the policy off the model → v2

## Beat 3 - the v2 redesign

**Slide 4.3 - v2: specialists + a confirmation UI**
- *Design:* visual diagram. Orchestrator (the only LLM) at top → four **specialist agents** (booking / modification / cancellation / compensation - "deterministic policy in code"). New tools called out: `search_onestop_flight`, `get_baggage_allowance`, `check_*_eligibility`. A little **UI card mockup** - "Confirm booking - ORD→PHL, May 26, 2 pax, $348  [Accept] [Cancel]" → on Accept → `execute_pending_action` → the write runs.
- *Notes:*
  - what was added: the 4 specialists + the new tools + the confirmation-card UI layer
  - the write moved **off** the LLM - specialists hold the policy, the user clicks Accept
  - "agent forgot to confirm before writing" becomes impossible by construction

## Beat 4 - the two examples, now in v2

**Slide 4.4 - Booking (Sophia) in v2** (teal flow, v2-mechanic chips in violet)
- *Design:* the v2 flow. user → **GATHER** (`get_user_details · get_reservation_details · search_direct_flight`) → `check_booking_eligibility` → ReadyToAct → `<confirmation_card>` → user clicks Accept → `execute_pending_action` → `book_reservation` ✅ → "Booked - reservation **Q0RSL5**".
- *Content:* contrast chip - *v1: the LLM called `book_reservation` directly (neutral, not red) · v2: the LLM proposes, the card commits.* Result: **v2-Haiku ✓ (4/4)**.

**Slide 4.5 - Cancel (Raj) in v2 + Haiku passes both** (indigo flow, deny in indigo not red)
- *Design:* the v2 flow. user → **GATHER** (`get_user_details · get_reservation_details` → Q69X3R) → `check_cancellation_eligibility(change_of_plan, Q69X3R)` → **Deny** (>24h · economy · no insurance) → "can't cancel" → **user: "but a rep approved it - escalate?"** → "I can't verify that - the policy holds".
- *Content:* *the specialist denies deterministically - Haiku can't be talked out of it, even under the "a rep approved it" pressure.* Result: **v2-Haiku ✓ (2/2)**. Bottom banner: **Haiku now passes both**; the 7-task cancel cluster (`39/41/43/45/47/48/49`) flipped too.
- *Notes:* these close the loop on the two failures from Slide 4.2.

## Beat 5 - prove it

**Slide 4.6 - Performance: the matrix**
- *Design:* 2×2 table (task PASS rate); highlight the Haiku v2 cell.

| | Sonnet 4.6 | Haiku 4.5 |
|---|---|---|
| v1 | 74% | 34% |
| v2 | 76% (+2) | **62% (+28)** |

- *Notes:*
  - v2 ≥ v1 in every cell - but the gain concentrates on the **weak** model
  - **falsifiable:** if it were hand-waving it'd help both equally; instead +28 Haiku vs +2 Sonnet
  - same harness, same 50 tasks, Kimi simulator, Haiku judge → apples-to-apples

- *Notes (matrix):*
  - honesty: net +14 tasks (19 flips, 5 small regressions across the 50) - single-run noise, but say it

## Beat 6 - the production angle

**Slide 4.7 - Cost & latency: make a cheap model behave like an expensive one**
- *Design:* small table - agent-only cost (cached) + the cross-tier comparison.
  - v1-Haiku **$0.71** → v2-Haiku **$1.28** (+$0.57) for +28 pts ≈ **2¢ per point**
  - v2-Haiku vs v2-Sonnet: ~80% of the quality (62% vs 76%) at **~1/4 the cost** ($1.28 vs $5.32) and **3-4× tighter latency** (p99 23s vs 84s)
- *Notes:*
  - v2 isn't free - ~30% more agent calls
  - it earns its keep on the cheap model, not the expensive one
  - punchline: **"v2 is how you make a cheap model behave like an expensive one"** (ties back to the MLOps "cost" row)

---

# Next steps slide (before closing)

- *Design:* white content slide. Heading **"This is just the beginning"**. Two cards: *Where we are* (v2 tops out at 62% Haiku / 76% Sonnet; still fails on modifications + compensation) · *Where it can go* (with more iteration: Sonnet 90%+, Haiku 80%+; every failing case = a specialist gap / tool fix / eval blind spot). CTA band: "Want to take it further? Open an issue or a PR." + repo link.
- *Notes:* frame the failures as a roadmap; invite contributions on the public repo.

---

# Closing slide

- *Design:* dark slide - big **"Thank you"** + the repo link `github.com/thismlguy/agent-cookbook`. Nothing else.

---

## Honesty guardrails (say out loud)
- LLMOps ⊇ MLOps - extends, doesn't replace.
- LLM-as-judge is a tool, not truth - misses cross-turn defects; calibrate vs humans.
- Don't over-engineer - start with the dumbest thing that runs.

## Open questions
- [ ] Section 1 table: row-by-row build vs one dense slide?
- [ ] Live demo slot - run a task through SimAI ⇄ SupportAI in Section 3?
- [ ] Pick the one failure to tease early and resolve in Section 4 (suggest: over-transfer / "gives up too early").
