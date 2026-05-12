## ADDED Requirements

### Requirement: Langfuse is initialized from environment
The codebase SHALL initialize the Langfuse client from environment variables: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`.

#### Scenario: Missing keys halt startup
- **WHEN** any of `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, or `LANGFUSE_BASE_URL` is not set and the app starts
- **THEN** startup aborts with a clear error naming the missing variable(s); there is no flag to disable tracing in this change

### Requirement: Each chat session is one trace
Every Chainlit chat session SHALL correspond to a single Langfuse trace, tagged with a stable session id.

#### Scenario: Trace contains all turns
- **WHEN** a developer opens a Langfuse trace for a completed session
- **THEN** every agent turn, tool call, and LLM call from that session appears as a span inside that trace

### Requirement: LLM calls produce generation spans
Each LLM call made by the agent SHALL produce a Langfuse generation span with input messages, output messages, and token usage.

#### Scenario: A turn's LLM call is observable
- **WHEN** the agent calls the LLM during a turn
- **THEN** a generation span exists with the messages sent, the messages received, and token usage

### Requirement: Tool calls produce spans
Each tool invocation SHALL produce a Langfuse span named after the tool, including its arguments and result.

#### Scenario: A tool call is observable
- **WHEN** the agent calls `book_reservation`
- **THEN** a span exists named `tool:book_reservation` (or equivalent) with the arguments and the returned result
