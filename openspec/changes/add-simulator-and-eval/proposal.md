## Why

The foundational change shipped a runnable agent and chat UI, but `SOUL.md`'s third pillar — *evaluation: llm-as-judge over entire simulated conversations* — and the workshop demo path are still missing. On top of that, the cookbook's value comes from *comparing* agents: different prompt/tool variants against each other, and the same agent across different LLM providers (Kimi K2.6 vs Sonnet 4.5 vs GPT 5.5 vs Opus 4.7, …). Both axes need to be picked at run time, and every run needs a reproducible on-disk artifact so results can be diffed and shared.

## What Changes

- Add an LLM-based **user simulator** that plays the human side of a task, driven by `tasks.json` `user_scenario` (persona, reason_for_call, known_info, task_instructions). The simulator also **decides when the conversation is complete** and signals end-of-conversation via structured output — termination is the simulator's responsibility, not the agent's.
- Add a **conversation runner** that loops sim ↔ agent against a fresh `Store`, terminating when the simulator emits the end signal or a turn cap is hit.
- Relocate the current agent into a **versioned variant layout**: move `src/agent/` → `src/agents/v0/`, and introduce a small variant registry so future variants (`v1`, `v2`, …) can be added without disturbing `v0` and the eval CLI can pick which variant to run.
- Add **provider selection at run time** via LangChain's `init_chat_model`. The CLI accepts `--model anthropic:claude-sonnet-4-5`, `--model openai:gpt-5-5`, `--model openrouter:moonshotai/kimi-k2-6` (and similar `--sim-model` / `--judge-model`). A single `openrouter:` alias preserves the existing Kimi/Moonshot path; otherwise LangChain handles per-provider message/tool serialization. Per-provider API keys are *conditionally* required — strict-fail at run start lists exactly which keys are missing for the chosen configuration.
- Add an **LLM-as-judge evaluator** that scores a whole transcript per task. **v0 asserts only on `nl_assertions`** (50/50 tasks have these). Tool-call sequencing and DB end-state checks are intentionally deferred: tool calls are an agent implementation detail we don't want to assert on, and DB checking can land in a later change.
- Add an **eval CLI** (`uv run python -m src.eval.run`) that runs every task in `data/tasks.json` (all 50) through the chosen agent variant + provider, with per-task verdicts and a final summary. No curated subset — we run the full set every time.
- Add **per-run results export**: each run writes a new directory under `results/<run_id>/` containing run metadata (agent variant, provider, models, timestamp, git sha, env), every conversation transcript, and the judge's per-conversation report. This is the durable artifact for cross-run comparison and workshop sharing; Langfuse remains the live-tracing surface.
- Extend Langfuse traces with `task_id`, `agent_variant`, `provider`, `model`, and the judge's verdict so a run's traces can be filtered and aggregated.

## Capabilities

### New Capabilities
- `user-simulator`: LLM-driven user grounded strictly in `user_scenario`. Emits structured turns that are either a user message or an end-of-conversation signal.
- `conversation-runner`: drives sim ↔ agent loop on a fresh `Store`, captures the transcript, terminates on the simulator's end signal or turn cap.
- `agent-variants`: versioned agent layout under `src/agents/v<N>/` with a uniform factory contract (`make_agent(store, llm) -> CompiledGraph`) and a registry that lets the runner instantiate any registered variant by id. `v0` is the existing code, relocated unchanged.
- `provider-selection`: pick LLM provider + model id at run time for agent, simulator, and judge independently, via LangChain's `init_chat_model` plus a small `openrouter:` alias. Validates only the keys required for the chosen configuration.
- `eval-judge`: LLM-as-judge over the full transcript, asserting only on `nl_assertions` in this change. Produces a structured pass/fail per assertion plus an overall verdict and rationale.
- `eval-cli`: command-line entrypoint that runs every task in `data/tasks.json` through the selected agent variant + provider combination, streams progress, writes results to disk, and publishes traces to Langfuse.
- `results-export`: per-run directory layout containing run metadata, every transcript, and every judge report — enough to reproduce and diff results across runs.

### Modified Capabilities
- `observability`: extend each conversation trace with `task_id`, `agent_variant`, `provider`, `model`, `judge_score`, `nl_assertion_results`, and `terminated_by` so the workshop dashboard can filter and aggregate per run.

## Impact

- **Code relocation**: `src/agent/{graph.py, prompt.py, tools.py, architecture.md}` → `src/agents/v1/`. `app.py` and any other importers updated accordingly. The `airline-agent` capability's *requirements* do not change — only the source location.
- **New code** under `src/agents/__init__.py` (variant registry), `src/providers/` (provider/model selection helpers), `src/sim/`, `src/runner/`, `src/eval/{judge.py, run.py}`, `src/results/` (results-export helpers).
- **Optional new env vars**, conditionally required by the chosen run: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and similar per added provider. `OPENROUTER_API_KEY` and `LANGFUSE_*` remain required. Startup precheck lists missing keys *for the chosen configuration only*.
- **No new `end_conversation` tool on the agent** (termination moved to the simulator).
- **Out of scope** (explicitly deferred):
  - Task loader as a separate module — the eval CLI loads `tasks.json` inline.
  - Curated `tasks_demo.json` subset — every run uses the full 50 tasks.
  - Tool-call / action-sequence assertions — agent implementation detail.
  - `communicate_info` checks and DB end-state diff — to be added in a follow-up change once `nl_assertions`-only eval is working.
  - Persistence, prompt-tuning chapters, voice/audio dataset, per-turn judging, batch concurrency.
