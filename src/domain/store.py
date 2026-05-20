"""In-memory mutable airline store loaded from data/db.json."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .schemas import Flight, Reservation, User


class Store:
    """In-memory mutable view of the airline DB.

    Each Chainlit session constructs its own Store, so mutations are
    isolated. Use reset() to restore the on-disk snapshot.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._raw: dict[str, dict[str, Any]] = {}
        self.flights: dict[str, Flight] = {}
        self.users: dict[str, User] = {}
        self.reservations: dict[str, Reservation] = {}
        # v3 pending-action store. Typed as `dict[str, Any]` here so this
        # base module doesn't depend on v3 internals; v3 code constructs
        # the concrete `PendingAction` rows. Unused by v1/v2.
        self.pending_actions: dict[str, Any] = {}
        self.reset()

    @classmethod
    def load_from_path(cls, db_path: str | Path) -> "Store":
        return cls(Path(db_path))

    def reset(self) -> None:
        with open(self._db_path) as f:
            raw = json.load(f)
        self._raw = copy.deepcopy(raw)
        self.flights = {k: Flight(**v) for k, v in raw["flights"].items()}
        self.users = {k: User(**v) for k, v in raw["users"].items()}
        self.reservations = {k: Reservation(**v) for k, v in raw["reservations"].items()}
        self.pending_actions = {}

    def snapshot(self) -> dict[str, Any]:
        return {
            "flights": {k: v.model_dump() for k, v in self.flights.items()},
            "users": {k: v.model_dump() for k, v in self.users.items()},
            "reservations": {k: v.model_dump() for k, v in self.reservations.items()},
        }
