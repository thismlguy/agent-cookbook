"""LLM-driven user simulator — produces the next user turn from a task scenario."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.sim.schemas import UserTurn

# Max attempts to coax a valid UserTurn out of the model before giving up.
_SIM_MAX_ATTEMPTS = 3


def _extract_json_obj(text: str) -> dict | None:
    """Best-effort recovery of a JSON object from raw model text. Kimi with
    reasoning under json_schema sometimes wraps the object in ``` fences or
    trailing prose, which trips the strict structured-output parser. Strip
    fences, then try a whole-string parse, then the first balanced {...}."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(t[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    return None
    return None


def _format_scenario(scenario: dict[str, Any]) -> str:
    """Inline the task's user_scenario into the simulator's system prompt."""
    instructions = (scenario or {}).get("instructions") or {}
    parts: list[str] = []
    persona = (scenario or {}).get("persona")
    if persona:
        parts.append(f"## Your persona\n{persona}")
    reason = instructions.get("reason_for_call")
    if reason:
        parts.append(f"## Why you are calling\n{reason}")
    known = instructions.get("known_info")
    if known:
        parts.append(f"## What you know\n{known}")
    unknown = instructions.get("unknown_info")
    if unknown:
        parts.append(f"## What you do not know\n{unknown}")
    task = instructions.get("task_instructions")
    if task:
        parts.append(f"## Your task\n{task}")
    return "\n\n".join(parts) if parts else "(no scenario details provided)"


SIMULATOR_SYSTEM_TEMPLATE = """\
You are roleplaying a customer who is calling an airline customer-support agent.
Stay in character as the customer throughout the conversation.

# Hard rules
- Use ONLY the facts inside "## What you know" and "## Why you are calling" below.
- NEVER invent reservation ids, flight numbers, dates, prices, payment methods, names, or any other concrete value that is not explicitly given to you.
- If the agent asks for a detail you do not have, say you don't know or ask the agent how to proceed — do not fabricate.
- Speak naturally and concisely, like a real customer would in a chat.
- Do not narrate or explain — output only what the customer would say.

# Confirming a proposed action (only relevant if you ever see one)
- When the agent's latest reply presents a proposed action for you to confirm
  (a line beginning "[Confirmation requested]" summarizing a booking, change, or
  cancellation and its cost), decide using your task and the amounts shown:
    • If accepting matches your task, set `card_action = "accept"`.
    • If it does not (wrong details, price over your limit, or you want to
      pivot), set `card_action = "reject"` and explain in `text` what you want
      instead.
- Do NOT repeat or echo any tag, id, or the summary back. Set `card_action` and
  keep `text` to what a real customer would say (it can be brief or empty on accept).
- Leave `card_action` null whenever no "[Confirmation requested]" summary is present.

# When to end the conversation
- Emit `kind = "end"` ONLY after BOTH are true:
  1. The agent has resolved your task OR has clearly refused it on policy grounds, AND
  2. You have acknowledged the outcome and said something closing (e.g. "thanks, that's all" or "ok, bye").
- If the agent has merely pushed back or asked a clarifying question, keep `kind = "message"` and continue.
- If your task remains unresolved and the agent has not refused, keep `kind = "message"`.
- The closing `text` should be brief (one short sentence is enough).

# Scenario
{scenario_block}
"""


def _transcript_to_messages(transcript: list[BaseMessage]) -> list[BaseMessage]:
    """Flip the perspective of the agent-side transcript for the simulator.

    In the runner's transcript, the customer is `HumanMessage` and the
    agent is `AIMessage`. From the simulator's perspective, the agent is
    "the other party" (HumanMessage) and the customer is itself (AIMessage).
    Tool calls and tool results are dropped — the simulator only sees what
    a real customer would see.
    """
    flipped: list[BaseMessage] = []
    for m in transcript:
        if isinstance(m, HumanMessage):
            # the prior simulator output → now the simulator's own assistant turn
            flipped.append(AIMessage(content=m.content))
        elif isinstance(m, AIMessage):
            # the agent's reply → now the "other party" speaking to the simulator
            text = m.content if isinstance(m.content, str) else str(m.content)
            if not text.strip():
                continue  # tool-only turns have no visible text
            flipped.append(HumanMessage(content=text))
        elif isinstance(m, (ToolMessage, SystemMessage)):
            continue
    return flipped


SimulatorFn = Callable[[list[BaseMessage]], UserTurn]


def _reasoning_enabled(llm: BaseChatModel) -> bool:
    """True if `llm` is an openrouter model built with reasoning turned on (see
    providers.select._build_openrouter). Such models reject a forced tool_choice,
    so structured output must use json_schema rather than function_calling."""
    eb = getattr(llm, "extra_body", None) or {}
    r = eb.get("reasoning") if isinstance(eb, dict) else None
    r = r or {}
    return bool(r.get("enabled") or r.get("max_tokens") or r.get("effort"))


def make_simulator(scenario: dict[str, Any], llm: BaseChatModel) -> SimulatorFn:
    """Build a `next_user_turn(transcript) -> UserTurn` callable.

    `transcript` is the runner's full message history (HumanMessage for
    user, AIMessage for agent, ToolMessage for tool results). We flip
    its perspective internally — the simulator sees the agent as the
    other party and never sees tool calls.
    """
    system_prompt = SIMULATOR_SYSTEM_TEMPLATE.format(scenario_block=_format_scenario(scenario))
    # function_calling is the most provider-portable mode for structured output,
    # but it forces a tool_choice — which Moonshot rejects when Kimi reasoning is
    # on ("tool_choice 'specified' is incompatible with thinking enabled"). For a
    # reasoning-enabled model, fall back to json_schema (no forced tool call).
    method = "json_schema" if _reasoning_enabled(llm) else "function_calling"
    # include_raw=True so a parse miss returns {parsed, raw, parsing_error}
    # instead of raising — we then recover the JSON from raw rather than letting
    # one malformed sim turn ERROR the whole task (json_schema under Kimi
    # reasoning emits invalid JSON ~1 turn in several at scale).
    structured = llm.with_structured_output(UserTurn, method=method, include_raw=True)

    _NUDGE = HumanMessage(
        content=(
            "Your previous reply was not valid JSON. Respond with ONLY a single "
            "JSON object matching the schema (fields: kind, text, card_action) — "
            "no markdown fences, no commentary."
        )
    )

    def next_user_turn(transcript: list[BaseMessage]) -> UserTurn:
        messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
        flipped = _transcript_to_messages(transcript)
        if not flipped:
            # opening turn — prompt the simulator to start the conversation
            messages.append(
                HumanMessage(content="Start the conversation. Say what you want to accomplish.")
            )
        else:
            messages.extend(flipped)

        last_err: object = None
        for attempt in range(_SIM_MAX_ATTEMPTS):
            out = structured.invoke(messages)
            parsed = out.get("parsed") if isinstance(out, dict) else out
            if parsed is not None:
                return parsed
            last_err = out.get("parsing_error") if isinstance(out, dict) else None
            raw = out.get("raw") if isinstance(out, dict) else None
            content = getattr(raw, "content", "") or ""
            obj = _extract_json_obj(content if isinstance(content, str) else str(content))
            if obj is not None:
                try:
                    return UserTurn.model_validate(obj)
                except Exception as e:  # recovered JSON didn't fit the schema
                    last_err = e
            # perturb the (temperature-0, deterministic) input so the retry differs
            messages = messages + [_NUDGE]

        raise ValueError(
            f"simulator could not produce a valid UserTurn after "
            f"{_SIM_MAX_ATTEMPTS} attempts: {last_err}"
        )

    return next_user_turn
