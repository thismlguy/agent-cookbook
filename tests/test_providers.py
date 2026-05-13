"""Provider-selection + key-validation unit tests."""
from __future__ import annotations

import pytest

from src.providers.keys import required_keys_for, validate_env
from src.providers.select import build_chat_model, parse_spec


def test_parse_spec_round_trip():
    assert parse_spec("openrouter:moonshotai/kimi-k2.6") == ("openrouter", "moonshotai/kimi-k2.6")
    assert parse_spec("anthropic:claude-sonnet-4-5") == ("anthropic", "claude-sonnet-4-5")
    assert parse_spec("openai:gpt-5-5") == ("openai", "gpt-5-5")


@pytest.mark.parametrize("bad", ["no-colon", ":model", "provider:", ""])
def test_parse_spec_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_spec(bad)


@pytest.mark.parametrize(
    "spec,expected_key",
    [
        ("openrouter:moonshotai/kimi-k2.6", "OPENROUTER_API_KEY"),
        ("anthropic:claude-sonnet-4-5", "ANTHROPIC_API_KEY"),
        ("openai:gpt-5-5", "OPENAI_API_KEY"),
    ],
)
def test_required_keys_per_provider(spec, expected_key):
    assert required_keys_for(spec) == {expected_key}


def test_required_keys_unknown_provider_is_empty():
    assert required_keys_for("madeup:foo") == set()


def test_validate_env_collects_all_missing_keys_into_one_error(monkeypatch):
    for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGFUSE_PUBLIC_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError) as ei:
        validate_env(
            {"agent": "anthropic:claude-sonnet-4-5", "sim": "openai:gpt-5-5"},
            extra_required=["LANGFUSE_PUBLIC_KEY"],
        )
    msg = str(ei.value)
    assert "ANTHROPIC_API_KEY" in msg and "needed by: agent" in msg
    assert "OPENAI_API_KEY" in msg and "needed by: sim" in msg
    assert "LANGFUSE_PUBLIC_KEY" in msg and "needed by: system" in msg


def test_validate_env_passes_when_all_present(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    validate_env({"agent": "openrouter:moonshotai/kimi-k2.6"}, extra_required=[])


def test_build_openrouter_kimi_pins_moonshot(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    llm = build_chat_model("openrouter:moonshotai/kimi-k2.6")
    assert llm.openai_api_base == "https://openrouter.ai/api/v1"  # type: ignore[attr-defined]
    assert llm.extra_body == {  # type: ignore[attr-defined]
        "provider": {"only": ["moonshotai"]},
        "reasoning": {"enabled": False},
    }


def test_build_openrouter_non_kimi_does_not_pin_moonshot(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    llm = build_chat_model("openrouter:anthropic/claude-3.5-sonnet")
    # Kimi-specific routing must NOT be set for non-Kimi OpenRouter models.
    assert llm.extra_body in (None, {})  # type: ignore[attr-defined]


def test_build_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    llm = build_chat_model("anthropic:claude-sonnet-4-5")
    assert type(llm).__name__ == "ChatAnthropic"
