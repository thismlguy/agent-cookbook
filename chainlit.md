# Airline Customer Support Agent

This is a demo agent from the **agent-cookbook** project — a production-grade walkthrough for building and deploying LLM agents. The running example is an airline customer-support agent built on the tau2-bench dataset.

## What I can help with

- **Book** a new flight reservation
- **Modify** an existing reservation (flights, cabin, baggage, passengers)
- **Cancel** a reservation and process refunds
- **Compensation** for cancelled or delayed flights (within policy)

## How to get started

Give me your **user id** (e.g. `mia_li_3668`) and tell me what you'd like to do. Examples:

- *"I'm `raj_sanchez_7340`, please pull up my reservations."*
- *"I want to book a one-way from ORD to PHL on 2024-05-26."*
- *"Cancel reservation Q69X3R — my plans changed."*

I follow a strict policy for every booking and modification — I'll always confirm before making any database changes.

## Under the hood

- **Model:** Kimi K2.6 via OpenRouter (Moonshot)
- **Framework:** LangChain + LangGraph (ReAct agent)
- **Tracing:** every turn flows to Langfuse — your session id is shown in the welcome message so you can look up the trace

Each browser session gets a fresh copy of the airline database, isolated from every other session.
