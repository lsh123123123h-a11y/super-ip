"""pin runtime implementations and add fencing heartbeats

Revision ID: 20260822_0005
Revises: 20260822_0004
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0005"
down_revision: Union[str, None] = "20260822_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_operations",
        sa.Column("implementation_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agent_operations",
        sa.Column("executor_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agent_operations",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_operations",
        sa.Column("fence_token", sa.Integer(), server_default="0", nullable=False),
    )

    op.add_column(
        "workflow_runs",
        sa.Column("workflow_definition_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("fence_token", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "provider_jobs",
        sa.Column("provider_adapter_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "workflow_route_decisions",
        sa.Column("selected_adapter_version", sa.String(length=64), nullable=True),
    )

    op.execute(
        "UPDATE agent_operations SET implementation_version = '1.0.0' "
        "WHERE operation_type = 'planning' AND implementation_version IS NULL"
    )
    op.execute(
        "UPDATE agent_operations SET implementation_version = '1.0.0' "
        "WHERE operation_type = 'executor' AND implementation_version IS NULL"
    )
    op.execute(
        "UPDATE workflow_runs SET workflow_definition_version = '1.0.0' "
        "WHERE workflow_definition_version IS NULL"
    )
    op.execute(
        "UPDATE provider_jobs SET provider_adapter_version = '1.0.0' "
        "WHERE provider_adapter_version IS NULL"
    )
    op.execute(
        "UPDATE workflow_route_decisions SET selected_adapter_version = '1.0.0' "
        "WHERE selected_adapter_version IS NULL"
    )


def downgrade() -> None:
    op.drop_column("workflow_route_decisions", "selected_adapter_version")
    op.drop_column("provider_jobs", "provider_adapter_version")
    op.drop_column("workflow_runs", "fence_token")
    op.drop_column("workflow_runs", "heartbeat_at")
    op.drop_column("workflow_runs", "workflow_definition_version")
    op.drop_column("agent_operations", "fence_token")
    op.drop_column("agent_operations", "heartbeat_at")
    op.drop_column("agent_operations", "executor_version")
    op.drop_column("agent_operations", "implementation_version")
