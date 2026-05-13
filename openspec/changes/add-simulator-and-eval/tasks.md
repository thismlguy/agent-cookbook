## 1. Agent variant scaffolding

- [x] 1.1 Move `src/agent/{graph.py, prompt.py, tools.py, architecture.md, __init__.py}` to `src/agents/v1/` preserving content.
- [x] 1.2 Update every importer (`app.py`, tests, anything in `src/`) to import from `src.agents.v1` instead of `src.agent`. Confirm `rg "src\.agent\b|src/agent\b"` returns no matches under the project.
- [x] 1.3 Add `src/agents/__init__.py` with `VARIANTS: dict[str, Callable[[Store, ChatModel], CompiledGraph]]` mapping `"v1"` to the v1 factory.
- [x] 1.4 Confirm `uv run chainlit run app.py --headless` still serves the v1 agent unchanged.

## 2. Provider-selection layer

- [x] 2.1 Add `src/providers/select.py` exposing `build_chat_model(spec: str) -> BaseChatModel` that parses `"<provider>:<model>"`.
- [x] 2.2 For `openrouter:<model>`, construct `ChatOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY, model=<model>, ...)`. For `openrouter:moonshotai/kimi-k2-*`, also set Moonshot provider routing and `reasoning.enabled: false` so existing behavior is preserved.
- [x] 2.3 For other prefixes, delegate to LangChain's `init_chat_model("<provider>:<model>")`.
- [x] 2.4 Add `src/providers/keys.py` exposing `required_keys_for(spec: str) -> set[str]` and `validate_env(specs: Iterable[str])` that aggregates required keys across the agent / sim / judge models and raises a single error listing every missing key with the role(s) that needed it.
- [x] 2.5 Smoke-test: build a chat model for at least `openrouter:moonshotai/kimi-k2-6` and one non-OpenRouter spec end-to-end (one round-trip call), to confirm the wiring works.

## 3. User simulator

- [x] 3.1 Add `src/sim/schemas.py` with a pydantic `UserTurn(kind: Literal["message","end"], text: str)`.
- [x] 3.2 Add `src/sim/simulator.py` with `make_simulator(scenario, llm)` returning a callable `next_user_turn(transcript) -> UserTurn`.
- [x] 3.3 Build the simulator system prompt: inline persona / known_info / reason_for_call / task_instructions verbatim; strict "use only these facts" preamble; explicit instruction on when to emit `kind == "end"` (only after the task is resolved or appropriately refused).
- [x] 3.4 Use `llm.with_structured_output(UserTurn)` so output is enforced; no sentinel parsing.
- [x] 3.5 Verify on a single task: simulator opens grounded in `reason_for_call`, asks (not invents) when a needed detail is absent, and emits `kind == "end"` only when the agent has resolved or refused per policy.

## 4. Conversation runner

- [x] 4.1 Add `src/runner/runner.py` defining `RunResult(transcript, turn_count, terminated_by)` and a `run_task(task, agent_id, agent_llm, sim_llm, max_turns, on_event=None) -> RunResult` entrypoint.
- [x] 4.2 Construct a fresh `Store`, instantiate the agent via `VARIANTS[agent_id](store, agent_llm)`, and construct the simulator via `make_simulator(task.user_scenario, sim_llm)`.
- [x] 4.3 Loop: simulator `next_user_turn(transcript)` → append `text` → if `kind == "end"`, set `terminated_by = "simulator_end"` and stop; else invoke the agent on the running message history → append the agent's reply (and resolve any tool calls fully) → next turn.
- [x] 4.4 Enforce `max_turns` (default 30); halt with `terminated_by = "max_turns"` if the simulator never emits end.
- [x] 4.5 Implement the `on_event` callback hook so the CLI can stream user/agent/tool entries per turn.
- [x] 4.6 Verify on a happy-path task: runner terminates via simulator end, transcript captures every turn including the final closing message, end-state `Store` reflects the agent's mutations.

## 5. Evaluation judge

- [x] 5.1 Add `src/eval/schemas.py` with `AssertionResult(assertion, passed, rationale)` and `JudgeResult(assertions: list[AssertionResult], passed: bool, summary: str)`.
- [x] 5.2 Add `src/eval/judge.py` exposing `judge(task, transcript, llm) -> JudgeResult`.
- [x] 5.3 Build a fixed-rubric judge system prompt that inlines the task description and the list of `nl_assertions`, and uses `llm.with_structured_output(JudgeResult)` to enforce shape.
- [x] 5.4 Compute overall `passed = all(a.passed for a in assertions)`; for tasks with empty `nl_assertions`, return an empty list and `passed = True` with a summary noting "no assertions applied".
- [x] 5.5 Verify on two tasks: one whose `nl_assertions` are obviously satisfied by a known good transcript, one obviously not — judge produces the matching verdict.

## 6. Results export

- [x] 6.1 Add `src/results/writer.py` exposing a `ResultsWriter(run_dir)` context manager that creates the directory and writes `metadata.json` at start.
- [x] 6.2 Compose the run id as `<UTC ISO timestamp>__<agent>__<provider>__<model>` with filesystem-unsafe characters collapsed (e.g., `/` → `-`, `:` → `-`).
- [x] 6.3 On each completed task, write `transcripts/<task_id>.json` (the runner's transcript) and `evaluations/<task_id>.json` (the judge's `JudgeResult` or an ERROR record).
- [x] 6.4 On run completion, write `summary.json` (per-task verdicts + aggregate counts) and update `metadata.json` with `end_ts` and `task_count`.
- [x] 6.5 Use stable key ordering in all emitted JSON (sort keys or fixed order) so two-run diffs are content-only.
- [x] 6.6 Best-effort capture `git_sha` from `git rev-parse HEAD`; tolerate missing git gracefully (sets `null`).

## 7. Eval CLI

- [x] 7.1 Add `src/eval/run.py` as the `python -m src.eval.run` entrypoint.
- [x] 7.2 Implement argparse with `--agent` (default `v1`), `--model` (default `openrouter:moonshotai/kimi-k2-6`), `--sim-model` (default = `--model`), `--judge-model` (default = `--model`), `--task-id` (optional), `--max-turns` (default 30).
- [x] 7.3 Validate env vars at startup via `validate_env({model, sim_model, judge_model})` plus the unconditional `OPENROUTER_API_KEY` + `LANGFUSE_*` set.
- [x] 7.4 Load `data/tasks.json` inline; optionally filter to `--task-id`.
- [x] 7.5 For each task, construct agent/sim/judge LLMs via `build_chat_model`, call the runner with an `on_event` callback that prints `[turn n] USER:` / `[turn n] AGENT:` / `[turn n] TOOL <name>(...) -> ...` lines, call the judge, write transcript + evaluation files, and print a per-task `task <id>: PASS|FAIL|ERROR — <summary>` line.
- [x] 7.6 Wrap each per-task pipeline in try/except so one failure does not abort the batch; ERROR tasks still produce transcript + evaluation files capturing the exception.
- [x] 7.7 Print final aggregate summary; exit non-zero if any task was not PASS.
- [x] 7.8 Smoke test: `uv run python -m src.eval.run --agent v1 --task-id 0` runs end-to-end and produces a complete results directory.

## 8. Observability wiring

- [x] 8.1 Extend `src/obs/langfuse.py` (or sibling helper) with a per-task trace context: trace name `task:<task_id>`, seeded metadata `{run_id, task_id, agent_variant, model, sim_model, judge_model}`, updated at end with `score`, `terminated_by`, `turn_count`, and `nl_assertion_results`.
- [x] 8.2 Ensure sim/agent/tool/judge spans all hang under the per-task trace.
- [x] 8.3 For ERROR tasks, attach the exception message and set `terminated_by = "error"`.
- [x] 8.4 Verify in Langfuse: one trace per task with all spans inside; filtering by `run_id` returns exactly the tasks from that run.

## 9. Project plumbing & docs

- [x] 9.1 Update `.env.example`: document optional `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (and any other added providers); note `SIM_MODEL_ID`/`JUDGE_MODEL_ID` are no longer used (the CLI flags supersede them).
- [x] 9.2 Update `README.md` quickstart with a "Run the evaluator" section showing the default invocation and at least one cross-provider example (`--model anthropic:claude-sonnet-4-5`), plus how to find the `results/<run_id>/` artifact.
- [x] 9.3 Add `results/` to `.gitignore`.
- [x] 9.4 Minimal tests under `tests/`: provider-selection parses each supported prefix; missing-key validation lists the right keys; judge schema-shape test on a synthetic transcript; results-export round-trip (write + reread + diff).
