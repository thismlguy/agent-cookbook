"""LLM-as-judge — scores nl_assertions for one transcript."""
from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.eval.schemas import JudgeResult


JUDGE_SYSTEM_PROMPT = """\
You are evaluating whether an airline customer-support agent satisfied a set
of natural-language assertions during a conversation with a (simulated)
customer.

You will be given the task description, the assertions to evaluate, and the
complete ordered transcript of the conversation (user messages, agent
messages, the tool calls the agent made, and the tool results returned).

For each assertion, decide independently whether the transcript as a whole
satisfies it. Ground every verdict in concrete evidence from the transcript.

Rules:
- Evaluate ONLY the listed assertions. Do not invent additional criteria.
- An assertion is satisfied if the agent's overall behavior across the whole
  conversation matches it, even if the agent took a different sequence of tool
  calls or wording than you might have chosen.
- An assertion is NOT satisfied if the agent's behavior clearly contradicts
  it, or if the conversation ended without the agent demonstrating it when it
  should have.
- Be decisive: every assertion gets a true/false verdict. Use the rationale to
  cite the moment in the transcript that drove your decision.
- The overall `passed` is true iff every assertion record passed.
- `summary` is one short line summarising the verdict.

Return your verdict in the required structured format.
"""


def _format_transcript(transcript: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, m in enumerate(transcript, start=1):
        role = m.get("role", "?")
        content = m.get("content", "")
        if role == "user":
            lines.append(f"[{i}] USER: {content}")
        elif role == "agent":
            text = (content or "").strip()
            if text:
                lines.append(f"[{i}] AGENT: {text}")
            for tc in m.get("tool_calls", []) or []:
                args = json.dumps(tc.get("args", {}), sort_keys=True)
                lines.append(f"[{i}] AGENT → tool {tc.get('name')}({args})")
        elif role == "tool":
            result = (content or "")
            if len(result) > 800:
                result = result[:800] + "…"
            lines.append(f"[{i}] TOOL {m.get('name', '?')} → {result}")
        else:
            lines.append(f"[{i}] {role.upper()}: {content}")
    return "\n".join(lines)


def _format_user_message(
    task: dict[str, Any],
    nl_assertions: list[str],
    transcript: list[dict[str, Any]],
) -> str:
    description = (task.get("description") or {}).get("purpose") or ""
    assertions_block = (
        "\n".join(f"{i + 1}. {a}" for i, a in enumerate(nl_assertions))
        if nl_assertions
        else "(none — verdict is vacuously pass)"
    )
    return (
        f"# Task description\n{description}\n\n"
        f"# Assertions to evaluate\n{assertions_block}\n\n"
        f"# Transcript\n{_format_transcript(transcript)}\n"
    )


def judge(
    task: dict[str, Any],
    transcript: list[dict[str, Any]],
    llm: BaseChatModel,
) -> JudgeResult:
    """Score a transcript against the task's nl_assertions.

    When `nl_assertions` is empty the judge short-circuits to a vacuous pass
    without calling the model.
    """
    nl_assertions = ((task.get("evaluation_criteria") or {}).get("nl_assertions")) or []

    if not nl_assertions:
        return JudgeResult(assertions=[], passed=True, summary="no assertions")

    # method="function_calling" is more robust than the default json_schema across
    # providers (especially Kimi K2 via OpenRouter, which does not strictly enforce
    # response_format JSON schemas for nested types).
    structured = llm.with_structured_output(JudgeResult, method="function_calling")
    messages = [
        SystemMessage(content=JUDGE_SYSTEM_PROMPT),
        HumanMessage(content=_format_user_message(task, nl_assertions, transcript)),
    ]
    result: JudgeResult = structured.invoke(messages)

    # Defensive recompute — the model occasionally disagrees with its own per-item booleans.
    passed = all(a.passed for a in result.assertions) if result.assertions else True
    if passed != result.passed:
        result = result.model_copy(update={"passed": passed})
    return result
