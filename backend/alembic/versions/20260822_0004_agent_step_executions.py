"""durable agent step executions

Revision ID: 20260822_0004
Revises: 20260821_0003
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0004"
down_revision: Union[str, None] = "20260821_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_step_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("production_order_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("plan_version_id", sa.String(length=36), nullable=False),
        sa.Column("parent_execution_id", sa.String(length=36), nullable=True),
        sa.Column("plan_step_key", sa.String(length=100), nullable=False),
        sa.Column("capability_key", sa.String(length=100), nullable=False),
        sa.Column("capability_version", sa.String(length=64), nullable=True),
        sa.Column("evaluator_key", sa.String(length=100), nullable=False),
        sa.Column("evaluator_version", sa.String(length=64), nullable=True),
        sa.Column("execution_kind", sa.String(length=32), server_default="inline", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("state_origin", sa.String(length=32), server_default="native", nullable=False),
        sa.Column("input_payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("runtime_binding_payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("external_execution_type", sa.String(length=32), nullable=True),
        sa.Column("external_execution_id", sa.String(length=200), nullable=True),
        sa.Column("output_artifact_version_id", sa.String(length=36), nullable=True),
        sa.Column("quality_evaluation_id", sa.String(length=36), nullable=True),
        sa.Column("decision_request_id", sa.String(length=36), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fence_token", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_wakeup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_request_id"], ["decision_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["output_artifact_version_id"], ["artifact_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_execution_id"], ["agent_step_executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_version_id"], ["plan_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["production_order_id"], ["production_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quality_evaluation_id"], ["quality_evaluations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_version_id",
            "plan_step_key",
            "attempt",
            name="uq_agent_step_execution_attempt",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_agent_step_execution_idempotency"),
    )
    for column in (
        "agent_run_id",
        "capability_key",
        "decision_request_id",
        "evaluator_key",
        "external_execution_id",
        "lease_expires_at",
        "lease_owner",
        "next_wakeup_at",
        "output_artifact_version_id",
        "parent_execution_id",
        "plan_step_key",
        "plan_version_id",
        "production_order_id",
        "quality_evaluation_id",
        "status",
        "tenant_id",
    ):
        op.create_index(
            f"ix_agent_step_executions_{column}",
            "agent_step_executions",
            [column],
            unique=False,
        )

    op.create_table(
        "agent_step_artifact_inputs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("step_execution_id", sa.String(length=36), nullable=False),
        sa.Column("input_name", sa.String(length=100), nullable=False),
        sa.Column("artifact_key", sa.String(length=100), nullable=False),
        sa.Column("artifact_version_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["artifact_version_id"], ["artifact_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["step_execution_id"], ["agent_step_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "step_execution_id",
            "input_name",
            name="uq_agent_step_artifact_input_name",
        ),
    )
    op.create_index(
        "ix_agent_step_artifact_inputs_artifact_version_id",
        "agent_step_artifact_inputs",
        ["artifact_version_id"],
    )
    op.create_index(
        "ix_agent_step_artifact_inputs_step_execution_id",
        "agent_step_artifact_inputs",
        ["step_execution_id"],
    )
    op.create_index(
        "ix_agent_step_artifact_inputs_tenant_id",
        "agent_step_artifact_inputs",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_table("agent_step_artifact_inputs")
    op.drop_table("agent_step_executions")
