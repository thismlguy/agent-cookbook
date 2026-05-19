"""Judge output schema."""
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
    # `passed` is advertised as required to the model via the JSON schema, but
    # we accept it as optional in our pydantic validation because some
    # providers (e.g. Kimi K2 via OpenRouter) occasionally omit it. The judge
    # re-derives it from the per-item booleans regardless.
    passed: bool | None = Field(
        default=None,
        description="True iff every assertion record passed (or there were no assertions).",
    )
    summary: str = Field(default="", description="One-line overall summary of the verdict.")
