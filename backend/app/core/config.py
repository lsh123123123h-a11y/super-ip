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
    auto_create_schema: bool = False
    redis_url: str = "redis://localhost:6379/0"
    workflow_queue: str = "xingliu:workflow:queue"
    agent_queue: str = "xingliu:agent:queue"
    outbox_batch_size: int = 50
    runtime_recovery_interval_seconds: float = 10.0
    agent_operation_lease_seconds: int = 180
    agent_operation_retry_base_seconds: int = 10
    planning_timeout_seconds: int = 180
    planning_max_attempts: int = 3
    workflow_lease_seconds: int = 120
    max_workflow_attempts: int = 3
    avatar_provider_order: str = "duix,opentalking"
    avatar_route_policy_version: str = "avatar-route-v1"

    model_gateway_base_url: str = ""
    model_gateway_api_key: str = ""
    model_gateway_default_model: str = ""
    model_gateway_timeout_seconds: float = 120.0

    duix_base_url: str = "http://localhost:8383/easy"
    duix_shared_data_root: Path = Path("./data/duix")
    duix_container_data_root: str = "/code/data"
    duix_poll_interval_seconds: float = 2.0
    duix_timeout_seconds: float = 3600.0
    duix_missing_job_poll_limit: int = 5
    duix_mock: bool = False

    opentalking_base_url: str = ""
    opentalking_api_key: str = ""
    opentalking_render_enabled: bool = False
    opentalking_render_submit_path: str = "/xingliu/render"
    opentalking_render_query_path: str = "/xingliu/render/{job_id}"
    opentalking_timeout_seconds: float = 3600.0

    max_upload_bytes: int = 500 * 1024 * 1024

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def avatar_provider_priority(self) -> list[str]:
        providers = [item.strip().lower() for item in self.avatar_provider_order.split(",") if item.strip()]
        return providers or ["duix"]

    @property
    def model_gateway_configured(self) -> bool:
        return bool(
            self.model_gateway_base_url.strip()
            and self.model_gateway_api_key.strip()
            and self.model_gateway_default_model.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
