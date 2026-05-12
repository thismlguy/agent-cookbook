## ADDED Requirements

### Requirement: System prompt embeds the full policy
The agent SHALL embed the full content of `data/policy.md` in its system prompt, with no truncation or summarization.

#### Scenario: Policy text is present verbatim
- **WHEN** the agent is constructed
- **THEN** its system prompt contains the byte-equivalent contents of `data/policy.md`

### Requirement: Agent exposes tau2-aligned tools
The agent SHALL bind tools whose names include, at minimum: `get_user_details`, `get_reservation_details`, `search_direct_flight`, `book_reservation`, `update_reservation_flights`, `update_reservation_baggages`, `update_reservation_passengers`, `cancel_reservation`, `transfer_to_human_agents`, `calculate`.

#### Scenario: Tool names match tau2 ground truth
- **WHEN** the agent enumerates its bound tools
- **THEN** the set of tool names is a superset of the 10 tau2-aligned names listed above

### Requirement: Tool argument shapes remain tau2-compatible
Write tools SHALL accept argument shapes compatible with the corresponding tau2 action arguments in `data/tasks.json` so that recorded ground-truth action sequences can be replayed against our tools.

#### Scenario: Replaying a known action sequence
- **WHEN** a recorded `evaluation_criteria.actions` sequence from `data/tasks.json` is applied to our tools in order
- **THEN** every action executes without an argument validation error

### Requirement: Write tools mutate the domain store
Write tools SHALL operate on the active `Store` instance such that their effects are observable in subsequent reads.

#### Scenario: book_reservation creates a reservation
- **WHEN** the agent calls `book_reservation` with valid arguments
- **THEN** the new reservation is retrievable via `get_reservation_details`

### Requirement: Agent uses LangGraph
The agent SHALL be built using LangGraph's prebuilt ReAct agent (`create_react_agent` or equivalent), not a hand-rolled loop.

#### Scenario: Agent loop is LangGraph-driven
- **WHEN** the agent processes a user turn
- **THEN** the loop is executed by the LangGraph runtime (tool calls handled by the framework, not application code)

### Requirement: Provider is OpenRouter, routed to Moonshot
The agent SHALL send LLM requests to OpenRouter (via the OpenAI-compatible endpoint at `https://openrouter.ai/api/v1`) and SHALL pin routing to the Moonshot provider for the configured Kimi model.

#### Scenario: Requests target OpenRouter
- **WHEN** the agent makes an LLM call
- **THEN** the request is sent to OpenRouter's OpenAI-compatible endpoint with the `OPENROUTER_API_KEY` as the bearer

#### Scenario: Routing is pinned to Moonshot
- **WHEN** the agent makes an LLM call for a Kimi model
- **THEN** the request includes OpenRouter provider-routing configuration that restricts the request to the Moonshot provider

### Requirement: Default model is Kimi K2.6, env-overridable
The agent SHALL default to Kimi K2.6 as its model and SHALL read `MODEL_ID` from the environment to override this default.

#### Scenario: Default with no override
- **WHEN** `MODEL_ID` is not set
- **THEN** the agent uses Kimi K2.6 (Moonshot via OpenRouter)

#### Scenario: Switching model via env
- **WHEN** `MODEL_ID` is set to another model before agent construction
- **THEN** newly-constructed agent instances use the configured model id

### Requirement: Startup fails on missing OpenRouter key
The application SHALL refuse to start if `OPENROUTER_API_KEY` is not set in the environment.

#### Scenario: Missing key halts startup
- **WHEN** `OPENROUTER_API_KEY` is unset and the app starts
- **THEN** startup aborts with a clear error message naming the missing variable

### Requirement: System block is prompt-cached
The agent SHALL enable provider-side prompt caching on the system block (policy + tool descriptions) using Moonshot's caching support on OpenRouter.

#### Scenario: System block is cacheable across turns
- **WHEN** the agent makes a second LLM call within a session
- **THEN** the request is configured so Moonshot can serve the system block from cache, and cached-token usage is reflected in the response usage record

### Requirement: Thinking is disabled
The agent SHALL request thinking-disabled responses from Moonshot via OpenRouter's `reasoning.enabled: false` parameter. Rationale: `langchain-openai` does not preserve third-party `reasoning_content` on `AIMessage` round-trips, so a thinking response that includes a tool call cannot be replayed on the next turn without provoking a 400 from Moonshot. Disabling thinking sidesteps the round-trip entirely.

#### Scenario: Outbound request disables thinking
- **WHEN** the agent makes any LLM call
- **THEN** the JSON body sent to OpenRouter contains `"reasoning": {"enabled": false}`

#### Scenario: Tool-calling turn followed by continuation
- **WHEN** the agent emits a tool call on turn 1 and is invoked again on turn 2 with the resulting `ToolMessage` in history
- **THEN** the second LLM call completes successfully (no `reasoning_content is missing` error from Moonshot)
