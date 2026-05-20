"""Chainlit entrypoint — interactive airline agent chat.

Run: `chainlit run app.py`

Each browser session gets a fresh Store + fresh agent, isolated from
other sessions. Tool calls are rendered in the Chainlit UI via
LangchainTracer; the whole session corresponds to a single Langfuse
trace tagged with the Chainlit session id.

Select an agent variant with `AIRLINE_AGENT_VARIANT=v1|v2|v3` (default `v1`).
v3 emits `<confirmation_card>` tags before writes; this UI renders them
as Accept/Cancel buttons and binds Accept to `execute_pending_action`.
"""
from __future__ import annotations

import logging
import os
import uuid

import chainlit as cl
from chainlit.langchain.callbacks import LangchainTracer
from langchain_core.messages import AIMessage, HumanMessage

from src.agents import get_variant
from src.agents.v3.pending_actions import (
    execute_pending_action,
    render_post_execute_message,
)
from src.config import DB_PATH, load_config
from src.domain.store import Store
from src.obs.langfuse import init_langfuse, run_config
from src.providers import build_chat_model
from src.runner.runner import _extract_card  # reuse the same regex

# Strict precheck on import — fails fast if any required env var is missing.
CONFIG = load_config()
init_langfuse(CONFIG)

logger = logging.getLogger("airline-agent")
logger.setLevel(logging.INFO)


CHAT_MODEL_SPEC = f"openrouter:{CONFIG.model_id}"
AGENT_VARIANT = os.getenv("AIRLINE_AGENT_VARIANT", "v1")


@cl.on_chat_start
async def on_chat_start() -> None:
    store = Store.load_from_path(DB_PATH)
    llm = build_chat_model(CHAT_MODEL_SPEC)
    agent = get_variant(AGENT_VARIANT)(store, llm)
    session_id = str(uuid.uuid4())

    cl.user_session.set("store", store)
    cl.user_session.set("agent", agent)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("history", [])

    logger.info(
        "chat session started: session_id=%s variant=%s", session_id, AGENT_VARIANT
    )

    await cl.Message(
        content=(
            "Hello, I'm your airline customer support agent. I can help you "
            "**book**, **modify**, or **cancel** flight reservations, and handle "
            "**refunds and compensation**. How can I help today?\n\n"
            f"_Variant: `{AGENT_VARIANT}` — Langfuse session id: `{session_id}`_"
        )
    ).send()


async def _send_agent_reply(text: str) -> None:
    """Send the agent's text reply; if it contains a confirmation_card tag,
    strip the tag from the message and render Accept/Cancel actions."""
    card = _extract_card(text)
    if card is None:
        await cl.Message(content=text).send()
        return

    # Suppress the raw tag in the rendered message.
    stripped = text.replace(
        f'<confirmation_card action_id="{card["action_id"]}" kind="{card["kind"]}"/>',
        "",
    ).strip()
    actions = [
        cl.Action(
            name="accept_card",
            value=card["action_id"],
            label="Accept",
            description="Confirm and run this action",
        ),
        cl.Action(
            name="cancel_card",
            value=card["action_id"],
            label="Cancel",
            description="Don't run this action",
        ),
    ]
    await cl.Message(content=stripped or "Please review and confirm.", actions=actions).send()


@cl.action_callback("accept_card")
async def on_accept(action: cl.Action) -> None:
    store = cl.user_session.get("store")
    history = list(cl.user_session.get("history") or [])
    pa = store.pending_actions.get(action.value)
    if pa is None:
        await cl.Message(content="That action has expired — please re-request.").send()
        return
    exec_result = execute_pending_action(action.value, store)
    templated = render_post_execute_message(pa, exec_result, store)
    history.append(HumanMessage(content=templated))
    cl.user_session.set("history", history)
    await _drive_agent_with_history(history)


@cl.action_callback("cancel_card")
async def on_cancel(action: cl.Action) -> None:
    history = list(cl.user_session.get("history") or [])
    history.append(HumanMessage(content="Never mind, please don't proceed with that."))
    cl.user_session.set("history", history)
    await _drive_agent_with_history(history)


async def _drive_agent_with_history(history: list) -> None:
    agent = cl.user_session.get("agent")
    session_id: str = cl.user_session.get("session_id")
    cfg = run_config(session_id=session_id)
    cfg["callbacks"] = [LangchainTracer(), *cfg["callbacks"]]
    result = await agent.ainvoke({"messages": history}, config=cfg)
    new_messages = result["messages"]
    cl.user_session.set("history", new_messages)
    final = new_messages[-1]
    text = getattr(final, "content", "") or ""
    if text:
        if AGENT_VARIANT == "v3":
            await _send_agent_reply(text)
        else:
            await cl.Message(content=text).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    history: list = list(cl.user_session.get("history") or [])
    history.append(HumanMessage(content=message.content))
    cl.user_session.set("history", history)
    await _drive_agent_with_history(history)
