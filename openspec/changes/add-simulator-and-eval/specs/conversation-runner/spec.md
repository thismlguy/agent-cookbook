## ADDED Requirements

### Requirement: Runner orchestrates one task end-to-end
The conversation runner SHALL accept a single task plus the run's selected agent variant + provider configuration and produce a `RunResult` containing the full transcript, turn count, and the reason termination occurred.

#### Scenario: Successful run produces a transcript
- **WHEN** the runner is invoked on a task and the simulator emits an end signal
- **THEN** the returned `RunResult` contains an ordered transcript of user, agent, and tool entries; `turn_count`; and `terminated_by == "simulator_end"`

### Requirement: Each task starts from a fresh store
The runner SHALL construct a fresh `Store` loaded from `data/db.json` for every task, never reusing state across tasks within a batch.

#### Scenario: State is isolated between tasks
- **WHEN** the runner executes task A then task B
- **THEN** task B's starting `Store` is byte-equivalent to a freshly loaded `data/db.json`, regardless of what task A mutated

### Requirement: Runner alternates simulator and agent turns
The runner SHALL drive turns in strict alternation: simulator produces a `UserTurn`, the user `text` is appended to the message history, the agent is invoked with the full history, and the agent's reply (including any tool calls and resulting tool messages) is appended before the next simulator turn.

#### Scenario: Tool calls resolve before the next user turn
- **WHEN** the agent emits one or more tool calls on a turn
- **THEN** every tool runs and its `ToolMessage` is appended to history before the simulator is asked for the next user turn

### Requirement: Runner terminates on simulator end signal
The runner SHALL halt the loop as soon as the simulator returns a `UserTurn` with `kind == "end"`. The closing `text` SHALL still be appended to the transcript so it appears in the saved record.

#### Scenario: Simulator emits end
- **WHEN** the simulator returns `kind == "end"` on turn N
- **THEN** the runner appends the closing `text` to the transcript, records `terminated_by == "simulator_end"`, and returns without invoking the agent for turn N+1

### Requirement: Runner enforces a turn cap
The runner SHALL accept a `max_turns` parameter (default 30) and halt the loop if the simulator has not emitted an end signal by that turn, recording `terminated_by == "max_turns"`.

#### Scenario: Turn cap halts a runaway loop
- **WHEN** the simulator never emits `kind == "end"` and the run reaches `max_turns`
- **THEN** the runner halts, records `terminated_by == "max_turns"`, and returns the truncated transcript

### Requirement: Runner exposes a streaming hook for live demos
The runner SHALL accept an optional event callback that is invoked on each turn boundary with a structured event describing the user message, agent message, and any tool calls/results, so a CLI can render the conversation live.

#### Scenario: CLI receives per-turn events
- **WHEN** the runner is invoked with a non-null event callback
- **THEN** the callback is called at least once per turn with the event for that turn, in order

### Requirement: Runner is agent-variant-agnostic
The runner SHALL construct the agent for a task via the agent-variants registry using the run's `--agent` id, and SHALL NOT reference any variant-specific implementation directly.

#### Scenario: Variant id drives instantiation
- **WHEN** the runner is asked to run a task with `agent_id == "v1"`
- **THEN** the agent is instantiated by looking up `"v1"` in the variants registry and invoking the registered factory
