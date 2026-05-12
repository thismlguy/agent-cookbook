"""Chainlit entrypoint — interactive airline agent chat.

Run: `chainlit run app.py`

Each browser session gets a fresh Store + fresh agent, isolated from
other sessions. Tool calls are rendered in the Chainlit UI via
LangchainTracer; the whole session corresponds to a single Langfuse
trace tagged with the Chainlit session id.
"""
from __future__ import annotations

import logging
import uuid

import chainlit as cl
from chainlit.langchain.callbacks import LangchainTracer
from langchain_core.messages import HumanMessage

from src.agent.graph import build_agent
from src.config import DB_PATH, load_config
from src.domain.store import Store
from src.obs.langfuse import init_langfuse, run_config

# Strict precheck on import — fails fast if any required env var is missing.
CONFIG = load_config()
init_langfuse(CONFIG)

logger = logging.getLogger("airline-agent")
logger.setLevel(logging.INFO)


@cl.on_chat_start
async def on_chat_start() -> None:
    store = Store.load_from_path(DB_PATH)
    agent = build_agent(CONFIG, store)
    session_id = str(uuid.uuid4())

    cl.user_session.set("store", store)
    cl.user_session.set("agent", agent)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("history", [])

    logger.info("chat session started: session_id=%s", session_id)

    await cl.Message(
        content=(
            "Hello, I'm your airline customer support agent. I can help you "
            "**book**, **modify**, or **cancel** flight reservations, and handle "
            "**refunds and compensation**. How can I help today?\n\n"
            f"_Langfuse session id: `{session_id}`_"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    agent = cl.user_session.get("agent")
    session_id: str = cl.user_session.get("session_id")
    history: list = cl.user_session.get("history") or []

    history = list(history) + [HumanMessage(content=message.content)]

    cfg = run_config(session_id=session_id)
    cfg["callbacks"] = [LangchainTracer(), *cfg["callbacks"]]
    result = await agent.ainvoke({"messages": history}, config=cfg)

    new_messages = result["messages"]
    cl.user_session.set("history", new_messages)

    final = new_messages[-1]
    text = getattr(final, "content", "") or ""
    if text:
        await cl.Message(content=text).send()
