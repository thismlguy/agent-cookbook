"""Judge schema-shape tests (no live LLM)."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.eval.judge import judge
from src.eval.schemas import AssertionResult, JudgeResult


def _stub(verdict: JudgeResult) -> MagicMock:
    structured = MagicMock()
    structured.invoke = MagicMock(return_value=verdict)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


def test_judge_short_circuits_when_no_nl_assertions():
    """With no rubric to score, the judge returns a vacuous pass without calling the model."""
    llm = _stub(JudgeResult(assertions=[], passed=True, summary="unused"))
    task = {"id": "t", "description": {"purpose": "x"}, "evaluation_criteria": {"nl_assertions": []}}

    result = judge(task, transcript=[], llm=llm)

    assert result.passed is True
    assert result.assertions == []
    llm.with_structured_output.assert_not_called()


def test_judge_recomputes_overall_passed_from_per_assertion_bools():
    fake = JudgeResult(
        assertions=[
            AssertionResult(assertion="a1", passed=True, rationale="ok"),
            AssertionResult(assertion="a2", passed=False, rationale="missed"),
        ],
        passed=True,  # model lied — judge should override
        summary="model-claimed-pass",
    )
    llm = _stub(fake)
    task = {"id": "t", "description": {"purpose": "x"}, "evaluation_criteria": {"nl_assertions": ["a1", "a2"]}}

    result = judge(task, transcript=[{"role": "user", "content": "hi"}], llm=llm)

    llm.with_structured_output.assert_called_once_with(JudgeResult, method="function_calling")
    assert result.passed is False


def test_judge_keeps_passed_true_when_all_items_pass():
    fake = JudgeResult(
        assertions=[
            AssertionResult(assertion="a1", passed=True, rationale="ok"),
            AssertionResult(assertion="a2", passed=True, rationale="ok"),
        ],
        passed=True,
        summary="ok",
    )
    llm = _stub(fake)
    task = {"id": "t", "description": {"purpose": "x"}, "evaluation_criteria": {"nl_assertions": ["a1", "a2"]}}
    result = judge(task, transcript=[], llm=llm)
    assert result.passed is True


def test_judgeresult_coerces_stringified_assertions():
    """Some judge models return `assertions` as a JSON-encoded string instead of
    a list (Haiku via function-calling). Coerce rather than ERROR the whole task."""
    import json

    payload = {
        "assertions": json.dumps(
            [{"assertion": "a1", "passed": True, "rationale": "ok"}]
        ),
        "passed": True,
        "summary": "s",
    }
    result = JudgeResult.model_validate(payload)
    assert isinstance(result.assertions, list)
    assert len(result.assertions) == 1
    assert result.assertions[0].assertion == "a1"


def test_judgeresult_unparseable_string_still_raises():
    """A non-JSON string falls through to normal validation (a real error, not a
    silent pass)."""
    import pytest

    with pytest.raises(Exception):
        JudgeResult.model_validate({"assertions": "not json", "passed": True})
