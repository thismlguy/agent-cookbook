## Context

The foundational change `add-airline-domain-and-agent` shipped: in-memory mutable `Store`, LangGraph ReAct agent with `policy.md` as system prompt, 10 tau2-aligned tools, Chainlit chat app, and Langfuse tracing. This change is the eval pillar from `SOUL.md`, plus the comparison surface the cookbook actually leans on: same evaluator, swap agent variants and LLM providers to see what moves.

`data/tasks.json` has 50 tau2-bench airline tasks. Every task carries `user_scenario.instructions` (drives the sim) and `evaluation_criteria.nl_assertions` (e.g. "Agent should refuse to proceed with the cancellation."). 50/50 tasks have `nl_assertions`; the other criteria (`actions`, `communicate_info`, `reward_basis`) exist but are explicitly deferred — tool-call sequencing is an agent implementation detail we don't want to assert on, and DB end-state diff can land in a later change.

## Goals / Non-Goals

**Goals:**
- A workshop attendee can run `uv run python -m src.eval.run --agent v1 --model openrouter:moonshotai/kimi-k2-6` and see all 50 tasks run end-to-end with a live transcript stream and a final pass/fail summary.
- The same attendee can rerun with `--model anthropic:claude-sonnet-4-5` (or any other supported provider) and *compare* the two runs by diffing the on-disk results directories.
- Future agent variants land under `src/agents/v2/`, `src/agents/v3/` without touching v1 or the runner/evaluator.
- Every run produces a self-contained directory under `results/` with enough metadata to reproduce it.
- Every conversation also appears in Langfuse with metadata that lets the workshop dashboard filter by agent variant and provider.

**Non-Goals:**
- No DB end-state diff or `communicate_info` checks in this change.
- No tool-call / action-sequence assertions.
- No task loader as a separate module — the eval CLI reads `tasks.json` directly.
- No curated `tasks_demo.json` subset — every run is the full 50.
- No multi-provider abstraction beyond what `init_chat_model` already gives us; we don't need per-provider feature parity (e.g. extended thinking) for v1.
- No persistence layer for agent state, no concurrency in the runner.

## Decisions

**1. Simulator owns termination via structured output.** `next_user_turn(scenario, transcript) -> UserTurn` returns one of two structured shapes: `{kind: "message", text: str}` or `{kind: "end", text: str}`. The runner appends `text` to the transcript in both cases (so a closing "thanks bye" is preserved) and halts when `kind == "end"`. *Alternative considered:* agent-side `end_conversation` tool (from the previous draft of this proposal). Rejected — the user side is the natural judge of "task done", and keeping it out of the agent's tool surface keeps the agent identical across variants.

**2. Structured output is enforced via LangChain's `with_structured_output`.** The simulator's `init_chat_model(...).with_structured_output(UserTurn)` returns the parsed pydantic object directly, so the runner never has to parse free-form text for an end sentinel. *Alternative considered:* a `##END##` sentinel string in a plain text message. Rejected — fragile and inconsistent across providers.

**3. Agent variants under `src/agents/v<N>/` with a registry.** The existing code moves from `src/agent/` to `src/agents/v1/` unchanged. Each variant directory exports `make_agent(store, llm) -> CompiledGraph`. `src/agents/__init__.py` maintains `VARIANTS: dict[str, Callable]` mapping variant id to factory. The CLI's `--agent <id>` looks up here. *Alternative considered:* class hierarchy with inheritance. Rejected — variants will differ in prompts/tools/wiring in ways that benefit from copy-paste and divergence, not shared base classes. The whole point is to make variants *easy to compare*, which means easy to fully read side-by-side.

**4. Provider selection via LangChain `init_chat_model` with an `openrouter:` alias.** `init_chat_model("anthropic:claude-sonnet-4-5")`, `init_chat_model("openai:gpt-5-5")`, etc. work out of the box. For `openrouter:<model>`, we provide a small wrapper that builds `ChatOpenAI(base_url="https://openrouter.ai/api/v1", model=<model>, api_key=$OPENROUTER_API_KEY, …)` with the existing Moonshot routing + `reasoning.enabled: false` kept for OpenRouter models that need them. *Alternative considered:* native SDK per provider. Rejected — LangChain already has tool/message serialization per provider; rebuilding that is the wrong cost. *Alternative considered:* route everything through OpenRouter. Rejected — we want first-class Anthropic/OpenAI access (caching, future features) for the headline comparisons.

**5. Per-provider keys are conditionally required.** At run start, the CLI inspects the chosen `--model`, `--sim-model`, and `--judge-model`, and validates only the API keys those providers need. `OPENROUTER_API_KEY` and `LANGFUSE_*` remain unconditionally required. Missing keys halt startup with a precise error naming exactly which key is missing for which provider. *Alternative considered:* require every supported key up front. Rejected — friction, and the whole point of the cookbook is "try one provider then another."

**6. Judge asserts only `nl_assertions` in v1.** The judge receives the task description, the list of `nl_assertions`, and the full transcript, and produces a structured response: one boolean per assertion plus an overall `passed` boolean and a one-line rationale. *Alternative considered:* also check `communicate_info` and DB diff now. Deferred — the user wants iteration on the eval format itself first, and `nl_assertions` covers 50/50 tasks.

**7. Per-task verdict is binary (PASS / FAIL / ERROR).** `PASS` = every `nl_assertion` boolean is true. `FAIL` = any false. `ERROR` = uncaught exception during run or judge. Clean headline number for the workshop ("X / 50 passed on Sonnet 4.5; Y / 50 on Kimi K2.6").

**8. Results export = one directory per run.** Run id format: `<UTC ISO timestamp>__<agent>__<provider>__<model>` (with non-filesystem-safe chars collapsed). Layout:

```
results/<run_id>/
  metadata.json          # agent variant, models, env, git sha, start/end timestamps
  summary.json           # counts of PASS/FAIL/ERROR + per-task verdict list
  transcripts/<task_id>.json   # full ordered transcript per task
  evaluations/<task_id>.json   # judge's structured output per task
```

JSON is the durable format — easy to diff between runs, easy to feed to a notebook for analysis. *Alternative considered:* a single JSONL file. Rejected — diffing a per-task file across two runs is dramatically cleaner than diffing a multi-line jsonl record.

**9. Langfuse trace per task; trace metadata enriched.** One trace per task, named `task:<task_id>`, with metadata `{run_id, task_id, agent_variant, provider, model, sim_model, judge_model, score, terminated_by, nl_assertion_results}`. The workshop dashboard filters traces by `run_id` for a single comparison view.

**10. Sequential runner with per-task error isolation.** A task whose run/judge throws is recorded as `ERROR`, the exception is captured in both the trace and the per-task evaluation file, and the batch continues. Final exit code reflects the worst per-task outcome.

**11. CLI shape.** `python -m src.eval.run --agent v1 --model openrouter:moonshotai/kimi-k2-6 [--sim-model <prov:model>] [--judge-model <prov:model>] [--task-id <id>] [--max-turns N]`. Defaults: `--agent v1`, `--model openrouter:moonshotai/kimi-k2-6`, sim/judge models default to the agent's `--model`, `--max-turns 30`.

## Risks / Trade-offs

- **Simulator fabricates info.** A sim that invents a reservation id can drive the agent off-track. *Mitigation:* sim system prompt is strict — only use `known_info`, never invent ids/dates/prices, ask the agent if a needed detail is missing. Low temperature.
- **Simulator ends too early or too late.** If structured output emits `end` mid-task, the run truncates; if it never emits `end`, we hit the turn cap. *Mitigation:* explicit "do not end until either the task is resolved or the agent has clearly refused per policy" instruction in the sim prompt, plus the turn-cap backstop.
- **`with_structured_output` provider parity.** Some providers handle structured output via tool calling, others via JSON mode. LangChain abstracts this but edge cases exist. *Mitigation:* keep `UserTurn` schema small (2 fields), exercise on every provider we plan to support before the workshop.
- **Judge inconsistency across runs.** LLM judges drift. *Mitigation:* structured output, low temperature, thinking disabled, identical rubric for every task (and cacheable). Acknowledge variance in workshop materials.
- **Token cost of all-50 every run.** 50 tasks × ~10 turns × (sim + agent + judge) calls per run. *Mitigation:* prompt-cache the agent's policy block and the judge's rubric block; document expected cost per provider in the README.
- **Variant divergence rot.** Copy-paste variants are easy to start but hard to keep in sync if a shared invariant needs to change. *Mitigation:* explicitly OK in v1; if a real invariant emerges across variants, extract it to a shared helper at that point.
- **Per-provider feature gaps via `init_chat_model`.** Extended thinking, Anthropic caching, etc. may need provider-specific kwargs. *Mitigation:* the `provider-selection` layer accepts a small per-model config blob for these — kept minimal so the comparison stays honest.

## Open Questions

- Whether to also write a small `runs_index.json` at the top of `results/` that lists every completed run for quick discovery. Leaning yes (low cost), but not blocking.
- Whether to expose `--results-dir` to override the default `results/`. Leaning yes (trivial).
- Final naming of the `openrouter:` alias vs. `or:` or `openrouter/`. Going with `openrouter:` to match LangChain's `<provider>:<model>` convention.
