## ADDED Requirements

### Requirement: Simulator produces structured turns
The user simulator SHALL expose a callable that, given a task `user_scenario` and the running transcript, returns a structured `UserTurn` value whose `kind` is either `"message"` (continue the conversation) or `"end"` (the simulator is ending the conversation). Both kinds carry a `text` payload — the user message itself for `"message"`, and the user's closing remark (e.g., thanks, goodbye) for `"end"`.

#### Scenario: Simulator opens with a message turn
- **WHEN** the simulator is called with the task scenario and an empty transcript
- **THEN** it returns a `UserTurn` with `kind == "message"` and non-empty `text` grounded in `reason_for_call` and `known_info`

#### Scenario: Simulator ends when task is resolved
- **WHEN** the agent has resolved the user's request or appropriately refused per policy, and the conversation has reached a natural closing point
- **THEN** the simulator returns a `UserTurn` with `kind == "end"` and `text` containing the closing remark

### Requirement: Simulator output is enforced as a structured schema
The simulator SHALL request its model output via LangChain's `with_structured_output` (or equivalent) bound to the `UserTurn` schema, so the runner never has to parse a free-form sentinel out of a text message.

#### Scenario: Output is parsed, not pattern-matched
- **WHEN** the simulator returns a turn
- **THEN** the returned value is a parsed `UserTurn` object, not a raw string, and the `kind` field is one of the two enum values

### Requirement: Simulator is grounded in scenario fields only
The simulator's system prompt SHALL instruct the model to use only the values present in `user_scenario` (`persona`, `reason_for_call`, `known_info`, `task_instructions`, `unknown_info`) and to refuse to fabricate identifiers, dates, prices, or other facts not given by the scenario.

#### Scenario: Missing detail prompts a question, not fabrication
- **WHEN** the agent requests information the scenario does not supply (e.g., a reservation id not in `known_info`)
- **THEN** the simulated user asks the agent or says it does not know, rather than inventing a value

### Requirement: Simulator end signal is gated on resolution or refusal
The simulator's prompt SHALL instruct it to emit `kind == "end"` only when the task is resolved or appropriately refused per policy, and to continue with `kind == "message"` otherwise. It SHALL NOT terminate solely because the agent has gone quiet, asked another clarifying question, or pushed back.

#### Scenario: Agent pushback does not end the conversation
- **WHEN** the agent refuses an action but the user has not yet acknowledged or wrapped up
- **THEN** the simulator returns `kind == "message"` continuing the exchange

### Requirement: Simulator uses the configured provider for the run
The simulator SHALL be constructed using the run's selected provider/model (defaulting to the agent's model unless `--sim-model` is supplied) via the project's provider-selection layer, with no provider-specific code in the simulator itself.

#### Scenario: Default simulator uses agent's model
- **WHEN** the eval CLI is invoked without `--sim-model`
- **THEN** the simulator's LLM is constructed for the same `provider:model` as `--model`

#### Scenario: Overriding the simulator's model per run
- **WHEN** the eval CLI is invoked with `--sim-model anthropic:claude-sonnet-4-5`
- **THEN** the simulator's LLM is constructed for `anthropic:claude-sonnet-4-5` regardless of the agent's model
