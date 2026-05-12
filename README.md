# agent-cookbook

A production-grade cookbook for building and deploying LLM agents, using an airline customer support agent as the running example. Built on the [tau2-bench](https://github.com/sierra-research/tau2-bench) airline dataset (policy, tasks, DB).

## Stack

- **LangChain + LangGraph** — agent runtime
- **OpenRouter → Moonshot** — LLM provider, default model **Kimi K2.6**
- **Langfuse** — tracing and evaluation
- **Chainlit** — interactive chat UI

## Quickstart

```bash
# 1. install dependencies
uv sync

# 2. configure environment
cp .env.example .env
# fill in OPENROUTER_API_KEY and LANGFUSE_* keys

# 3. run the chat
uv run chainlit run app.py
```

Open [http://localhost:8000](http://localhost:8000) and start chatting with the agent.

### Environment variables

| Variable | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | OpenRouter API key |
| `LANGFUSE_PUBLIC_KEY` | yes | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | yes | Langfuse project secret key |
| `LANGFUSE_BASE_URL` | yes | e.g. `https://us.cloud.langfuse.com` |
| `MODEL_ID` | no | Override the default model (`moonshotai/kimi-k2.6`) |

Startup fails fast with a clear error if any required key is missing.

## Testing

```bash
# 1. install dev deps (one-time)
uv sync --group dev

# 2. run the test suite
uv run pytest tests/ -v
```

The e2e test (`tests/test_agent_e2e.py`) mocks the OpenRouter HTTPS endpoint with `respx`, drives the agent through a full ReAct loop (tool call → tool result → final reply), and asserts on the outbound JSON: model id, provider pin to Moonshot, `reasoning.enabled: false`, `max_completion_tokens`, full policy in the system prompt, and all 10 tau2-aligned tool definitions. Runs in under a second, no live API calls, no API key required.

## Repo layout

```
data/                   tau2-bench airline dataset (db.json, policy.md, tasks.json)
src/
  config.py             env loading + strict precheck
  domain/               typed entities + in-memory mutable store
  agent/                LangGraph agent: prompt, tools, graph
  obs/                  Langfuse initialization
app.py                  Chainlit entrypoint
tests/                  pytest + respx e2e tests with mocked OpenRouter
openspec/               spec-driven change proposals
```

## What's next

- `add-airline-domain-and-agent` (this) — runnable baseline with an interactive Chainlit chat.
- `add-simulator-and-eval` (next) — user simulator, conversation runner, our LLM-as-judge evaluator over the 50 `tasks.json` tasks.
