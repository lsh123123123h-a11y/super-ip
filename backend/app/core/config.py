from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "星流 AI API"
    environment: str = "development"
    api_prefix: str = "/v1"
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://xingliu:xingliu@localhost:5432/xingliu"
    redis_url: str = "redis://localhost:6379/0"
    workflow_queue: str = "xingliu:workflow:queue"
    max_workflow_attempts: int = 3

    duix_base_url: str = "http://localhost:8383/easy"
    duix_shared_data_root: Path = Path("./data/duix")
    duix_container_data_root: str = "/code/data"
    duix_poll_interval_seconds: float = 2.0
    duix_timeout_seconds: float = 3600.0
    duix_missing_job_poll_limit: int = 5
    duix_mock: bool = False

    max_upload_bytes: int = 500 * 1024 * 1024

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
