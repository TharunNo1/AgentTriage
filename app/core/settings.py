from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.models import RemediationMode


class Settings(BaseSettings):
    """All runtime configuration. Values come from the environment (prefix ``TRIAGE_``) or a local ``.env`` file."""

    model_config = SettingsConfigDict(env_prefix="TRIAGE_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: PostgresDsn
    database_pool_size: int = 10
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")

    max_body_bytes: int = 1_000_000
    rate_limit_per_minute: int = 600
    idempotency_ttl_seconds: int = 86_400
    mute_window_seconds: int = 3_600
    webhook_hmac_secrets: dict[str, SecretStr] = Field(default_factory=dict)
    hmac_max_skew_seconds: int = 300

    remediation_mode: RemediationMode = "dry_run"
    approval_ttl_seconds: int = 3_600
    verify_delay_seconds: int = 120
    max_reproposals: int = 1
    stuck_incident_seconds: int = 60

    triage_agent: Literal["mock", "gemini"] = "mock"
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    ticketing: Literal["mock", "jira"] = "mock"
    jira_site: str | None = None
    jira_project: str | None = None
    jira_issue_type_id: str | None = None
    jira_email: str | None = None
    jira_api_token: SecretStr | None = None
    notifier: Literal["mock", "slack", "resend"] = "mock"
    slack_webhook_url: SecretStr | None = None
    resend_api_key: SecretStr | None = None
    resend_from_email: str | None = None
    resend_to_email: str | None = None

    job_timeout_seconds: int = 300
    job_max_tries: int = 5
    worker_max_jobs: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required fields are read from the environment
