# v1 (well-prompted single agent): Sonnet 4.6 vs Haiku 4.5

Comparison of the **v1** agent (XML-structured policy + operating principles, a
single ReAct loop) run on two Anthropic models over the full 50-task airline
eval. The only variable that changes between the two runs is the **agent
model** — same prompt, same tools, same audited assertions, same Haiku
simulator and Haiku judge.

Run artifacts:
- Sonnet: [`2026-06-15T10-22-08Z__v1__anthropic__claude-sonnet-4-6/`](2026-06-15T10-22-08Z__v1__anthropic__claude-sonnet-4-6/)
- Haiku: [`2026-06-15T10-50-39Z__v1__anthropic__claude-haiku-4-5/`](2026-06-15T10-50-39Z__v1__anthropic__claude-haiku-4-5/)

Configuration:
- Agent: `v1` (well-prompted single agent). Sonnet run used `--effort medium --thinking adaptive`; Haiku does not support effort/thinking, so it ran plain.
- Simulator + judge: `claude-haiku-4-5` for both runs (held constant).
- Assertions: the audited set (see `data/CHANGES.md` — unverifiable delay/cancellation checks, factual bugs, and over-specified assertions were fixed; 162 assertions total).
- Prompt caching on; system+tools prefix served from cache turn 2+.

## Headline

| Metric | **Sonnet 4.6** | **Haiku 4.5** |
|---|---|---|
| **Tasks** (pass = every assertion passes) | **31 / 50 — 62%** | **14 / 50 — 28%** |
| **Assertions** (partial credit) | **134 / 162 — 82.7%** | **88 / 162 — 54.3%** |

Same prompt, same eval — swapping Haiku → Sonnet roughly **doubles** the task
pass rate and lifts assertion accuracy by **+28 points**. For this task, **model
capability is the dominant lever**, well ahead of prompt sophistication.

## Why two metrics

Task scoring is all-or-nothing: a 9-assertion task that gets 8 right scores the
same FAIL as one that gets 0 right. The **assertion-level** metric restores
partial credit and exposes *how* the two models fail differently:

- **Sonnet's failures are near-misses.** Most failed tasks miss exactly one
  assertion (ratios like 1/2, 3/4, 5/6, 6/7). The agent is substantively
  correct and trips on a single check.
- **Haiku's failures compound.** On the 18 tasks where Sonnet passes but Haiku
  fails, Haiku does not miss by one — it misses *most*: T2 **1/5**, T14 **2/6**,
  T25 **0/2**, T24 **1/4**, T32 **1/3**. These are multi-error breakdowns, not
  near-misses.

This is the single clearest read in the data: a capable model is "right with a
slip," a weaker model is "wrong in several places at once" — invisible to the
task metric, obvious in the assertion metric.

## Where Sonnet wins (18 tasks: Sonnet PASS, Haiku FAIL)

`T0, T2, T9, T10, T14, T21, T24, T25, T26, T27, T31, T32, T33, T39, T41, T43,
T45, T49`

These span every flow — cancellation eligibility (0, 24, 26, 43, 45, 49),
compensation reasoning (2, 27), multi-step booking/payment (14, 21, 25),
modification (10, 31, 32, 33), and duplicate-detection (41). Haiku's low
assertion ratios on them confirm broad rule-application failure, not isolated
slips.

Only **one** task reverses (T47: Haiku passes, Sonnet fails) — an over-transfer
case where Sonnet escalated and Haiku happened not to. It is within run-to-run
variance, not a real Haiku advantage.

## Where both fail — the structural ceiling (18 tasks)

`T1, T5, T7, T11, T13, T15, T16, T18, T20, T23, T28, T35, T36, T37, T38, T44,
T46, T48`

These fail on **both** models, so they are not a capability gap a bigger model
closes — they are a *structural* ceiling. They cluster into three buckets:

1. **Over-transfer** (T1, T5, T28, T46, T48): the agent calls
   `transfer_to_human_agents` on an in-scope policy denial under user pressure.
   Prompt hardening (an explicit "frustration is not a transfer request" rule)
   did **not** fix it on either model.
2. **Payment / total arithmetic** (T7, T11, T18, T23, T35, T44): wrong totals or
   payment allocations on multi-step transactions.
3. **Search completeness** (T15, T16, T20, T35): wrong "second-cheapest" flight,
   failure to explore connecting hubs, or a degenerate "can't search" claim.

Plus scattered rule-application slips (T13 rule conflation, T37 cancelling an
ineligible reservation, T38 offering a cert the precondition forbids).

## Response latency

Per-response wall-clock, from each run's `summary.json` → `response_time_stats_ms`
(milliseconds per agent response turn). Sonnet ran with `--effort medium
--thinking adaptive`; Haiku ran plain (no effort/thinking support) — that
difference is the main driver of the gap below.

| Metric (per response) | **Sonnet 4.6** | **Haiku 4.5** |
|---|---:|---:|
| Average | **10,950 ms** (~10.9 s) | **3,011 ms** (~3.0 s) |
| Median | **5,112 ms** (~5.1 s) | **2,254 ms** (~2.3 s) |
| Min | 1,291 ms | 890 ms |
| Max | 174,761 ms (~175 s) | 15,383 ms (~15 s) |
| Responses measured | 319 | 533 |

- **Average:** Sonnet is ~3.6× slower (+7.9 s/response). **Median:** ~2.3×
  slower (+2.9 s). The median gap is far smaller than the average gap, so
  Sonnet's mean is pulled up by a few very slow turns.
- **Tail:** Sonnet's worst turn (~175 s) is an order of magnitude above Haiku's
  (~15 s) — extended thinking on hard turns.
- **Turn count:** Haiku logged 533 responses vs Sonnet's 319 for the same 50
  tasks. Haiku is faster *per turn* but chattier, taking more (often
  unsuccessful) turns per task.

Net: Haiku is meaningfully faster per response, but pays for it with roughly half
the task pass rate (28% vs 62%).

## Failure profile by theme

Failed assertions, bucketed (Sonnet had 28 failed; Haiku had 74):

| Theme | Sonnet | Haiku |
|---|---:|---:|
| Over-transfer | 9 | 23 |
| Rule application (cabin/destination/eligibility/passenger) | ~1 | 13 |
| Payment / total / arithmetic | 8 | 14 |
| Search / wrong flight | 3 | 4 |
| Compensation eligibility | 4 | 7 |
| Other | 3 | 13 |

Over-transfer is the **#1 failure on both models**. Beyond that, Haiku's
failures fan out across rule application and "other" in a way Sonnet's do not —
Sonnet's residual errors are concentrated in arithmetic and transfer, where even
a strong model needs help.

## Takeaways

1. **Model dominates prompt here.** Same v1 prompt: 28% (Haiku) → 62% (Sonnet)
   tasks; 54% → 83% assertions. If you can afford the stronger model, it buys
   more than prompt engineering does.
2. **Sonnet plateaus at 62% because of a structural ceiling, not a prompt
   ceiling.** The 18 both-fail tasks resist prompting on *either* model. The
   biggest single lever is **transfer discipline**, which is not reliably
   prompt-fixable — the agent keeps escalating in-scope denials under pressure.
3. **This is the case for v2 (architecture).** The structural failures map
   directly onto v2's design: gate `transfer_to_human_agents` so the model
   cannot escalate an in-scope denial; move eligibility/pricing into
   deterministic specialist functions; add a search-with-hub-fallback wrapper.
   Roughly 4–6 of the both-fail tasks turn on transfer alone — fixing it
   structurally would move Sonnet from 31 toward ~36/50 before any other change.

The next step is to build v2 and re-run this same eval to measure the
architecture's contribution on top of the model.
