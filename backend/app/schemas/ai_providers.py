from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


MODEL_ALIAS_PATTERN = r"^[a-z][a-z0-9_.-]{1,99}$"


class AIModelBindingWrite(BaseModel):
    model_alias: str = Field(pattern=MODEL_ALIAS_PATTERN)
    upstream_model: str = Field(min_length=1, max_length=200)
    enabled: bool = True


class AIModelBindingRead(AIModelBindingWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str


class AIProviderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    adapter_type: Literal["new_api"] = "new_api"
    base_url: str = Field(min_length=8, max_length=500)
    api_key: SecretStr | None = None
    default_model: str = Field(min_length=1, max_length=200)
    timeout_seconds: int = Field(default=120, ge=5, le=600)
    enabled: bool = True
    bindings: list[AIModelBindingWrite] | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("Base URL 必须使用 http:// 或 https://")
        if "@" in normalized.split("//", 1)[-1].split("/", 1)[0]:
            raise ValueError("Base URL 不得包含用户名或密码")
        return normalized


class AIProviderRead(BaseModel):
    id: str
    name: str
    adapter_type: str
    base_url: str
    secret_configured: bool
    secret_hint: str
    capability_types: list[str]
    default_model: str
    timeout_seconds: int
    enabled: bool
    status: str
    config_version: int
    last_tested_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    bindings: list[AIModelBindingRead]
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_tokens: int = 0
    average_latency_ms: int | None = None
    last_invoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AIProviderConnectionTest(BaseModel):
    provider_id: str | None = None
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    api_key: SecretStr | None = None
    timeout_seconds: int | None = Field(default=None, ge=5, le=120)

    @field_validator("base_url")
    @classmethod
    def validate_optional_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return AIProviderWrite.validate_base_url(value)


class AIProviderConnectionResult(BaseModel):
    ok: bool
    gateway_ref: str
    model_count: int
    models: list[str]
    latency_ms: int


class AIProviderEnabledUpdate(BaseModel):
    enabled: bool


class AIInvocationRead(BaseModel):
    id: str
    provider_config_id: str | None
    model_binding_id: str | None
    provider_config_version: int | None
    adapter_type: str | None
    adapter_version: str | None
    routing_policy: str
    routing_policy_version: str
    provider_name: str
    provider_source: str
    invocation_kind: str
    purpose: str
    model_alias: str
    requested_model: str
    response_model: str | None
    provider_request_id: str | None
    success: bool | None
    http_status: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_amount: Decimal | None
    cost_currency: str | None
    latency_ms: int | None
    error_code: str | None
    error_message: str | None
    metadata_payload: dict[str, object]
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class AIInvocationSummary(BaseModel):
    request_count: int
    success_count: int
    failure_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    average_latency_ms: int | None
    reported_cost: Decimal | None


class AIInvocationPage(BaseModel):
    summary: AIInvocationSummary
    items: list[AIInvocationRead]
