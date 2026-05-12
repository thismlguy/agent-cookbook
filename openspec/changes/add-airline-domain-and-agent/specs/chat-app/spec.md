## ADDED Requirements

### Requirement: Chainlit entrypoint runs the airline agent
The codebase SHALL provide an `app.py` Chainlit entrypoint that starts a chat backed by a freshly-initialized airline agent.

#### Scenario: Starting the app
- **WHEN** a developer runs `chainlit run app.py`
- **THEN** they can send messages in the browser and receive agent responses

### Requirement: Each session gets isolated state
Each Chainlit chat session SHALL receive its own `Store` instance and its own agent instance, isolated from any other concurrent session.

#### Scenario: Two concurrent sessions do not share mutations
- **WHEN** two browser sessions are open and one session books a reservation
- **THEN** the other session does not see the new reservation

### Requirement: Tool calls render in the UI
Each tool call made by the agent SHALL be visible in the Chainlit UI with its name, arguments, and result.

#### Scenario: A booking call is visible
- **WHEN** the agent invokes `book_reservation`
- **THEN** the UI displays the tool name, the arguments passed, and the returned result
