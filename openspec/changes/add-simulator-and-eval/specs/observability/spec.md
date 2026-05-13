## ADDED Requirements

### Requirement: Each evaluated task is one Langfuse trace
A batch evaluation run SHALL produce one Langfuse trace per task, named `task:<task_id>`, containing every simulator LLM call, agent LLM call, tool call, and the final judge call as spans inside.

#### Scenario: Trace exists per task
- **WHEN** the eval CLI finishes a task (PASS, FAIL, or ERROR)
- **THEN** Langfuse contains exactly one trace named `task:<task_id>` for that task in that run

#### Scenario: Trace contains all conversation spans
- **WHEN** a trace is opened for a finished task
- **THEN** spans exist for every simulator LLM call, every agent LLM call, every tool call, and a final `judge` span carrying the judge's structured output

### Requirement: Trace metadata identifies the run and its configuration
Each per-task trace SHALL attach metadata containing at least: `run_id`, `task_id`, `agent_variant`, `model`, `sim_model`, `judge_model`, `score` (`"PASS"|"FAIL"|"ERROR"`), `terminated_by`, `turn_count`, and the judge's `nl_assertion_results` (the per-assertion booleans + rationales).

#### Scenario: Filtering traces by run
- **WHEN** a developer filters Langfuse traces by `run_id`
- **THEN** they see exactly the per-task traces produced by that run

#### Scenario: Filtering traces by configuration
- **WHEN** a developer filters Langfuse traces by `agent_variant` or `model`
- **THEN** they see the per-task traces from every run with that variant/model

### Requirement: Error tasks still produce a trace
If a task errors out before reaching the judge, the trace SHALL still be created with `score = "ERROR"`, `terminated_by = "error"`, and the exception message attached to metadata.

#### Scenario: Crashed task is observable
- **WHEN** a task raises an uncaught exception during the run
- **THEN** its Langfuse trace exists with the exception message in metadata and `terminated_by == "error"`
