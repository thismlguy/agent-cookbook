## ADDED Requirements

### Requirement: Provider and model are selected at run time
The codebase SHALL expose a helper (e.g., `build_chat_model(spec: str)`) that constructs a LangChain chat model from a `<provider>:<model>` string at run time, with no hard-coded provider in the agent, simulator, or judge.

#### Scenario: Building an Anthropic model
- **WHEN** the helper is called with `"anthropic:claude-sonnet-4-5"`
- **THEN** it returns a LangChain chat model that targets Anthropic with model id `claude-sonnet-4-5`

#### Scenario: Building an OpenAI model
- **WHEN** the helper is called with `"openai:gpt-5-5"`
- **THEN** it returns a LangChain chat model that targets OpenAI with model id `gpt-5-5`

### Requirement: OpenRouter is a first-class alias
The helper SHALL accept `"openrouter:<model>"` and construct `ChatOpenAI` pointed at OpenRouter's OpenAI-compatible endpoint (`https://openrouter.ai/api/v1`) authenticated with `OPENROUTER_API_KEY`. For Kimi K2.x models, the helper SHALL preserve Moonshot provider routing and `reasoning.enabled: false` so existing behavior is unchanged.

#### Scenario: Building an OpenRouter Kimi model
- **WHEN** the helper is called with `"openrouter:moonshotai/kimi-k2-6"`
- **THEN** the returned chat model targets `https://openrouter.ai/api/v1`, uses `OPENROUTER_API_KEY`, pins routing to Moonshot, and sends `reasoning.enabled: false`

#### Scenario: Building an OpenRouter model that is not Kimi K2.x
- **WHEN** the helper is called with `"openrouter:<some-other-model>"`
- **THEN** the returned chat model targets OpenRouter without forcing Moonshot routing

### Requirement: Provider-selection is composed via LangChain's `init_chat_model`
For non-OpenRouter providers (`anthropic:`, `openai:`, etc.), the helper SHALL delegate to LangChain's `init_chat_model` so that message/tool serialization across providers is handled by the framework, not by application code.

#### Scenario: Non-OpenRouter providers go through init_chat_model
- **WHEN** the helper is called with any non-`openrouter:` provider prefix
- **THEN** the underlying construction is performed by `init_chat_model` with the matching provider arguments

### Requirement: Per-provider API keys are conditionally required
At run start, the eval CLI SHALL determine the set of providers needed by the selected `--model`, `--sim-model`, and `--judge-model`, and SHALL validate that each required API key is present in the environment. Validation SHALL fail with a clear error naming every missing key and which provider/role required it.

#### Scenario: Required key missing
- **WHEN** the chosen agent model is `anthropic:claude-sonnet-4-5` and `ANTHROPIC_API_KEY` is unset
- **THEN** the CLI exits with an error naming `ANTHROPIC_API_KEY` and indicating it is needed for the agent's model

#### Scenario: Unused provider keys are not required
- **WHEN** every selected model uses `openrouter:` and `ANTHROPIC_API_KEY` is unset
- **THEN** the CLI proceeds normally and does not complain about the missing `ANTHROPIC_API_KEY`

### Requirement: LANGFUSE and OPENROUTER keys remain unconditionally required
Regardless of model selection, `OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` SHALL remain unconditionally required at run start, because OpenRouter is the default provider and Langfuse is the observability backbone.

#### Scenario: Langfuse keys still required for non-OpenRouter runs
- **WHEN** the run uses only non-OpenRouter models and a Langfuse key is missing
- **THEN** the CLI exits with the same missing-Langfuse-key error as today
