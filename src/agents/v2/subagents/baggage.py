"""Free checked-bag allowance — the single source of truth for v2.

Encodes the `data/policy.md` <booking> "Checked bag allowance" table:
free bags per passenger as a function of (membership, cabin). Each extra
bag beyond the free allowance is $50.

Used by both `get_baggage_allowance` (the read tool) and
`booking_specialist` (which derives the paid-bag count itself rather than
trusting the LLM's arithmetic).
"""
from __future__ import annotations

# free bags per passenger, indexed by (membership, cabin)
FREE_BAGGAGE_TABLE: dict[str, dict[str, int]] = {
    "regular": {"basic_economy": 0, "economy": 1, "business": 2},
    "silver":  {"basic_economy": 1, "economy": 2, "business": 3},
    "gold":    {"basic_economy": 2, "economy": 3, "business": 4},
}

EXTRA_BAG_FEE_USD = 50


def free_allowance_per_passenger(membership: str, cabin: str) -> int | None:
    """Free bags per passenger; None if (membership, cabin) is unknown."""
    return FREE_BAGGAGE_TABLE.get(membership, {}).get(cabin)
