"""Runtime settings, read from environment variables (and a local .env file)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    # Per-turn work (extraction + reply) runs on a fast, cheap model;
    # the one-off recruiter summary runs on a stronger model.
    chat_model: str = os.getenv("CHAT_MODEL", "claude-haiku-5-5")
    summary_model: str = os.getenv("SUMMARY_MODEL", "claude-sonnet-5-5")
    database_path: Path = Path(os.getenv("DATABASE_PATH", str(ROOT_DIR / "data" / "screening.db")))
    client_config_path: Path = Path(os.getenv("CLIENT_CONFIG_PATH", str(ROOT_DIR / "config" / "client.json")))
    # A candidate with no reply for this long shows as "inactive" in the dashboard.
    inactive_after_hours: float = float(os.getenv("INACTIVE_AFTER_HOURS", "24"))
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    max_message_chars: int = 1000


settings = Settings()
