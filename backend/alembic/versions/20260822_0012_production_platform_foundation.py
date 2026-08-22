"""establish production platform foundation

Revision ID: 20260822_0012
Revises: 20260822_0011
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260822_0012"
down_revision: Union[str, None] = "20260822_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    "project.read",
    "project.write",
    "production_order.read",
    "production_order.write",
    "production_order.control",
    "asset.read",
    "asset.write",
    "provider.read",
    "provider.manage",
    "ai_provider.read",
    "ai_provider.manage",
    "usage.read",
    "billing.read",
    "billing.manage",
    "tenant.manage_members",
    "tenant.manage_settings",
)

ROLE_PERMISSIONS = {
    "owner": PERMISSIONS,
    "admin": PERMISSIONS,
    "member": (
        "project.read",
        "project.write",
        "production_order.read",
        "production_order.write",
        "production_order.control",
        "asset.read",
        "asset.write",
        "provider.read",
        "ai_provider.read",
        "usage.read",
    ),
    "viewer": (
        "project.read",
        "production_order.read",
        "asset.read",
        "provider.read",
        "ai_provider.read",
        "usage.read",
        "billing.read",
    ),
}

RLS_TABLES = (
    "memberships",
    "service_principals",
    "authentication_audit_events",
    "projects",
    "content_items",
    "ip_profiles",
    "campaigns",
    "content_projects",
    "ip_profile_snapshots",
    "production_orders",
    "agent_runs",
    "agent_operations",
    "plan_versions",
    "agent_step_executions",
    "agent_step_artifact_inputs",
    "decision_requests",
    "artifacts",
    "artifact_versions",
    "quality_evaluations",
    "agent_events",
    "outbox_events",
    "assets",
    "asset_refs",
    "consent_snapshots",
    "workflow_runs",
    "step_attempts",
    "provider_jobs",
    "workflow_route_decisions",
    "ai_provider_configs",
    "ai_model_bindings",
    "ai_invocations",
    "usage_facts",
    "price_books",
    "pricing_rules",
    "tenant_quotas",
    "usage_reservations",
    "ledger_entries",
)


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.String(length=36), primary_key=True, nullable=False)


def _tenant_column(nullable: bool = False) -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.String(length=36),
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=nullable,
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.execute("SELECT set_config('app.system_context', 'on', true)")

    op.create_table(
        "external_identities",
        _uuid_pk(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issuer", sa.String(500), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])

    op.create_table(
        "permissions",
        _uuid_pk(),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), server_default="", nullable=False),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)
    op.create_table(
        "roles",
        _uuid_pk(),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("key", name="uq_roles_key"),
    )
    op.create_index("ix_roles_key", "roles", ["key"], unique=True)
    op.create_table(
        "role_permissions",
        _uuid_pk(),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", sa.String(36), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"])

    permission_table = sa.table(
        "permissions", sa.column("id", sa.String), sa.column("code", sa.String), sa.column("description", sa.String)
    )
    op.bulk_insert(
        permission_table,
        [
            {"id": f"perm-{index:02d}", "code": code, "description": code}
            for index, code in enumerate(PERMISSIONS, start=1)
        ],
    )
    role_table = sa.table(
        "roles", sa.column("id", sa.String), sa.column("key", sa.String), sa.column("name", sa.String), sa.column("is_system", sa.Boolean)
    )
    role_names = {"owner": "Owner", "admin": "Admin", "member": "Member", "viewer": "Viewer"}
    op.bulk_insert(
        role_table,
        [
            {"id": f"role-{key}", "key": key, "name": role_names[key], "is_system": True}
            for key in ROLE_PERMISSIONS
        ],
    )
    role_permission_table = sa.table(
        "role_permissions",
        sa.column("id", sa.String),
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    permission_ids = {code: f"perm-{index:02d}" for index, code in enumerate(PERMISSIONS, start=1)}
    op.bulk_insert(
        role_permission_table,
        [
            {
                "id": f"rp-{role_key}-{index:02d}",
                "role_id": f"role-{role_key}",
                "permission_id": permission_ids[code],
            }
            for role_key, codes in ROLE_PERMISSIONS.items()
            for index, code in enumerate(codes, start=1)
        ],
    )

    op.add_column("memberships", sa.Column("role_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_memberships_role_id", "memberships", "roles", ["role_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_memberships_role_id", "memberships", ["role_id"])
    op.execute("UPDATE memberships SET role_id = 'role-' || role WHERE role IN ('owner','admin','member','viewer')")

    op.create_table(
        "service_principals",
        _uuid_pk(),
        _tenant_column(),
        sa.Column("client_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("secret_digest", sa.String(64), nullable=False),
        sa.Column("permissions", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "client_id", name="uq_service_principal_tenant_client"),
        sa.UniqueConstraint("client_id", name="uq_service_principals_client_id"),
    )
    for column in ("tenant_id", "client_id", "status", "created_by_user_id"):
        op.create_index(f"ix_service_principals_{column}", "service_principals", [column], unique=column == "client_id")

    op.create_table(
        "authentication_audit_events",
        _uuid_pk(),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("service_principal_id", sa.String(36), sa.ForeignKey("service_principals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("issuer", sa.String(500), nullable=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("auth_type", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("claim_digest", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("tenant_id", "user_id", "service_principal_id", "auth_type", "outcome", "request_id", "created_at"):
        op.create_index(f"ix_authentication_audit_events_{column}", "authentication_audit_events", [column])

    for table in ("ip_profiles", "campaigns", "content_projects"):
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(
        """
        INSERT INTO tenants (id, slug, name, status)
        SELECT 'local-tenant', 'local-tenant', 'Legacy local workspace', 'active'
        WHERE (
          EXISTS (SELECT 1 FROM ip_profiles WHERE tenant_id IS NULL)
          OR EXISTS (SELECT 1 FROM campaigns WHERE tenant_id IS NULL)
          OR EXISTS (SELECT 1 FROM content_projects WHERE tenant_id IS NULL)
        ) AND NOT EXISTS (SELECT 1 FROM tenants WHERE id = 'local-tenant')
        """
    )
    for table in ("ip_profiles", "campaigns", "content_projects"):
        op.execute(
            f"""
            UPDATE {table} legacy
            SET tenant_id = COALESCE(
                (SELECT membership.tenant_id
                 FROM memberships membership
                 JOIN users identity_user ON identity_user.id = membership.user_id
                 WHERE membership.user_id = legacy.owner_id
                    OR identity_user.external_subject = legacy.owner_id
                 ORDER BY membership.created_at LIMIT 1),
                'local-tenant'
            )
            WHERE tenant_id IS NULL
            """
        )
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_tenant_id", table, "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.create_unique_constraint(f"uq_{table}_tenant_id", table, ["tenant_id", "id"])

    for name, type_ in (
        ("storage_backend", sa.String(64)),
        ("storage_key", sa.String(500)),
        ("media_type", sa.String(100)),
        ("size_bytes", sa.Integer()),
    ):
        op.add_column("artifact_versions", sa.Column(name, type_, nullable=True))

    op.create_table(
        "usage_facts",
        _uuid_pk(),
        _tenant_column(),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(200), nullable=False),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("agent_operations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_run_id", sa.String(36), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step_execution_id", sa.String(36), sa.ForeignKey("agent_step_executions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("capability_key", sa.String(100), nullable=True),
        sa.Column("provider_id", sa.String(100), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("dedupe_key", sa.String(220), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_usage_fact_tenant_dedupe"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_usage_facts_tenant_id"),
    )
    op.create_table(
        "price_books",
        _uuid_pk(),
        _tenant_column(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(16), server_default="internal_credit", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "version", name="uq_price_book_tenant_version"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_price_books_tenant_id"),
    )
    op.create_table(
        "pricing_rules",
        _uuid_pk(),
        _tenant_column(),
        sa.Column("price_book_id", sa.String(36), sa.ForeignKey("price_books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("provider_id", sa.String(100), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("capability_key", sa.String(100), nullable=True),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("unit_size", sa.Numeric(24, 8), server_default="1", nullable=False),
        sa.Column("unit_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("price_book_id", "metric", "provider_id", "model", "capability_key", name="uq_pricing_rule_dimensions"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_pricing_rules_tenant_id"),
    )
    op.create_table(
        "tenant_quotas",
        _uuid_pk(),
        _tenant_column(),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hard_limit", sa.Numeric(24, 8), nullable=True),
        sa.Column("soft_limit", sa.Numeric(24, 8), nullable=True),
        sa.Column("used_quantity", sa.Numeric(24, 8), server_default="0", nullable=False),
        sa.Column("reserved_quantity", sa.Numeric(24, 8), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "metric", "period", "period_start", name="uq_tenant_quota_period"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tenant_quotas_tenant_id"),
    )
    op.create_table(
        "usage_reservations",
        _uuid_pk(),
        _tenant_column(),
        sa.Column("quota_id", sa.String(36), sa.ForeignKey("tenant_quotas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("production_order_id", sa.String(36), sa.ForeignKey("production_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("agent_operations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(24, 8), server_default="0", nullable=False),
        sa.Column("currency", sa.String(16), server_default="internal_credit", nullable=False),
        sa.Column("pricing_rule_id", sa.String(36), sa.ForeignKey("pricing_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("price_book_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), server_default="reserved", nullable=False),
        sa.Column("idempotency_key", sa.String(220), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_reservation_tenant_key"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_usage_reservations_tenant_id"),
    )
    op.create_table(
        "ledger_entries",
        _uuid_pk(),
        _tenant_column(),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), server_default="0", nullable=False),
        sa.Column("currency", sa.String(16), server_default="internal_credit", nullable=False),
        sa.Column("metric", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=True),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(200), nullable=False),
        sa.Column("usage_fact_id", sa.String(36), sa.ForeignKey("usage_facts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pricing_rule_id", sa.String(36), sa.ForeignKey("pricing_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("price_book_version", sa.Integer(), nullable=True),
        sa.Column("production_order_id", sa.String(36), sa.ForeignKey("production_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("agent_operations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_run_id", sa.String(36), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reverses_entry_id", sa.String(36), sa.ForeignKey("ledger_entries.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("idempotency_key", sa.String(220), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ledger_tenant_key"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ledger_entries_tenant_id"),
    )

    INDEXES = {
        "usage_facts": ("tenant_id", "source_type", "source_id", "operation_id", "workflow_run_id", "step_execution_id", "capability_key", "provider_id", "model", "metric", "occurred_at"),
        "price_books": ("tenant_id", "version", "effective_from", "status", "created_by_user_id"),
        "pricing_rules": ("tenant_id", "price_book_id", "metric"),
        "tenant_quotas": ("tenant_id", "metric", "period_start", "period_end"),
        "usage_reservations": ("tenant_id", "quota_id", "production_order_id", "operation_id", "pricing_rule_id", "metric", "status"),
        "ledger_entries": ("tenant_id", "entry_type", "metric", "source_type", "source_id", "usage_fact_id", "pricing_rule_id", "production_order_id", "operation_id", "workflow_run_id", "reverses_entry_id", "created_by_user_id", "occurred_at"),
    }
    for table, columns in INDEXES.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])

    for name, table, columns in (
        (
            "ix_agent_operations_claim",
            "agent_operations",
            ("status", "next_wakeup_at", "lease_expires_at"),
        ),
        (
            "ix_agent_step_executions_claim",
            "agent_step_executions",
            ("status", "next_wakeup_at", "lease_expires_at"),
        ),
        (
            "ix_workflow_runs_claim",
            "workflow_runs",
            ("status", "next_wakeup_at", "lease_expires_at"),
        ),
        (
            "ix_outbox_events_publish_claim",
            "outbox_events",
            ("published_at", "dead_lettered_at", "available_at", "created_at"),
        ),
        (
            "ix_consumed_events_recovery",
            "consumed_events",
            ("status", "dead_lettered_at", "next_attempt_at", "lease_expires_at"),
        ),
        (
            "ix_tenant_quotas_lookup",
            "tenant_quotas",
            ("tenant_id", "metric", "period_start", "period_end"),
        ),
        (
            "ix_price_books_effective",
            "price_books",
            ("tenant_id", "status", "effective_from", "version"),
        ),
        (
            "ix_pricing_rules_lookup",
            "pricing_rules",
            ("tenant_id", "metric", "provider_id", "model", "capability_key"),
        ),
        (
            "ix_usage_facts_tenant_occurred",
            "usage_facts",
            ("tenant_id", "occurred_at"),
        ),
        (
            "ix_ledger_entries_tenant_occurred",
            "ledger_entries",
            ("tenant_id", "occurred_at"),
        ),
    ):
        op.create_index(name, table, list(columns))

    for table, parent_column, parent in (
        ("pricing_rules", "price_book_id", "price_books"),
        ("usage_reservations", "quota_id", "tenant_quotas"),
        ("usage_reservations", "pricing_rule_id", "pricing_rules"),
        ("ledger_entries", "usage_fact_id", "usage_facts"),
        ("ledger_entries", "pricing_rule_id", "pricing_rules"),
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_{parent_column}_tenant_guard
            BEFORE INSERT OR UPDATE OF tenant_id, {parent_column} ON {table}
            FOR EACH ROW EXECUTE FUNCTION enforce_same_tenant_reference('{parent}', '{parent_column}')
            """
        )

    op.execute(
        """
        CREATE FUNCTION reject_immutable_fact_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in ("usage_facts", "price_books", "pricing_rules", "ledger_entries", "authentication_audit_events"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_fact_mutation()"
        )

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (
                tenant_id::text = current_setting('app.tenant_id', true)
                OR current_setting('app.system_context', true) = 'on'
            )
            WITH CHECK (
                tenant_id::text = current_setting('app.tenant_id', true)
                OR current_setting('app.system_context', true) = 'on'
            )
            """
        )


def downgrade() -> None:
    op.execute("SELECT set_config('app.system_context', 'on', true)")

    for name, table in (
        ("ix_consumed_events_recovery", "consumed_events"),
        ("ix_outbox_events_publish_claim", "outbox_events"),
        ("ix_workflow_runs_claim", "workflow_runs"),
        ("ix_agent_step_executions_claim", "agent_step_executions"),
        ("ix_agent_operations_claim", "agent_operations"),
    ):
        op.drop_index(name, table_name=table)
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in ("authentication_audit_events", "ledger_entries", "pricing_rules", "price_books", "usage_facts"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION reject_immutable_fact_mutation()")
    for table, parent_column in (
        ("ledger_entries", "pricing_rule_id"),
        ("ledger_entries", "usage_fact_id"),
        ("usage_reservations", "pricing_rule_id"),
        ("usage_reservations", "quota_id"),
        ("pricing_rules", "price_book_id"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_{parent_column}_tenant_guard ON {table}")

    for table in (
        "ledger_entries",
        "usage_reservations",
        "tenant_quotas",
        "pricing_rules",
        "price_books",
        "usage_facts",
    ):
        op.drop_table(table)
    for column in ("size_bytes", "media_type", "storage_key", "storage_backend"):
        op.drop_column("artifact_versions", column)
    for table in ("content_projects", "campaigns", "ip_profiles"):
        op.drop_constraint(f"uq_{table}_tenant_id", table, type_="unique")
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
    op.drop_table("authentication_audit_events")
    op.drop_table("service_principals")
    op.drop_index("ix_memberships_role_id", table_name="memberships")
    op.drop_constraint("fk_memberships_role_id", "memberships", type_="foreignkey")
    op.drop_column("memberships", "role_id")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_table("external_identities")
