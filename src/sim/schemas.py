"""Simulator output schema — one turn from the simulated user."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserTurn(BaseModel):
    """A single turn from the simulated user.

    `kind == "message"` means continue the conversation.
    `kind == "end"` means the simulator is ending the conversation;
    `text` carries the closing remark (e.g., a thanks/goodbye).
    """

    kind: Literal["message", "end"] = Field(
        description=(
            "Use 'message' to continue the conversation. Use 'end' only when "
            "the agent has resolved the task or refused it per policy AND you "
            "have wrapped up with a thanks or goodbye."
        )
    )
    text: str = Field(
        description="What the user says on this turn. For 'end', a brief closing remark."
    )
