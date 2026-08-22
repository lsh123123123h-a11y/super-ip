import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uuid_text() -> str:
    return str(uuid.uuid4())


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    storage_backend: Mapped[str] = mapped_column(String(64), default="local")
    locator_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Deprecated compatibility field. Runtime code must use the storage locator
    # and a provider staging adapter instead of persisting provider-owned paths.
    provider_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetRef(Base):
    __tablename__ = "asset_refs"
    __table_args__ = (
        UniqueConstraint("production_order_id", "asset_id", "role", name="uq_order_asset_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    production_order_id: Mapped[str] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), index=True)
    role: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConsentSnapshot(Base):
    __tablename__ = "consent_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    consent_type: Mapped[str] = mapped_column(String(64))
    grantor: Mapped[str] = mapped_column(String(200))
    scope_text: Mapped[str] = mapped_column(Text)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    granted: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
