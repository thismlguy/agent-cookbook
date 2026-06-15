## ADDED Requirements

### Requirement: CLI is invokable as a Python module
The evaluation CLI SHALL be invokable as `uv run python -m src.eval.run` and SHALL be the single entrypoint for running an agent variant + provider combination against the task set.

#### Scenario: Module invocation
- **WHEN** a user runs `uv run python -m src.eval.run --agent v0 --model openrouter:moonshotai/kimi-k2-6`
- **THEN** the CLI loads `data/tasks.json`, runs every task through the conversation runner with the v0 agent on the Kimi K2.6 model, judges each transcript, and writes a results directory

### Requirement: CLI runs all tasks in tasks.json by default
The CLI SHALL load `data/tasks.json` inline (no separate task loader module) and execute every task in file order. There SHALL be no curated demo subset and no `tasks_demo.json` file in this change.

#### Scenario: Full-set run
- **WHEN** the CLI is invoked without `--task-id`
- **THEN** all 50 tasks in `data/tasks.json` are executed in file order

### Requirement: CLI accepts agent, provider, and model flags
The CLI SHALL accept the following flags:
- `--agent <id>` (default `v0`): variant id resolved against the agent-variants registry.
- `--model <provider:model>` (default `openrouter:moonshotai/kimi-k2-6`): agent's chat model spec.
- `--sim-model <provider:model>` (optional): simulator's chat model spec; defaults to `--model`.
- `--judge-model <provider:model>` (optional): judge's chat model spec; defaults to `--model`.
- `--task-id <id>` (optional): run only the named task.
- `--max-turns N` (default 30): turn cap passed to the runner.

#### Scenario: Default invocation
- **WHEN** the CLI is invoked with no flags
- **THEN** it runs `v1` with `openrouter:moonshotai/kimi-k2-6` for agent, simulator, and judge, with a 30-turn cap

#### Scenario: Mixed providers
- **WHEN** the CLI is invoked with `--model anthropic:claude-sonnet-4-5 --sim-model openrouter:moonshotai/kimi-k2-6 --judge-model openai:gpt-5-5`
- **THEN** each role uses its corresponding provider; the per-provider key precheck validates `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, and `OPENAI_API_KEY` are all set

#### Scenario: Single-task run
- **WHEN** the CLI is invoked with `--task-id 12`
- **THEN** only task `12` is executed and the resulting directory contains a single transcript and evaluation entry

### Requirement: CLI streams per-turn output to the terminal
The CLI SHALL print a human-readable per-turn rendering for each task as it runs: user messages, agent messages, tool calls with arguments, and tool results, plus a per-task `PASS|FAIL|ERROR` verdict line at the end of each task.

#### Scenario: Live demo output
- **WHEN** the CLI is run interactively
- **THEN** for each task it prints turn-by-turn lines tagged with the speaker (USER/AGENT/TOOL) and finishes the task with `PASS`, `FAIL`, or `ERROR` plus a one-line rationale

### Requirement: Per-task errors do not abort the batch
The CLI SHALL isolate per-task failures (uncaught exceptions, judge errors, provider 4xx/5xx) so that the remaining tasks still run; the failing task is recorded as `ERROR` in both the live output and the results directory.

#### Scenario: One task crashes
- **WHEN** task N raises an uncaught exception during the run or judge
- **THEN** the CLI records the exception, marks task N as `ERROR`, and continues with task N+1

### Requirement: CLI exit code reflects worst per-task outcome
The CLI SHALL exit `0` only if every executed task was `PASS`; any `FAIL` or `ERROR` SHALL produce a non-zero exit code so CI / scripted comparisons can detect regressions.

#### Scenario: All pass
- **WHEN** every task is judged PASS
- **THEN** the CLI exits 0

#### Scenario: Any non-pass
- **WHEN** at least one task is FAIL or ERROR
- **THEN** the CLI exits non-zero

### Requirement: CLI validates required env vars up front
Before executing any tasks, the CLI SHALL validate the union of API keys required by the chosen `--model`, `--sim-model`, and `--judge-model` (per the provider-selection requirements) and the unconditionally-required Langfuse keys, and SHALL refuse to start if any are missing, naming each missing key and which provider/role required it.

#### Scenario: Missing provider key halts startup
- **WHEN** the run requires `ANTHROPIC_API_KEY` and it is unset
- **THEN** the CLI prints a clear error naming `ANTHROPIC_API_KEY` and exits non-zero without executing any task
