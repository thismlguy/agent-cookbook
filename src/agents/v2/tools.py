"""v2 tools — re-export of v1's tool factory.

v2 is a prompt-only iteration over v1, so we share v1's `make_tools` directly.
A future variant that wants to change schemas or add tools should copy these
into its own module rather than aliasing.
"""
from __future__ import annotations

from src.agents.v1.tools import make_tools

__all__ = ["make_tools"]
