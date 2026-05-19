# CLAUDE.md

Orientation for AI coding agents working in this repo. Keep it short — link out instead of restating.

## Conventions you must follow

- **Always run Python via `uv run`.** Bare `python` is not on PATH; `.venv/bin/python` bypasses uv's env management. Use `uv run python -m ...`, `uv run pytest ...`, `uv run chainlit run app.py`.
- **The eval CLI exits non-zero when any task FAILs or ERRORs** (`src/eval/run.py:517`). A non-zero exit does not mean the run is broken — check the printed summary.
- **`results/` is gitignored, `published-runs/` is tracked.** Move a run dir into `published-runs/` to share it.

## Where to look

| If you're working on… | Read this |
|---|---|
| Setup, env vars, full CLI reference | [README.md](README.md) |
| The agent's behavior rules (system prompt body) | [data/policy.md](data/policy.md) |
| Why a `tasks.json` assertion looks the way it does | [data/CHANGES.md](data/CHANGES.md) |
| Where the dataset came from / citation | [data/SOURCE.md](data/SOURCE.md) |
| v1 (baseline ReAct) agent architecture | [src/agents/v1/architecture.md](src/agents/v1/architecture.md) |
| v2 (XML-structured prompt) — what changed and why | [src/agents/v2/architecture.md](src/agents/v2/architecture.md) |
| Prompt-design principles applied in v2 | [src/agents/v2/prompting-best-practices.md](src/agents/v2/prompting-best-practices.md) |
| Project intent / workshop framing | [openspec/SOUL.md](openspec/SOUL.md) |
| Spec-driven change proposals | [openspec/changes/](openspec/changes/) |
| What the Chainlit user sees on launch | [chainlit.md](chainlit.md) |

## Repo shape (one-liner per dir)

- `src/agents/v{1,2,…}/` — agent variants, registered in `src/agents/__init__.py`. To add `v3`, add a sibling dir with a `make_agent(store, llm)` factory and register it.
- `src/eval/` — `python -m src.eval.run` CLI + LLM-as-judge.
- `src/runner/` — sim ↔ agent conversation loop.
- `src/sim/`, `src/domain/`, `src/providers/`, `src/results/`, `src/obs/` — see README "Repo layout" section.
- `data/` — tau2-bench airline dataset (policy, tasks, db) plus our additive changes.
- `tests/` — pytest suite, run with `uv run pytest tests/ -v`.

## Common commands

```bash
uv run chainlit run app.py                                # chat UI
uv run python -m src.eval.run                             # full eval (v1, default model, 10 in parallel)
uv run python -m src.eval.run --agent v2 --task-id 0      # single task on v2
uv run python -m src.eval.run --rejudge-from results/<id> # re-judge an existing run
uv run pytest tests/ -v                                   # tests
```

See [README.md](README.md) for the full flag reference (model selection, mixed providers, concurrency tuning, rejudge).
