import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uuid_text() -> str:
    return str(uuid.uuid4())


class UsageFact(Base):
    __tablename__ = "usage_facts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_usage_fact_tenant_dedupe"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(200), index=True)
    operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_operations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    step_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_step_executions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    capability_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    metric: Mapped[str] = mapped_column(String(100), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(220))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceBook(Base):
    __tablename__ = "price_books"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_price_book_tenant_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(16), default="internal_credit")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PricingRule(Base):
    __tablename__ = "pricing_rules"
    __table_args__ = (
        UniqueConstraint(
            "price_book_id",
            "metric",
            "provider_id",
            "model",
            "capability_key",
            name="uq_pricing_rule_dimensions",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    price_book_id: Mapped[str] = mapped_column(
        ForeignKey("price_books.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[str] = mapped_column(String(100), index=True)
    provider_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    capability_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str] = mapped_column(String(32))
    unit_size: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantQuota(Base):
    __tablename__ = "tenant_quotas"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "metric", "period", "period_start", name="uq_tenant_quota_period"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(100), index=True)
    period: Mapped[str] = mapped_column(String(32))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    hard_limit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    soft_limit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    used_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageReservation(Base):
    __tablename__ = "usage_reservations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_reservation_tenant_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    quota_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenant_quotas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    production_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("production_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_operations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metric: Mapped[str] = mapped_column(String(100), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(32))
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(16), default="internal_credit")
    pricing_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("pricing_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    price_book_version: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="reserved", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(220))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_ledger_tenant_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    entry_type: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(16), default="internal_credit")
    metric: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(200), index=True)
    usage_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("usage_facts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pricing_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("pricing_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    price_book_version: Mapped[int | None] = mapped_column(nullable=True)
    production_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("production_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_operations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reverses_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("ledger_entries.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(220))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
