import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # GCP Configuration
    PROJECT_ID: str = "agent-triage"
    REGION: str = "asia-south1"

    # AI Engine
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"

    # Infrastructure
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    MOCKTRACES: bool = True
    LOG_DIR: Path = REPO_ROOT / "logs"
    LOG_FILE_PATH: Path = LOG_DIR / "mock_traces.log"

    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USE_TLS: bool = True
    SMTP_USER: str = os.getenv("SMTP_USER", "triage_agent")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "password-agent")  # Gmail app-password

    SRE_EMAIL_SENDER: str = "sre-alerts@triage.com"

    ONCALL_EMAIL_GROUP: list[str] = []

    @field_validator("ONCALL_EMAIL_GROUP", mode="before")
    @classmethod
    def parse_csv_emails(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [email.strip() for email in v.split(",")]
        return []

    # Pydantic Configuration
    model_config = SettingsConfigDict(env_file=REPO_ROOT / "app/.env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
