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

    # Identity is an explicit adapter choice. Development headers are never
    # consulted when this is set to ``oidc``.
    auth_mode: str = "development"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: str = "RS256"
    oidc_tenant_claim: str = "tenant_id"
    oidc_roles_claim: str = "roles"
    oidc_permissions_claim: str = "permissions"
    oidc_auto_provision_users: bool = False
    service_principal_pepper: str = ""

    database_url: str = "postgresql+asyncpg://xingliu:xingliu@localhost:5432/xingliu"
    migration_database_url: str = ""
    auto_create_schema: bool = False
    redis_url: str = "redis://localhost:6379/0"
    workflow_queue: str = "xingliu:workflow:queue"
    agent_queue: str = "xingliu:agent:queue"
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 8
    outbox_retry_base_seconds: int = 5
    runtime_consumer_max_attempts: int = 8
    runtime_consumer_retry_base_seconds: int = 5
    runtime_consumer_lease_seconds: int = 180
    runtime_recovery_interval_seconds: float = 10.0
    agent_operation_lease_seconds: int = 180
    agent_operation_retry_base_seconds: int = 10
    agent_step_lease_seconds: int = 180
    agent_step_retry_base_seconds: int = 10
    agent_step_max_concurrency: int = 8
    evaluator_max_attempts: int = 3
    evaluator_retry_base_seconds: int = 10
    planning_timeout_seconds: int = 180
    planning_max_attempts: int = 3
    workflow_lease_seconds: int = 120
    max_workflow_attempts: int = 3
    avatar_provider_order: str = "duix,opentalking"
    avatar_route_policy_version: str = "avatar-route-v1"
    capability_extension_modules: str = ""
    evaluator_extension_modules: str = ""
    workflow_extension_modules: str = ""
    provider_extension_modules: str = ""
    executor_extension_modules: str = ""
    product_extension_modules: str = ""

    model_gateway_base_url: str = ""
    model_gateway_api_key: str = ""
    model_gateway_default_model: str = ""
    model_gateway_timeout_seconds: float = 120.0
    ai_provider_secret_key: str = ""

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
    asset_storage_root: Path | None = None
    asset_storage_backend: str = "local"
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_force_path_style: bool = False
    s3_presign_expiry_seconds: int = 900

    readiness_schema_revision: str = "20260822_0012"
    log_level: str = "INFO"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def avatar_provider_priority(self) -> list[str]:
        providers = [item.strip().lower() for item in self.avatar_provider_order.split(",") if item.strip()]
        return providers or ["duix"]

    def extension_modules(self, kind: str) -> list[str]:
        raw = getattr(self, f"{kind}_extension_modules", "")
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def model_gateway_configured(self) -> bool:
        return bool(
            self.model_gateway_base_url.strip()
            and self.model_gateway_api_key.strip()
            and self.model_gateway_default_model.strip()
        )

    @property
    def oidc_algorithm_list(self) -> list[str]:
        return [item.strip() for item in self.oidc_algorithms.split(",") if item.strip()]

    def production_configuration_errors(self) -> list[str]:
        errors: list[str] = []
        if self.environment.lower() == "production" and self.auth_mode == "development":
            errors.append("AUTH_MODE=oidc")
        if self.auth_mode == "oidc":
            if not self.oidc_issuer.strip():
                errors.append("OIDC_ISSUER")
            if not self.oidc_audience.strip():
                errors.append("OIDC_AUDIENCE")
            if not self.oidc_jwks_url.strip():
                errors.append("OIDC_JWKS_URL")
            if not self.oidc_algorithm_list:
                errors.append("OIDC_ALGORITHMS")
        elif self.auth_mode != "development":
            errors.append("AUTH_MODE")
        if self.asset_storage_backend == "s3":
            for name, value in (
                ("S3_BUCKET", self.s3_bucket),
                ("S3_ACCESS_KEY_ID", self.s3_access_key_id),
                ("S3_SECRET_ACCESS_KEY", self.s3_secret_access_key),
            ):
                if not value.strip():
                    errors.append(name)
        elif self.asset_storage_backend != "local":
            errors.append("ASSET_STORAGE_BACKEND")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
