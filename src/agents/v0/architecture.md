# Agent architecture

## Per-session lifecycle

Every Chainlit chat session constructs its own `Store` and its own agent.
Nothing is shared across sessions — mutations from one chat cannot leak
into another.

```
   browser session  ──▶  app.py @cl.on_chat_start
                              │
                              ├──▶  Store.load_from_path(db.json)
                              │         flights (300) + users (500) + reservations (2000)
                              │
                              ├──▶  build_agent(config, store)
                              │         policy.md → system prompt
                              │         make_tools(store) → 10 @tools bound to THIS store
                              │         create_react_agent(model, tools, prompt)
                              │
                              └──▶  session_id = uuid4()
                                    cl.user_session.set(store, agent, session_id, history)
```

## ReAct loop (one turn)

`langgraph.prebuilt.create_react_agent` runs the loop. The model decides
on each step whether to call a tool or emit a final message. Tool
results flow back into the message history and the model is re-invoked.

```
                 ┌──────────────────────────┐
   user msg ───▶ │   messages: [...]        │ ◀─── tool result
                 │   + SystemMessage(policy)│
                 └────────────┬─────────────┘
                              │
                              ▼
                       ┌─────────────┐
                       │     LLM     │  (ChatOpenAI → OpenRouter → Moonshot)
                       │  Kimi K2.6  │
                       └──────┬──────┘
                              │
                ┌─────────────┴──────────────┐
                ▼                            ▼
        AIMessage.content              AIMessage.tool_calls
        (final reply, loop ends)       (loop continues)
                                            │
                                            ▼
                                    ┌───────────────┐
                                    │   ToolNode    │
                                    │  dispatches   │
                                    │  to bound     │
                                    │  Store        │
                                    └───────┬───────┘
                                            │
                                            ▼
                                   ToolMessage(result)
                                            │
                                            └────► loops back to messages
```

## LLM stack

```
   src/providers/select.py builds the LLM; src/agents/v0/graph.py
   wraps create_react_agent(llm, tools, prompt).
   ─────────────────────────────────────────
                ChatOpenAI(
                  model = <model id>       ◀── from --model CLI flag
                  openai_api_base = …/v1   ◀── OpenRouter OpenAI-compatible
                  openai_api_key  = …      ◀── OPENROUTER_API_KEY
                  extra_body = {provider:  ◀── pin routing
                    {only: [moonshotai]}}
                  max_tokens = 4096        ◀── per-request credit cap
                  temperature = 0
                )
                       │
                       ▼
          https://openrouter.ai/api/v1
                       │
                       ▼
                Moonshot AI provider
                       │
                       ▼
                  Kimi K2.6
                       │
                       ▼
              automatic prefix caching
              (system block → cache hit on turn 2+)
```

## Tool surface

10 tau2-aligned tools, all built by `make_tools(store)` so each closure
holds a reference to the same `Store` instance the agent was built with.

| Tool | Kind | What it does |
|------|------|--------------|
| `get_user_details` | read | look up a user profile by id |
| `get_reservation_details` | read | look up a reservation by id |
| `search_direct_flight` | read | find available flights origin → destination on a date |
| `calculate` | pure | safe arithmetic over `+ - * / // % **` and parens |
| `book_reservation` | write | create a reservation, resolve prices, append to user |
| `update_reservation_flights` | write | replace flights / cabin; record price diff |
| `update_reservation_baggages` | write | adjust baggage counts; charge $50 per extra paid bag |
| `update_reservation_passengers` | write | replace passengers (count cannot change) |
| `cancel_reservation` | write | remove reservation, return refund summary |
| `transfer_to_human_agents` | escape | end-of-policy escape hatch |

All tools return either a JSON-serializable result (dict / list / scalar) or
a string starting with `Error:` on validation failure. The agent sees the
error string and can recover or escalate to `transfer_to_human_agents`.

## Observability

Each agent invocation carries two LangChain callbacks. The callbacks
hook into the ReAct loop so every LLM call, tool call, and chain step
becomes a span.

```
   agent.ainvoke({messages}, config = {
     callbacks: [LangchainTracer,           ◀── Chainlit: renders steps in UI
                 langfuse_handler],         ◀── Langfuse: emits OTel spans
     metadata:  {langfuse_session_id: …}    ◀── groups all turns under one trace
   })
```

The Langfuse handler reads `langfuse_session_id` from metadata and tags
every span emitted during that invocation. Result: in the Langfuse UI,
all turns from a single Chainlit session are grouped under the same
session view, regardless of how many tool calls happened across them.

## File map

```
src/agents/v0/
├── prompt.py       load_system_prompt() — reads data/policy.md verbatim
├── tools.py        make_tools(store)    — factory yielding 10 @tool closures
└── graph.py        make_agent(store, llm) — create_react_agent(llm, tools, prompt)
```
