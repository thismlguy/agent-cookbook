"""Per-provider API-key requirements — validate only the keys this run needs."""
from __future__ import annotations

import os
from typing import Iterable

from src.providers.select import parse_spec

PROVIDER_TO_KEY: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "google_vertexai": "GOOGLE_APPLICATION_CREDENTIALS",
    "groq": "GROQ_API_KEY",
    "mistralai": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "together": "TOGETHER_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def required_keys_for(spec: str) -> set[str]:
    """Return the set of env-var names this model spec needs to be runnable."""
    provider, _ = parse_spec(spec)
    key = PROVIDER_TO_KEY.get(provider)
    return {key} if key else set()


def validate_env(role_to_spec: dict[str, str], extra_required: Iterable[str] = ()) -> None:
    """Validate all env-vars required by the chosen specs are present.

    `role_to_spec` maps role name (e.g. "agent", "sim", "judge") to model
    spec. Aggregates required keys, then errors with a single message
    listing every missing key and which role(s) needed it.

    `extra_required` is unconditionally required (e.g. Langfuse keys).
    """
    needed: dict[str, set[str]] = {}  # key -> roles that need it
    for role, spec in role_to_spec.items():
        for key in required_keys_for(spec):
            needed.setdefault(key, set()).add(role)
    for key in extra_required:
        needed.setdefault(key, set()).add("system")

    missing = {k: roles for k, roles in needed.items() if not os.environ.get(k)}
    if not missing:
        return

    lines = ["Missing required environment variables:"]
    for key in sorted(missing):
        roles = ", ".join(sorted(missing[key]))
        lines.append(f"  - {key}  (needed by: {roles})")
    raise RuntimeError("\n".join(lines))
