"""Environment configuration with strict startup precheck."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "db.json"
POLICY_PATH = DATA_DIR / "policy.md"

REQUIRED_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)

DEFAULT_MODEL_ID = "moonshotai/kimi-k2.6"


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str
    model_id: str


def load_config() -> Config:
    load_dotenv(REPO_ROOT / ".env")
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + f". Copy .env.example to .env and fill them in. Repo root: {REPO_ROOT}"
        )
    return Config(
        openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
        langfuse_public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        langfuse_secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        langfuse_base_url=os.environ["LANGFUSE_BASE_URL"],
        model_id=os.environ.get("MODEL_ID", DEFAULT_MODEL_ID),
    )
