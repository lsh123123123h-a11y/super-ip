import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WorkflowStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    waiting_provider = "waiting_provider"
    retry_wait = "retry_wait"
    paused = "paused"
    canceling = "canceling"
    canceled = "canceled"
    succeeded = "succeeded"
    failed_final = "failed_final"
    manual_intervention = "manual_intervention"


class StepStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


def uuid_text() -> str:
    return str(uuid.uuid4())


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key", name="uq_workflow_owner_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    owner_id: Mapped[str] = mapped_column(String(128), default="local-user", index=True)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    production_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    plan_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("plan_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(64), default="digital_human.render")
    workflow_definition_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capability: Mapped[str] = mapped_column(String(100), default="avatar.render", index=True)
    status: Mapped[WorkflowStatus] = mapped_column(Enum(WorkflowStatus), default=WorkflowStatus.queued, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fence_token: Mapped[int] = mapped_column(Integer, default=0)
    next_wakeup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.position",
        lazy="selectin",
    )
    provider_jobs: Mapped[list["ProviderJob"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    route_decisions: Mapped[list["WorkflowRouteDecision"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowRouteDecision.created_at",
        lazy="selectin",
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("workflow_id", "step_key", name="uq_workflow_step_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    step_key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer)
    capability: Mapped[str | None] = mapped_column(String(100), nullable=True)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_artifact: Mapped[str | None] = mapped_column(String(100), nullable=True)
    checkpoint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.pending)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped[WorkflowRun] = relationship(back_populates="steps")


class StepAttempt(Base):
    __tablename__ = "step_attempts"
    __table_args__ = (UniqueConstraint("workflow_step_id", "attempt_number", name="uq_step_attempt_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    workflow_step_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_steps.id", ondelete="CASCADE"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderJob(Base):
    __tablename__ = "provider_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    step_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("step_attempts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    capability: Mapped[str] = mapped_column(String(100), default="avatar.render", index=True)
    provider: Mapped[str] = mapped_column(String(64), default="duix")
    provider_adapter_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    external_job_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(64), default="submitted")
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workflow: Mapped[WorkflowRun] = relationship(back_populates="provider_jobs")


class WorkflowRouteDecision(Base):
    __tablename__ = "workflow_route_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability: Mapped[str] = mapped_column(String(64), default="avatar.render")
    requested_provider: Mapped[str] = mapped_column(String(64), default="auto")
    requested_execution: Mapped[str] = mapped_column(String(64), default="auto")
    selected_provider: Mapped[str] = mapped_column(String(64))
    selected_adapter_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_execution: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped[WorkflowRun] = relationship(back_populates="route_decisions")
