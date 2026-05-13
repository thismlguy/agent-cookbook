"""Judge schema-shape tests (no live LLM)."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.eval.judge import judge
from src.eval.schemas import AssertionResult, JudgeResult


def test_judge_short_circuits_when_no_nl_assertions():
    task = {
        "id": "t",
        "description": {"purpose": "x"},
        "evaluation_criteria": {"nl_assertions": []},
    }
    result = judge(task, transcript=[], llm=MagicMock())
    assert result.passed is True
    assert result.assertions == []
    assert "no" in result.summary.lower() and "assertion" in result.summary.lower()


def test_judge_uses_structured_output_and_recomputes_overall():
    """The judge should defensively recompute `passed` from per-assertion bools."""
    fake_result = JudgeResult(
        assertions=[
            AssertionResult(assertion="a1", passed=True, rationale="ok"),
            AssertionResult(assertion="a2", passed=False, rationale="missed"),
        ],
        passed=True,  # model lied — judge should override
        summary="model-claimed-pass",
    )

    structured = MagicMock()
    structured.invoke = MagicMock(return_value=fake_result)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)

    task = {
        "id": "t",
        "description": {"purpose": "x"},
        "evaluation_criteria": {"nl_assertions": ["a1", "a2"]},
    }
    result = judge(task, transcript=[{"role": "user", "content": "hi"}], llm=llm)

    llm.with_structured_output.assert_called_once_with(JudgeResult, method="function_calling")
    assert structured.invoke.call_count == 1
    # Overall should reflect the per-assertion bools, NOT the model's claim.
    assert result.passed is False


def test_judge_keeps_passed_true_when_all_assertions_pass():
    fake_result = JudgeResult(
        assertions=[
            AssertionResult(assertion="a1", passed=True, rationale="ok"),
            AssertionResult(assertion="a2", passed=True, rationale="ok"),
        ],
        passed=True,
        summary="ok",
    )
    structured = MagicMock()
    structured.invoke = MagicMock(return_value=fake_result)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    task = {"id": "t", "description": {"purpose": "x"}, "evaluation_criteria": {"nl_assertions": ["a1", "a2"]}}
    result = judge(task, transcript=[], llm=llm)
    assert result.passed is True
