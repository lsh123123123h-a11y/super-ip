"""agent operation control plane

Revision ID: 20260821_0002
Revises: ac18980a9b69
Create Date: 2026-08-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_0002"
down_revision: Union[str, None] = "ac18980a9b69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("production_order_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("plan_version_id", sa.String(length=36), nullable=True),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("operation_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("executor_key", sa.String(length=100), nullable=True),
        sa.Column("external_execution_id", sa.String(length=200), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("span_id", sa.String(length=64), nullable=False),
        sa.Column("parent_span_id", sa.String(length=64), nullable=True),
        sa.Column("required_permissions", sa.JSON(), nullable=False),
        sa.Column("granted_permissions", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("budget_limit", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("budget_reserved", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("budget_spent", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("usage_payload", sa.JSON(), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_wakeup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_version_id"], ["plan_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["production_order_id"], ["production_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in (
        "agent_run_id",
        "executor_key",
        "external_execution_id",
        "lease_expires_at",
        "lease_owner",
        "next_wakeup_at",
        "operation_type",
        "plan_version_id",
        "production_order_id",
        "status",
        "tenant_id",
        "trace_id",
    ):
        op.create_index(f"ix_agent_operations_{column}", "agent_operations", [column], unique=False)


def downgrade() -> None:
    op.drop_table("agent_operations")
