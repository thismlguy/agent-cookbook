## ADDED Requirements

### Requirement: Each run writes a self-contained results directory
The eval CLI SHALL create a new directory under `results/` for every run, named such that the agent variant, provider, model, and timestamp are visible in the directory name without opening it.

#### Scenario: Directory name embeds key facets
- **WHEN** a run completes for agent `v0` on `openrouter:moonshotai/kimi-k2-6` starting at UTC `2026-05-13T18:42:01Z`
- **THEN** the results directory is named `results/2026-05-13T18-42-01Z__v0__openrouter__moonshotai-kimi-k2-6/` (with filesystem-unsafe characters collapsed)

#### Scenario: No collisions between concurrent runs
- **WHEN** two runs are started within the same second with identical agent/model
- **THEN** the second run resolves the collision (e.g., by appending a short suffix) so each run has a unique directory

### Requirement: Run metadata is captured for reproducibility
The results directory SHALL contain a `metadata.json` capturing at least: `run_id`, `start_ts`, `end_ts`, `agent_variant`, `model`, `sim_model`, `judge_model`, `max_turns`, `git_sha` (best-effort if available), `task_count`, and the resolved set of API-key names used (not the values).

#### Scenario: Metadata exists
- **WHEN** a run completes (PASS, FAIL, or partial ERROR)
- **THEN** `metadata.json` exists in the run directory with all required fields populated

#### Scenario: Git sha is best-effort
- **WHEN** the working directory is not a git repository
- **THEN** `git_sha` is `null` and the run still completes normally

### Requirement: Every conversation transcript is exported
The results directory SHALL contain `transcripts/<task_id>.json` for every task that started a run (including ERROR tasks), containing the ordered transcript captured by the conversation runner with speaker, content, and any tool-call / tool-result records.

#### Scenario: Transcript per task
- **WHEN** the CLI finishes the run
- **THEN** `transcripts/` contains exactly one JSON file per task that was attempted, named by `task_id`

### Requirement: Every evaluation report is exported
The results directory SHALL contain `evaluations/<task_id>.json` for every task that was attempted, containing the judge's structured output (per-assertion records, overall `passed`, `summary`) or, for ERROR tasks, the captured exception message with `passed: null`.

#### Scenario: Evaluation per task
- **WHEN** the CLI finishes the run
- **THEN** `evaluations/` contains exactly one JSON file per attempted task, named by `task_id`, each parseable as the judge result schema (or its ERROR variant)

### Requirement: Run summary aggregates per-task outcomes
The results directory SHALL contain `summary.json` listing each `{task_id, score: "PASS"|"FAIL"|"ERROR", terminated_by, turn_count}` plus aggregate counts of PASS/FAIL/ERROR.

#### Scenario: Summary is queryable without opening per-task files
- **WHEN** a developer wants to scan a run's outcomes
- **THEN** `summary.json` exposes the verdict per task and the aggregate counts in a single file

### Requirement: Results directories are stable across runs
The output of two identical runs (same agent, same model, same task set, same seed where applicable) SHALL be diffable: per-task files keep stable shapes and key orders so a textual diff between two run directories is informative rather than dominated by formatting differences.

#### Scenario: Diff between two runs is informative
- **WHEN** two runs are executed back-to-back with the same configuration
- **THEN** diffing their `transcripts/` and `evaluations/` directories yields content-level differences only, not key-ordering or formatting noise
