import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uuid_text() -> str:
    return str(uuid.uuid4())


class AIProviderConfig(Base):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_ai_provider_tenant_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    adapter_type: Mapped[str] = mapped_column(String(64), default="new_api", index=True)
    base_url: Mapped[str] = mapped_column(String(500))
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    secret_hint: Mapped[str] = mapped_column(String(32), default="")
    capability_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_model: Mapped[str] = mapped_column(String(200))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="untested", index=True)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AIModelBinding(Base):
    __tablename__ = "ai_model_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "model_alias", name="uq_ai_model_tenant_alias"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    provider_config_id: Mapped[str] = mapped_column(
        ForeignKey("ai_provider_configs.id", ondelete="CASCADE"), index=True
    )
    model_alias: Mapped[str] = mapped_column(String(100), index=True)
    upstream_model: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AIInvocation(Base):
    __tablename__ = "ai_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    provider_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_provider_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_binding_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_model_bindings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adapter_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    adapter_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    routing_policy: Mapped[str] = mapped_column(String(64), default="model_alias")
    routing_policy_version: Mapped[str] = mapped_column(String(64), default="1.0.0")
    provider_source: Mapped[str] = mapped_column(String(32), index=True)
    invocation_kind: Mapped[str] = mapped_column(String(64), default="brain.structured")
    purpose: Mapped[str] = mapped_column(String(100), index=True)
    model_alias: Mapped[str] = mapped_column(String(100), index=True)
    requested_model: Mapped[str] = mapped_column(String(200))
    response_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8), nullable=True
    )
    cost_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
