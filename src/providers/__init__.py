"""Provider-selection layer — build chat models from `<provider>:<model>` specs."""
from src.providers.keys import required_keys_for, validate_env
from src.providers.select import build_chat_model, cache_system_prompt, parse_spec

__all__ = [
    "build_chat_model",
    "cache_system_prompt",
    "parse_spec",
    "required_keys_for",
    "validate_env",
]
