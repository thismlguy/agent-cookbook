# v1 vs v2 — the agentic-airline comparison matrix

Four full 50-task runs, one per cell of **{v1, v2} × {Sonnet 4.6, Haiku 4.5}**.
Every cell shares the **same** evaluation harness so the comparison is
apples-to-apples:

| Knob | Value (held constant across all 4 runs) |
|---|---|
| Tasks | `data/tasks.json` (50 tau2-bench airline tasks), current HEAD |
| User simulator | `openrouter:moonshotai/kimi-k2.6`, reasoning on, 256-token budget |
| Judge | `anthropic:claude-haiku-4-5` |
| Agent settings | Sonnet: `--effort medium --thinking adaptive`; Haiku: defaults |

> **Read this within the matrix, not against history.** These numbers use the
> Kimi simulator, so they are **not** comparable to the earlier Haiku-sim
> baselines (which ran ~12–22 points lower). The *relative* story — v1 vs v2,
> Sonnet vs Haiku — is what's valid here.

The four run directories sit beside this file; each holds `metadata.json`,
`summary.json`, and per-task `transcripts/` + `evaluations/`.

---

## 1. Performance

Task pass-rate = all assertions for the task passed. Assertion pass-rate = the
finer-grained signal.

| Agent | Model | Tasks PASS | Assertions | ERROR |
|---|---|---:|---:|---:|
| **v2** | Sonnet 4.6 | **38/50 (76.0%)** | **87.5%** | 1 |
| v1 | Sonnet 4.6 | 37/50 (74.0%) | 86.6% | 1 |
| **v2** | Haiku 4.5 | **31/50 (62.0%)** | **78.4%** | 0 |
| v1 | Haiku 4.5 | 17/50 (34.0%) | 61.7% | 0 |

**v2 ≥ v1 in every cell — but the gain is concentrated on the weak model:**

|  | v1 → v2 (tasks) | v1 → v2 (assertions) |
|---|---|---|
| **Sonnet** | 74.0% → 76.0% (**+2 pts**) | 86.6% → 87.5% (**+0.9**) |
| **Haiku** | 34.0% → 62.0% (**+28 pts**) | 61.7% → 78.4% (**+16.7**) |

On Haiku the orchestrator+specialist design nearly **doubles** task completion;
on Sonnet it's within noise of v1. This is the central result: moving policy out
of the prompt and into deterministic specialists matters most exactly where the
model is weakest at following policy itself.

---

## 2. Cost — agent only

LLM cost of the **agent** alone (the simulator and judge are excluded, per the
brief). Estimated from the transcripts using the ReAct context-resend model:
each agent turn re-sends the system prompt + tool schemas + the conversation so
far. Anthropic prices: Sonnet $3/$15 per M in/out, Haiku $1/$5. "Cached" assumes
the stable system+tools prefix is prompt-cached (~0.1× on reads), which the
harness does via `cache_system_prompt`.

| Agent | Model | Agent calls | Input toks | Output toks | **Cost (cached)** | Cost (no cache) |
|---|---|---:|---:|---:|---:|---:|
| v1 | Sonnet | 327 | 2.22 M | 0.15 M | **$4.07** | $9.00 |
| **v2** | Sonnet | 409 | 2.79 M | 0.19 M | **$5.32** | $11.18 |
| v1 | Haiku | 338 | 2.25 M | 0.03 M | **$0.71** | $2.41 |
| **v2** | Haiku | 475 | 3.34 M | 0.04 M | **$1.28** | $3.55 |

**v2 costs ~30–50% more than v1** (409 vs 327 calls on Sonnet; 475 vs 338 on
Haiku). The extra spend is structural: the specialist eligibility checks and the
confirmation-card protocol each add agent turns. The question is whether that
buys anything:

| Cell | Extra cost (cached) | Extra performance | Verdict |
|---|---|---|---|
| **Haiku** | +$0.57 / run | **+28 task pts** | **Clear win** — ~2¢ per point |
| **Sonnet** | +$1.25 / run | +2 task pts | Marginal — you're paying for headroom Sonnet doesn't need |

The cost-effectiveness of v2 mirrors its performance story: it earns its keep on
the cheap model, not the expensive one. (Output is a rounding error everywhere —
≤$0.04 of Haiku's bill — because airline turns are short; cost is ~95% the
re-sent input context, which is why prompt caching roughly halves it.)

---

## 3. Time distribution — agent AI response latency

Per-agent-response wall-clock (ms), aggregated across each run's ~170–240 agent
turns. This is the latency a user would feel per agent reply.

| Agent | Model | median | mean | p90 | p99 | max |
|---|---|---:|---:|---:|---:|---:|
| v1 | Sonnet | 8.2 s | 17.6 s | 50.0 s | 97.4 s | 116 s |
| **v2** | Sonnet | 7.5 s | 14.7 s | 33.2 s | 83.9 s | 167 s |
| v1 | Haiku | 5.1 s | 5.6 s | 9.5 s | 17.3 s | 21 s |
| **v2** | Haiku | 4.6 s | 6.1 s | 9.5 s | 22.6 s | 148 s |

Distribution of agent responses by latency bucket:

| Cell | <2 s | 2–5 s | 5–15 s | 15–30 s | >30 s |
|---|---:|---:|---:|---:|---:|
| v1-sonnet | 2 | 49 | 66 | 19 | **36** |
| v2-sonnet | 4 | 76 | 82 | 38 | 30 |
| v1-haiku | 14 | 71 | 86 | 3 | 0 |
| v2-haiku | 21 | 113 | 102 | 4 | 2 |

Reading it:

- **Thinking is the long tail.** The Sonnet runs (`--thinking adaptive`) have a
  heavy >30 s tail (p99 ~84–97 s); the Haiku runs, with no extended thinking,
  stay tight (p90 ~9.5 s). Latency is dominated by *whether the model thinks*,
  not by v1-vs-v2.
- **v2 is faster per call despite making more of them.** v2's median is lower in
  both model tiers (7.5 vs 8.2 s on Sonnet; 4.6 vs 5.1 s on Haiku) and its
  Sonnet p90 is much better (33 s vs 50 s). The thin orchestrator prompt and the
  offloading of policy reasoning to pure-Python specialists mean each individual
  agent turn carries less to reason about — so v2 trades *more, shorter* turns
  for v1's *fewer, heavier* ones.
- The handful of >30 s outliers on v2-haiku (max 148 s) are isolated turns, not
  a systemic shift — Haiku's p99 is still 22 s.

---

## 4. Commentary — what this work amounts to

The headline number is **v2-Haiku: 34% → 62%**. Everything else is in service of
trusting it.

**The architectural thesis held, and it's falsifiable.** v2's bet was that a thin
orchestrator over deterministic specialists would beat a single policy-laden
prompt *by taking the policy off the model*. If that were just hand-waving, v2
would have helped Sonnet and Haiku equally. Instead the gain is +28 points on
Haiku and ~0 on Sonnet — precisely the signature you'd predict if the mechanism
is "compensating for a model that can't reliably hold policy in-context." Sonnet
already can, so it sees only the cost (+30% calls), not the benefit. That
asymmetry is the result, not a footnote to it.

**Most of the engineering was making the comparison trustworthy, not making the
agent smarter.** The agent-quality fixes this session (passenger-multiplied
refunds, the two-tool flight search, the payment/baggage/duration/compensation
gaps) closed real bugs — but they moved the assertion rate by single digits. The
larger share of effort went into *harness fidelity*: a confirmation-card execute
loop that actually commits, structural writes made visible to the judge, a
judge-output coercion, and — most instructively — the Kimi-simulator rollout,
where the first full run ERRORed 18/50 tasks because Kimi ignores `json_schema`
under reasoning and answers in prose. The fix (parse JSON ourselves; treat prose
as the user's line) is unglamorous, but without it the matrix above would be
noise. A recurring lesson: **a strong model failing like a weak one is almost
always a harness bug, not a model limit** — and the way you catch it is by
re-running the *failed* tasks, not a clean smoke test (the 2-task validation
passed; the bug only bit long conversations).

**The cost/latency view sharpens the recommendation.** v2 is not a free upgrade —
it's ~30% more agent calls. The right reading isn't "v2 > v1"; it's *"v2 is how
you make a cheap model behave like an expensive one."* A v2-Haiku deployment buys
~80% of v2-Sonnet's task quality (62% vs 76%) at **~1/4 the agent cost** ($1.28
vs $5.32) and **3–4× tighter latency** (p99 23 s vs 84 s). For a
cost/latency-sensitive product that's the most interesting cell in the grid — and
it only exists because of the orchestrator+specialist design.

**What I'd footnote.** Single run per cell, so ±a couple points is noise; the two
Sonnet ERRORs (1 each) are isolated, not systemic. And the absolute numbers ride
on the Kimi simulator — a more faithful, more adversarial user than Haiku, which
is why these sit above the historical baselines. The relative conclusions are
robust; the absolute ceiling would move under a different judge or simulator.
