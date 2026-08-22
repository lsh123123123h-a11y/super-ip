"""guard tenant consistency for nullable aggregate references

Revision ID: 20260822_0010
Revises: 20260822_0009
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260822_0010"
down_revision: Union[str, None] = "20260822_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OPTIONAL_REFERENCES = (
    ("production_orders", "content_item_id", "content_items"),
    ("production_orders", "ip_profile_snapshot_id", "ip_profile_snapshots"),
    ("agent_operations", "plan_version_id", "plan_versions"),
    ("agent_step_executions", "parent_execution_id", "agent_step_executions"),
    ("agent_step_executions", "output_artifact_version_id", "artifact_versions"),
    ("agent_step_executions", "quality_evaluation_id", "quality_evaluations"),
    ("agent_step_executions", "decision_request_id", "decision_requests"),
    ("decision_requests", "plan_version_id", "plan_versions"),
    ("artifacts", "content_item_id", "content_items"),
    ("artifact_versions", "plan_version_id", "plan_versions"),
    ("agent_events", "agent_run_id", "agent_runs"),
    ("workflow_runs", "production_order_id", "production_orders"),
    ("workflow_runs", "plan_version_id", "plan_versions"),
    ("ai_invocations", "provider_config_id", "ai_provider_configs"),
    ("ai_invocations", "model_binding_id", "ai_model_bindings"),
    ("assets", "project_id", "projects"),
)


def _trigger_name(table: str, column: str) -> str:
    return f"trg_{table}_{column}_tenant_guard"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_same_tenant_reference()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            reference_id text;
            parent_tenant text;
        BEGIN
            reference_id := to_jsonb(NEW) ->> TG_ARGV[1];
            IF reference_id IS NULL THEN
                RETURN NEW;
            END IF;
            EXECUTE format('SELECT tenant_id::text FROM %I WHERE id::text = $1', TG_ARGV[0])
                INTO parent_tenant
                USING reference_id;
            IF parent_tenant IS NOT NULL
               AND (NEW.tenant_id IS NULL OR NEW.tenant_id::text <> parent_tenant) THEN
                RAISE EXCEPTION 'cross-tenant reference %.% -> %',
                    TG_TABLE_NAME, TG_ARGV[1], TG_ARGV[0]
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table, column, parent in OPTIONAL_REFERENCES:
        op.execute(
            "DO $$ BEGIN "
            f"IF EXISTS (SELECT 1 FROM {table} child "
            f"JOIN {parent} parent ON parent.id = child.{column} "
            "WHERE child.tenant_id IS DISTINCT FROM parent.tenant_id) THEN "
            f"RAISE EXCEPTION 'existing cross-tenant reference {table}.{column}'; "
            "END IF; END $$"
        )
        op.execute(
            f"CREATE TRIGGER {_trigger_name(table, column)} "
            f"BEFORE INSERT OR UPDATE OF tenant_id, {column} ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            f"enforce_same_tenant_reference('{parent}', '{column}')"
        )


def downgrade() -> None:
    for table, column, _ in reversed(OPTIONAL_REFERENCES):
        op.execute(f"DROP TRIGGER {_trigger_name(table, column)} ON {table}")
    op.execute("DROP FUNCTION enforce_same_tenant_reference()")
