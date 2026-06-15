# agent-cookbook

A production-grade cookbook for building and deploying LLM agents, using an airline customer support agent as the running example. Built on the [tau2-bench](https://github.com/sierra-research/tau2-bench) airline dataset (policy, tasks, DB).

## Stack

- **LangChain + LangGraph** — agent runtime
- **OpenRouter → Moonshot** — LLM provider, default model **Kimi K2.6**
- **Langfuse** — tracing and evaluation
- **Chainlit** — interactive chat UI

## Quickstart

```bash
# 1. install dependencies
uv sync

# 2. configure environment
cp .env.example .env
# fill in OPENROUTER_API_KEY and LANGFUSE_* keys

# 3. run the chat
uv run chainlit run app.py
```

Open [http://localhost:8000](http://localhost:8000) and start chatting with the agent.

### Environment variables

| Variable | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | OpenRouter API key — used by the Chainlit app and any `--model openrouter:*` eval run |
| `LANGFUSE_PUBLIC_KEY` | yes | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | yes | Langfuse project secret key |
| `LANGFUSE_BASE_URL` | yes | e.g. `https://us.cloud.langfuse.com` |
| `ANTHROPIC_API_KEY` | only if used | needed when an eval run selects an `anthropic:` model |
| `OPENAI_API_KEY` | only if used | needed when an eval run selects an `openai:` model |
| `MODEL_ID` | no | Override the default model id used by the Chainlit app |

Startup fails fast with a clear error listing exactly which keys are missing for the run's configuration.

## Run the evaluator

The evaluator runs every task in `data/tasks.json` through the chosen agent
variant and LLM provider, judges each transcript against the task's
`nl_assertions`, and writes a per-run results directory under `results/`.

```bash
# default: agent v1 on Kimi K2.6 via OpenRouter, all 50 tasks, 10 in parallel
uv run python -m src.eval.run

# tune concurrency (default 10; drop to 1 for sequential debugging or if you trip rate limits)
uv run python -m src.eval.run --concurrency 5

# pick a different provider/model
uv run python -m src.eval.run --model anthropic:claude-sonnet-4-5

# mix providers across roles (agent, simulator, judge)
uv run python -m src.eval.run \
  --model openrouter:moonshotai/kimi-k2.6 \
  --sim-model anthropic:claude-sonnet-4-5 \
  --judge-model openai:gpt-5-5

# debug a single task end-to-end
uv run python -m src.eval.run --task-id 0

# pick an agent variant (v0, v1, or v2 — orchestrator + specialists with a
# pending-action store; see src/agents/v2/architecture.md)
uv run python -m src.eval.run --agent v2 --task-id 0
```

Each run writes a directory like
`results/<UTC-ts>__<agent>__<provider>__<model>/` containing:

- `metadata.json` — agent variant, models, env, git sha, start/end timestamps
- `summary.json` — per-task verdicts + aggregate PASS/FAIL/ERROR counts
- `transcripts/<task_id>.json` — full ordered conversation per task
- `evaluations/<task_id>.json` — judge's structured output per task

Every task also appears as one Langfuse trace named `task:<task_id>`,
tagged with `run:<run_id>` so the workshop dashboard can filter to a
single run and compare two runs side by side.

### Sharing a run

`results/` is gitignored — every run is transient by default. To
publish a run for comparison or sharing, move its directory into
`published-runs/`, which is tracked in git:

```bash
mv results/<run_id> published-runs/
```

Browse the existing committed runs under `published-runs/`.

### Re-judge an existing run

To iterate on the judge prompt / model / schema without re-running the
expensive sim ↔ agent loop, point the CLI at an existing run directory:

```bash
# Same judge model, fresh verdicts (useful after editing src/eval/judge.py).
uv run python -m src.eval.run --rejudge-from results/<run_id>

# Swap in a different judge.
uv run python -m src.eval.run \
  --rejudge-from results/<run_id> \
  --judge-model anthropic:claude-sonnet-4-5

# Filter the rejudge to a subset.
uv run python -m src.eval.run --rejudge-from results/<run_id> --limit 5
uv run python -m src.eval.run --rejudge-from results/<run_id> --task-id 0
```

In rejudge mode, `--model` and `--sim-model` are ignored and only the
judge's provider API key (plus Langfuse) is required. The source run
is never modified — a fresh directory is created under
`results/<UTC-ts>__rejudge__<provider>__<model>/` with the same
transcripts copied through and brand-new evaluation files. The new
run's `metadata.json` includes a `source_run_id` field so lineage is
queryable, and every Langfuse trace is tagged `mode:rejudge`.

## Testing

```bash
# 1. install dev deps (one-time)
uv sync --group dev

# 2. run the test suite
uv run pytest tests/ -v
```

The e2e test (`tests/test_agent_e2e.py`) mocks the OpenRouter HTTPS endpoint with `respx`, drives the agent through a full ReAct loop (tool call → tool result → final reply), and asserts on the outbound JSON: model id, provider pin to Moonshot, `reasoning.enabled: false`, `max_completion_tokens`, full policy in the system prompt, and all 10 tau2-aligned tool definitions. Runs in under a second, no live API calls, no API key required.

## Repo layout

```
data/                   tau2-bench airline dataset (db.json, policy.md, tasks.json)
src/
  config.py             env loading + strict precheck
  domain/               typed entities + in-memory mutable store
  agents/               agent variants — v0/ is the flat ReAct baseline, v1/ is the current (XML-structured) agent
  providers/            provider/model selection (init_chat_model + openrouter alias)
  sim/                  LLM-driven user simulator
  runner/               sim ↔ agent conversation runner
  eval/                 LLM-as-judge + `python -m src.eval.run` CLI
  results/              per-run results-directory writer
  obs/                  Langfuse initialization
app.py                  Chainlit entrypoint
tests/                  pytest unit + respx e2e tests
openspec/               spec-driven change proposals
results/                per-run eval outputs (gitignored)
```
