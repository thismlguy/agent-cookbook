"""Judge output schemas — one record per nl_assertion, plus an overall verdict."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AssertionResult(BaseModel):
    assertion: str = Field(description="The nl_assertion this record evaluates, copied verbatim.")
    passed: bool = Field(description="True iff the transcript satisfies the assertion.")
    rationale: str = Field(description="One-sentence justification grounded in the transcript.")


class JudgeResult(BaseModel):
    assertions: list[AssertionResult] = Field(
        description="One record per task nl_assertion, in the same order as the task."
    )
    passed: bool = Field(
        description="True iff every assertion record passed (or there were no assertions)."
    )
    summary: str = Field(description="One-line overall summary of the verdict.")
