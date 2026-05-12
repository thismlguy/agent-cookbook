## Why

The cookbook needs a runnable baseline before we can teach iterative development, evaluation, or workshop the codebase: an airline customer-support agent grounded in the tau2-bench dataset that a human can actually chat with end-to-end. This change establishes that baseline — domain, agent, chat UI, observability — so the next change can layer on a user simulator and our own LLM-as-judge evaluation.

## What Changes

- Introduce an in-memory mutable airline domain (flights, users, reservations) loaded from `data/db.json`, with `reset()` and `snapshot()` for per-session isolation.
- Define langchain `@tool` wrappers over the domain store with our own docstrings (free to redesign per SOUL.md). Tool *names* match the 10 tau2 action names referenced in `data/tasks.json` so action-level comparisons remain meaningful in the follow-up change: `get_user_details`, `get_reservation_details`, `search_direct_flight`, `book_reservation`, `update_reservation_flights`, `update_reservation_baggages`, `update_reservation_passengers`, `cancel_reservation`, `transfer_to_human_agents`, `calculate`. Additional read-only convenience tools allowed.
- Build a LangGraph ReAct agent whose system prompt is the full `data/policy.md` verbatim (no truncation), with tools bound. Provider is OpenRouter (via `langchain-openai`'s `ChatOpenAI` pointed at OpenRouter's OpenAI-compatible endpoint); default model is **Kimi K2.6** routed to the **Moonshot** provider (which supports prompt caching). Model id is env-overridable.
- Ship a Chainlit chat app (`app.py`) as the interactive entrypoint. A human can have a full booking / modification / cancellation conversation with tool calls rendered in the UI.
- Instrument every agent turn, LLM call, and tool call with Langfuse traces, tagged by session id.

## Capabilities

### New Capabilities
- `airline-domain`: typed entities and in-memory mutable store loaded from `data/db.json`, with deterministic reset and snapshot.
- `airline-agent`: LangGraph ReAct agent grounded in `data/policy.md`, with tau2-aligned tools bound.
- `chat-app`: Chainlit-based chat UI for interactive sessions against the agent.
- `observability`: Langfuse tracing on every agent turn, tool invocation, and LLM call.

### Modified Capabilities
- (none — this is the foundational change)

## Impact

- **New code** under `src/domain/`, `src/agent/`, `src/obs/`, and `app.py`.
- **New dependencies**: `langchain`, `langgraph`, `langchain-openai`, `chainlit`, `langfuse`, `pydantic`.
- **Configuration**: `.env` keys (`OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`); startup fails with a clear error if any are missing. `.env.example` mirrors `.env` with placeholder values.
- **Out of scope** (deferred to follow-up change `add-simulator-and-eval`): user simulator, conversation runner, our LLM-as-judge evaluator, `tasks.json` loader, batch runs, `end_conversation` termination tool.
