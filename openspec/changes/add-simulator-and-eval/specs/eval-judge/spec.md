## ADDED Requirements

### Requirement: Judge scores whole transcripts, not single turns
The evaluator SHALL accept the full transcript of a task run and produce a structured per-task verdict in a single LLM call; it SHALL NOT score individual turns or tool calls in isolation.

#### Scenario: Judge receives the whole transcript
- **WHEN** the judge is invoked for a completed task run
- **THEN** its input includes the task's `description`, the full ordered transcript, and the list of `evaluation_criteria.nl_assertions` for that task, and produces a single verdict

### Requirement: Judge asserts only on `nl_assertions`
For this change, the judge SHALL evaluate each `nl_assertion` in `evaluation_criteria.nl_assertions` independently against the transcript. It SHALL NOT inspect `evaluation_criteria.actions`, `communicate_info`, or the end-state of the `Store`.

#### Scenario: Tool calls are not asserted on
- **WHEN** the judge runs on a transcript whose agent took a different action sequence from `evaluation_criteria.actions`
- **THEN** the judge's verdict depends only on the `nl_assertions`, not on which tools were called

#### Scenario: communicate_info is not asserted on in v1
- **WHEN** the judge runs on a task whose `evaluation_criteria.communicate_info` is non-empty
- **THEN** the judge's verdict ignores the `communicate_info` items and depends only on the `nl_assertions`

### Requirement: Judge output is a structured per-assertion record
The judge SHALL return a structured object containing: an array of `{assertion: str, passed: bool, rationale: str}` records (one per `nl_assertion`), an overall `passed: bool` (true iff every assertion passed), and a one-line `summary` string.

#### Scenario: All assertions pass
- **WHEN** every `nl_assertion` is satisfied by the transcript
- **THEN** every record's `passed` is true, the overall `passed` is true, and `summary` reflects the success

#### Scenario: Any assertion fails
- **WHEN** at least one `nl_assertion` is not satisfied
- **THEN** that record's `passed` is false with a rationale, and the overall `passed` is false

#### Scenario: Task with no nl_assertions
- **WHEN** a task has an empty `nl_assertions` list
- **THEN** the judge returns an empty assertions array, overall `passed` is true (vacuously), and `summary` notes that no assertions applied

### Requirement: Per-task overall score is binary
Each task's overall score SHALL be `PASS` iff the judge's overall `passed` is true. Otherwise, `FAIL`. A task whose run or judge raises an uncaught exception SHALL be scored `ERROR`.

#### Scenario: Pass requires every assertion
- **WHEN** the judge's overall `passed` is true
- **THEN** the task's score is `PASS`

#### Scenario: Exception during judge
- **WHEN** the judge raises an uncaught exception for a task
- **THEN** the task's score is `ERROR` and the exception message is recorded in the per-task evaluation output

### Requirement: Judge uses the selected provider
The judge SHALL be constructed using the run's selected provider/model (defaulting to `--model` unless `--judge-model` is supplied) via the project's provider-selection layer, with no provider-specific code in the judge itself.

#### Scenario: Overriding the judge model per run
- **WHEN** the CLI is invoked with `--judge-model anthropic:claude-sonnet-4-5`
- **THEN** the judge's LLM is constructed for `anthropic:claude-sonnet-4-5` regardless of the agent's or simulator's model

### Requirement: Judge requests are configured for consistency
The judge SHALL request low-temperature responses with thinking disabled where supported, and SHALL use structured output enforcement (e.g., `with_structured_output`) so the per-assertion record schema is parsed, not pattern-matched.

#### Scenario: Structured output shape
- **WHEN** the judge makes any LLM call
- **THEN** the call requests low temperature and uses structured-output enforcement bound to the judge's result schema
