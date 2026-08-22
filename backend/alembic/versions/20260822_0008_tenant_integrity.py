"""enforce tenant-consistent aggregate ownership

Revision ID: 20260822_0008
Revises: 20260822_0007
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260822_0008"
down_revision: Union[str, None] = "20260822_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PARENTS = (
    "projects",
    "content_items",
    "ip_profile_snapshots",
    "production_orders",
    "agent_runs",
    "agent_operations",
    "plan_versions",
    "agent_step_executions",
    "decision_requests",
    "artifacts",
    "artifact_versions",
    "quality_evaluations",
    "workflow_runs",
    "ai_provider_configs",
    "ai_model_bindings",
)

# Only ownership edges whose child tenant is non-nullable (or whose child is
# intentionally tenantless-compatible) use composite foreign keys. Optional
# SET NULL references retain their scalar FK because SQL would otherwise also
# null the non-nullable tenant column.
OWNERSHIP_EDGES = (
    ("content_items", "project_id", "projects", "CASCADE"),
    ("production_orders", "project_id", "projects", "CASCADE"),
    ("agent_runs", "production_order_id", "production_orders", "CASCADE"),
    ("agent_operations", "production_order_id", "production_orders", "CASCADE"),
    ("agent_operations", "agent_run_id", "agent_runs", "CASCADE"),
    ("plan_versions", "agent_run_id", "agent_runs", "CASCADE"),
    ("agent_step_executions", "production_order_id", "production_orders", "CASCADE"),
    ("agent_step_executions", "agent_run_id", "agent_runs", "CASCADE"),
    ("agent_step_executions", "plan_version_id", "plan_versions", "CASCADE"),
    ("agent_step_artifact_inputs", "step_execution_id", "agent_step_executions", "CASCADE"),
    ("agent_step_artifact_inputs", "artifact_version_id", "artifact_versions", "RESTRICT"),
    ("decision_requests", "production_order_id", "production_orders", "CASCADE"),
    ("decision_requests", "agent_run_id", "agent_runs", "CASCADE"),
    ("artifacts", "production_order_id", "production_orders", "CASCADE"),
    ("artifact_versions", "artifact_id", "artifacts", "CASCADE"),
    ("quality_evaluations", "artifact_version_id", "artifact_versions", "CASCADE"),
    ("agent_events", "production_order_id", "production_orders", "CASCADE"),
    ("step_attempts", "workflow_id", "workflow_runs", "CASCADE"),
    ("provider_jobs", "workflow_id", "workflow_runs", "CASCADE"),
    ("workflow_route_decisions", "workflow_id", "workflow_runs", "CASCADE"),
    ("ai_model_bindings", "provider_config_id", "ai_provider_configs", "CASCADE"),
)


def _uq_name(table: str) -> str:
    return f"uq_{table}_tenant_id"


def _fk_name(child: str, column: str) -> str:
    return f"fk_{child}_tenant_{column}"


def upgrade() -> None:
    for table in PARENTS:
        op.create_unique_constraint(_uq_name(table), table, ["tenant_id", "id"])
    for child, column, parent, ondelete in OWNERSHIP_EDGES:
        op.create_foreign_key(
            _fk_name(child, column),
            child,
            parent,
            ["tenant_id", column],
            ["tenant_id", "id"],
            ondelete=ondelete,
        )


def downgrade() -> None:
    for child, column, _, _ in reversed(OWNERSHIP_EDGES):
        op.drop_constraint(_fk_name(child, column), child, type_="foreignkey")
    for table in reversed(PARENTS):
        op.drop_constraint(_uq_name(table), table, type_="unique")
