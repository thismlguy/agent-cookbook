"""System prompt assembly — the full policy.md, verbatim."""
from __future__ import annotations

from src.config import POLICY_PATH


def load_system_prompt() -> str:
    return POLICY_PATH.read_text()
