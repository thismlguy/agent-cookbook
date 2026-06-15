"""Specialist subagents for v2 — pure-Python policy-encoded functions.

Each specialist takes a typed input model and returns a discriminated-
union response (`ReadyToAct` / `Deny` / `TransferRequired`, plus the
compensation-specific `CompensationOffer` / `CompensationDeny`).
Specialists never talk to the user and never call other specialists.
"""
from __future__ import annotations

from src.agents.v2.subagents.booking_specialist import booking_specialist
from src.agents.v2.subagents.cancellation_specialist import cancellation_specialist
from src.agents.v2.subagents.compensation_specialist import compensation_specialist
from src.agents.v2.subagents.modification_specialist import modification_specialist

__all__ = [
    "booking_specialist",
    "cancellation_specialist",
    "compensation_specialist",
    "modification_specialist",
]
