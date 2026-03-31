from anyio.functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    # GCP Configuration
    PROJECT_ID: str = "agent-triage"
    REGION: str = "asia-south1"

    # AI Engine
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Infrastructure
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # Pydantic Configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings: Settings = get_settings()
