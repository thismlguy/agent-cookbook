"""v1 tools — re-export of v0's tool factory.

v1 is a prompt-only iteration over v0, so we share v0's `make_tools` directly.
A future variant that wants to change schemas or add tools should copy these
into its own module rather than aliasing.
"""
from __future__ import annotations

from src.agents.v0.tools import make_tools

__all__ = ["make_tools"]
