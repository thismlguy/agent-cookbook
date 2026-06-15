## ADDED Requirements

### Requirement: Agents are organized into versioned variants
The codebase SHALL place each agent implementation in its own directory under `src/agents/v<N>/`, with `v0` containing the foundational agent relocated from `src/agent/` (no behavior change). Each variant directory SHALL be self-contained — prompt, tools, and graph wiring live within the variant directory and may diverge freely across variants.

#### Scenario: v0 variant exists and is self-contained
- **WHEN** the repository is built
- **THEN** `src/agents/v0/` contains the agent's graph, prompt, and tool wiring, and importing the variant does not pull from any other variant directory

### Requirement: Variants expose a uniform factory contract
Every agent variant SHALL expose `make_agent(store, llm) -> CompiledGraph` (or equivalent agreed entrypoint) that accepts the active `Store` and a pre-configured LangChain chat model and returns a ready-to-invoke agent.

#### Scenario: Variant factory contract
- **WHEN** the runner calls `make_agent(store, llm)` on any registered variant
- **THEN** the returned object is a LangGraph-compatible agent that can be invoked with a message history and supports tool execution

### Requirement: Variants are registered for lookup by id
`src/agents/__init__.py` SHALL maintain a `VARIANTS` mapping from variant id (e.g., `"v0"`) to factory callable. Registering a new variant SHALL be a single-line addition to this mapping.

#### Scenario: Looking up a registered variant
- **WHEN** code calls `VARIANTS["v0"]`
- **THEN** it receives the `make_agent` callable for v0

#### Scenario: Looking up an unknown variant
- **WHEN** code calls `VARIANTS["v99"]` (not registered)
- **THEN** lookup raises a `KeyError` (or equivalent clear error) naming the missing variant

### Requirement: Importers update to the new path
Any module that imports from the old `src/agent/` path SHALL be updated to import from `src/agents/v0/` (or via the registry), and there SHALL be no stale references to `src/agent/` remaining in the codebase.

#### Scenario: No stale imports remain
- **WHEN** the project is built or its tests are run
- **THEN** no module imports from `src/agent/` and the package builds cleanly
