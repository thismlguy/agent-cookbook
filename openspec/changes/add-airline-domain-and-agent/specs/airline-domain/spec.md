## ADDED Requirements

### Requirement: Domain entities are typed
The codebase SHALL provide pydantic models for `Flight`, `User`, and `Reservation` (with nested types as needed) that round-trip cleanly with `data/db.json`.

#### Scenario: Loading db.json populates typed entities
- **WHEN** the store loads `data/db.json`
- **THEN** it exposes 300 flights, 500 users, and 2000 reservations as typed pydantic instances

### Requirement: Store is mutable and resettable
The store SHALL support in-memory mutation of users, flights, and reservations, and SHALL support a deterministic reset back to the on-disk snapshot.

#### Scenario: Mutations persist within a session
- **WHEN** code creates or modifies a reservation via the store API
- **THEN** subsequent reads from the same store instance reflect the mutation

#### Scenario: Reset restores original state
- **WHEN** code calls `store.reset()` after any mutations
- **THEN** the store contents are equivalent to a fresh load from `data/db.json`

### Requirement: Snapshot captures current state
The store SHALL expose a `snapshot()` method that returns a deep-copied serializable view of the current state.

#### Scenario: Snapshot is independent of subsequent mutations
- **WHEN** a caller captures `s = store.snapshot()` and the store is then mutated
- **THEN** `s` reflects the pre-mutation state
