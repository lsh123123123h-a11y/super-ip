import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
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


class ProductionOrderStatus(str, enum.Enum):
    draft = "draft"
    planning = "planning"
    awaiting_plan_approval = "awaiting_plan_approval"
    queued = "queued"
    running = "running"
    awaiting_decision = "awaiting_decision"
    evaluating = "evaluating"
    retry_wait = "retry_wait"
    paused = "paused"
    canceling = "canceling"
    canceled = "canceled"
    succeeded = "succeeded"
    failed_final = "failed_final"
    manual_intervention = "manual_intervention"


class AgentRunStatus(str, enum.Enum):
    planning = "planning"
    running = "running"
    awaiting_decision = "awaiting_decision"
    evaluating = "evaluating"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class PlanVersionStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    superseded = "superseded"
    completed = "completed"


class DecisionStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"
    canceled = "canceled"


class ArtifactVersionStatus(str, enum.Enum):
    candidate = "candidate"
    approved = "approved"
    returned = "returned"
    superseded = "superseded"


class AgentStepExecutionStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    waiting = "waiting"
    awaiting_decision = "awaiting_decision"
    evaluating = "evaluating"
    rework_requested = "rework_requested"
    retry_wait = "retry_wait"
    succeeded = "succeeded"
    failed_final = "failed_final"
    canceled = "canceled"
    superseded = "superseded"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    settings_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(64), default="digital_human_video")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IPProfileSnapshot(Base):
    __tablename__ = "ip_profile_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ip_profile_id", "profile_version", name="uq_ip_snapshot_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    ip_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    profile_version: Mapped[int] = mapped_column(Integer)
    snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionOrder(Base):
    __tablename__ = "production_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_order_tenant_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    content_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    ip_profile_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_profile_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200))
    intent_text: Mapped[str] = mapped_column(Text)
    intent_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    request_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    automation_mode: Mapped[str] = mapped_column(String(32), default="key_checkpoints")
    checkpoint_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    external_side_effect_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[ProductionOrderStatus] = mapped_column(
        Enum(ProductionOrderStatus), default=ProductionOrderStatus.planning, index=True
    )
    budget_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    max_auto_rework: Mapped[int] = mapped_column(Integer, default=2)
    auto_rework_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("production_order_id", "run_number", name="uq_agent_run_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    production_order_id: Mapped[str] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), index=True
    )
    run_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus), default=AgentRunStatus.planning, index=True
    )
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stop_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentOperation(Base):
    __tablename__ = "agent_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    production_order_id: Mapped[str] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    plan_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("plan_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operation_type: Mapped[str] = mapped_column(String(32), index=True)
    operation_key: Mapped[str] = mapped_column(String(100))
    implementation_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    executor_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    executor_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_execution_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    span_id: Mapped[str] = mapped_column(String(64))
    parent_span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    required_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    granted_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    budget_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    budget_reserved: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    budget_spent: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    usage_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_wakeup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fence_token: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("agent_run_id", "version", name="uq_plan_run_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    goal: Mapped[str] = mapped_column(Text)
    success_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    plan_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    budget_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    status: Mapped[PlanVersionStatus] = mapped_column(
        Enum(PlanVersionStatus), default=PlanVersionStatus.draft, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentStepExecution(Base):
    """Durable runtime state for one attempt of one Agent plan step.

    AgentEvent remains the audit timeline. This row is the authoritative state
    used for ownership, recovery, retries, evaluation and result application.
    """

    __tablename__ = "agent_step_executions"
    __table_args__ = (
        UniqueConstraint(
            "plan_version_id",
            "plan_step_key",
            "attempt",
            name="uq_agent_step_execution_attempt",
        ),
        UniqueConstraint("idempotency_key", name="uq_agent_step_execution_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    production_order_id: Mapped[str] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    plan_version_id: Mapped[str] = mapped_column(
        ForeignKey("plan_versions.id", ondelete="CASCADE"), index=True
    )
    parent_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_step_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan_step_key: Mapped[str] = mapped_column(String(100), index=True)
    capability_key: Mapped[str] = mapped_column(String(100), index=True)
    capability_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluator_key: Mapped[str] = mapped_column(String(100), index=True)
    evaluator_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_kind: Mapped[str] = mapped_column(String(32), default="inline")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(
        String(32), default=AgentStepExecutionStatus.pending.value, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(220))
    state_origin: Mapped[str] = mapped_column(String(32), default="native")
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    runtime_binding_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    external_execution_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_execution_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    output_artifact_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quality_evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("quality_evaluations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("decision_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fence_token: Mapped[int] = mapped_column(Integer, default=0)
    next_wakeup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentStepArtifactInput(Base):
    """Exact ArtifactVersion bound to a named input of a step attempt."""

    __tablename__ = "agent_step_artifact_inputs"
    __table_args__ = (
        UniqueConstraint(
            "step_execution_id",
            "input_name",
            name="uq_agent_step_artifact_input_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    step_execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_step_executions.id", ondelete="CASCADE"), index=True
    )
    input_name: Mapped[str] = mapped_column(String(100))
    artifact_key: Mapped[str] = mapped_column(String(100))
    artifact_version_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DecisionRequest(Base):
    __tablename__ = "decision_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    production_order_id: Mapped[str] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    plan_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("plan_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason_code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    recommended_option: Mapped[str | None] = mapped_column(String(64), nullable=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus), default=DecisionStatus.pending, index=True
    )
    resolved_option: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("production_order_id", "artifact_key", name="uq_order_artifact_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    production_order_id: Mapped[str] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), index=True
    )
    content_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    artifact_key: Mapped[str] = mapped_column(String(100))
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"), index=True)
    plan_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("plan_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[ArtifactVersionStatus] = mapped_column(
        Enum(ArtifactVersionStatus), default=ArtifactVersionStatus.candidate, index=True
    )
    content_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    lineage_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QualityEvaluation(Base):
    __tablename__ = "quality_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    artifact_version_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="CASCADE"), index=True
    )
    evaluator_key: Mapped[str] = mapped_column(String(100))
    evaluator_version: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    score_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    issue_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    production_order_id: Mapped[str] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    topic: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConsumedEvent(Base):
    """Durable consumer-side deduplication and takeover state."""

    __tablename__ = "consumed_events"
    __table_args__ = (
        UniqueConstraint("consumer_name", "event_id", name="uq_consumed_event_consumer"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_text)
    consumer_name: Mapped[str] = mapped_column(String(100), index=True)
    event_id: Mapped[str] = mapped_column(String(36), index=True)
    topic: Mapped[str] = mapped_column(String(100), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="processing", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    fence_token: Mapped[int] = mapped_column(Integer, default=1)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
