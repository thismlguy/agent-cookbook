## Context

Initial vision in `SOUL.md`. Dataset shape: `data/db.json` (300 flights / 500 users / 2000 reservations), `data/policy.md` (~36 rules), `data/tasks.json` (50 scored tasks — consumed in the next change, not here). Scanning `tasks.json` shows 10 distinct tool names used as evaluation actions: `book_reservation`, `calculate`, `cancel_reservation`, `get_reservation_details`, `get_user_details`, `search_direct_flight`, `transfer_to_human_agents`, `update_reservation_baggages`, `update_reservation_flights`, `update_reservation_passengers`.

The cookbook is structured as one final agent (not multi-chapter), per the user's direction. This change builds the runnable skeleton; iteration and evaluation happen in later changes.

## Goals / Non-Goals

**Goals:**
- A human can run `chainlit run app.py` and have a full airline-support conversation, with tool calls rendered in the UI and traces in Langfuse.
- Tool *names* and *DB mutations* match tau2 semantics so the same `db.json` snapshots can be diffed against tau2 ground truth in the follow-up change.
- Domain store can be reset deterministically between sessions.

**Non-Goals:**
- No user simulator — the human is the user in this change.
- No evaluator, no `tasks.json` consumption, no batch runs.
- No prompt engineering beyond loading `policy.md` verbatim. Tuning belongs to a separate iteration.
- No multi-provider abstraction. Pick one provider, make the model id env-configurable, and move on.
- No persistence layer (SQLite, Postgres). In-memory only.

## Decisions

**1. Tool surface matches tau2 names, owns its own docstrings.** Tools are rewrapped with our own docstrings (per SOUL.md), but the 10 evaluated tool names from `tasks.json` are kept identical so ground-truth actions remain meaningful in the follow-up change. Read-only convenience tools beyond the 10 are allowed if they help the agent. Argument *shape* should remain tau2-compatible even though docstrings are ours — verify by replaying a known task's action sequence against our tools and checking the DB diff.

**2. Policy in system prompt verbatim, no truncation.** Per SOUL.md. Prompt-caching the system block is wired from day one — policy is ~7KB and rides every turn; cheap to set up, painful to retrofit.

**3. Mutable in-memory store, no persistence.** `db.json` is loaded once at process start; mutations live in memory. `reset()` reloads from disk. Faster iteration, simpler workshops.

**4. LangGraph prebuilt ReAct agent.** `langgraph.prebuilt.create_react_agent` covers the loop we need. A custom graph would add complexity we don't need until the simulator change.

**5. Provider = OpenRouter; default model = Kimi K2.6 routed to Moonshot, with thinking disabled.** We use `langchain-openai`'s `ChatOpenAI` pointed at `https://openrouter.ai/api/v1`. OpenRouter is OpenAI-API-compatible, so no dedicated LangChain package is needed. The OpenRouter `provider` parameter pins routing to Moonshot (which supports prompt caching for Kimi K2.x). We additionally pass `reasoning.enabled: false` to disable thinking. Reason: K2.6 is a thinking model and `langchain-openai` deliberately drops third-party `reasoning_content` when parsing responses (documented in its source). With thinking on, a tool-calling turn cannot be replayed on the next turn — Moonshot rejects with "reasoning_content is missing". Disabling thinking is the supported workaround; quality on airline-support tasks remains strong. Model id is env-overridable (`MODEL_ID`).

**6. Strict fail-on-missing-keys.** If `OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, or `LANGFUSE_BASE_URL` is missing at startup, the app refuses to start with a clear error. No silent degradation, no disable-flag escape hatch — keys are always expected to be present per the user's environment.

**7. Single agent, single thread per Chainlit session.** Each session gets a fresh agent + fresh `Store`. No multi-tenancy concerns; trivially correct.

**8. Forward-looking — termination will be an `end_conversation` tool.** Not implemented here (no simulator yet). Recorded so it surfaces in the next change. Rationale: LangGraph-idiomatic, lets the simulator recognize end-of-task without a sentinel-string parser.

## Risks / Trade-offs

- **Tool surface drift from tau2.** If we redesign tool *signatures* (arguments) beyond cosmetics, action-level eval comparison gets harder. Mitigation in Decision 1.
- **Policy + tool descriptions are large.** Without prompt caching, every turn re-pays the full token cost. Caching from day one mitigates.
- **No persistence means lost state on restart.** Acceptable — sessions are short, this is a teaching artifact.
- **OpenRouter + Moonshot lock-in.** Acceptable for now; provider-swap and model comparison can be a later chapter of the cookbook itself.
- **Caching dependency on OpenRouter passthrough.** Moonshot supports prompt caching for Kimi K2.x, but we depend on OpenRouter passing the caching headers through correctly. Verify during implementation by inspecting cached-token counts in Langfuse on the second turn of a session.
