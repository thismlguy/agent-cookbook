# Purpose

i have been building agents in production for past 3 years. i want to create a github repo with my recommended cookbook of building and deploying agents in production, using an airline customer support agent as the running example. i also want to use this repo for giving live 1-hour workshops.

## What the cookbook must cover

- agent architecture: base prompt + tools + knowledge base
- iterative development: simple prompt → + tools → + policy → ...
- evaluation: llm-as-judge over entire simulated conversations (not single-turn or cached)

## Tech stack

- **langchain + langgraph** for the agent
- **langfuse** for observability and eval tracking (open source, cheap for personal use)
- **chainlit** for the chat ui (native tool-call rendering, langfuse-compatible)

## Dataset scope (tau2-bench airline)

use only the *dataset* from tau2-bench. user simulator, evaluator, and tools live in our codebase.

- **policy**: full `policy.md` (~36 substantive rules), no truncation
- **tasks**: all 50 in `tasks.json` for batch eval. curate a 6-8 task `tasks_demo.json` subset for live runs
- **tools**: hybrid port — lift db-manipulation logic from tau2's `src/tau2/domains/airline/tools.py` (14 tools total), rewrap each as a langchain `@tool` with our own docstrings
- **db**: copy `db.json`, load into an in-memory mutable store
- ignore voice/audio variants of the dataset

## Demo scope (1-hour workshop)

- **live**: run 2-3 representative tasks end-to-end through the user simulator
- **offline**: pre-computed langfuse dashboard with batch eval results across all 50 tasks
