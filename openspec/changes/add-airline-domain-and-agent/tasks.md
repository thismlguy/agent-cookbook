## 1. Domain layer

- [x] 1.1 Define pydantic models for `Flight`, `User`, `Reservation` (and nested types) that round-trip with `data/db.json`.
- [x] 1.2 Implement `Store` with `load_from_path(path)`, `reset()`, `snapshot()`.
- [x] 1.3 Sanity check: loading `data/db.json` yields exactly 300 flights, 500 users, 2000 reservations.

## 2. Tool surface

- [x] 2.1 Implement read-only tools: `get_user_details`, `get_reservation_details`, `search_direct_flight`, `calculate`.
- [x] 2.2 Implement write tools: `book_reservation`, `update_reservation_flights`, `update_reservation_baggages`, `update_reservation_passengers`, `cancel_reservation`.
- [x] 2.3 Implement `transfer_to_human_agents`.
- [x] 2.4 Each tool returns a JSON-serializable result and a clear error message on validation failure.
- [x] 2.5 Replay one known task's action sequence against the tools and verify the resulting DB diff is plausible.

## 3. Agent

- [x] 3.1 Load `data/policy.md` and assemble the system prompt.
- [x] 3.2 Build the LangGraph agent via `create_react_agent` with tools bound.
- [x] 3.3 Wire `ChatOpenAI` to OpenRouter (`base_url=https://openrouter.ai/api/v1`, key from `OPENROUTER_API_KEY`). Default `MODEL_ID` to Kimi K2.6; pin routing to the Moonshot provider via OpenRouter's `provider` parameter.
- [x] 3.4 Enable prompt caching on the system block (Moonshot supports it). Confirm during smoke test that the second turn of a session shows cached-token usage in Langfuse.

## 4. Chat UI

- [x] 4.1 Wire `app.py` Chainlit entrypoint: new session → fresh `Store` + fresh agent.
- [x] 4.2 Stream agent text + tool calls + tool results into the UI.

## 5. Observability

- [x] 5.1 Initialize Langfuse from env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`) at startup; strict fail with a clear error if any are missing.
- [x] 5.2 Each chat session is one trace, tagged with a stable session id.
- [x] 5.3 Verify a single chat session produces a coherent trace in the Langfuse UI.

## 6. Project plumbing

- [x] 6.1 Add dependencies to `pyproject.toml`: `langchain`, `langgraph`, `langchain-openai`, `chainlit`, `langfuse`, `pydantic`.
- [x] 6.2 Add `.env.example` mirroring `.env` keys (`OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`) with placeholder values, so readers know what to set.
- [x] 6.3 Add a startup precheck: fail with a clear error listing any missing required env vars (`OPENROUTER_API_KEY`, `LANGFUSE_*`).
- [x] 6.4 README quickstart: install, copy `.env.example` → `.env`, run `chainlit run app.py`. Mention `MODEL_ID` as the override knob.
