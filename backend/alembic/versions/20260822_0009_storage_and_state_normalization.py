"""separate asset storage locators and normalize cancellation state

Revision ID: 20260822_0009
Revises: 20260822_0008
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0009"
down_revision: Union[str, None] = "20260822_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("storage_backend", sa.String(length=64), server_default="local", nullable=False),
    )
    op.add_column(
        "assets",
        sa.Column("locator_payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.create_unique_constraint("uq_assets_tenant_id", "assets", ["tenant_id", "id"])
    op.create_foreign_key(
        "fk_asset_refs_tenant_production_order_id",
        "asset_refs",
        "production_orders",
        ["tenant_id", "production_order_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_asset_refs_tenant_asset_id",
        "asset_refs",
        "assets",
        ["tenant_id", "asset_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_consent_snapshots_tenant_asset_id",
        "consent_snapshots",
        "assets",
        ["tenant_id", "asset_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.execute(
        "UPDATE workflow_runs SET status = 'canceled' "
        "WHERE status::text = 'cancelled'"
    )
    op.execute(
        "UPDATE workflow_runs SET status = 'retry_wait' "
        "WHERE status::text = 'failed_retryable'"
    )
    op.execute(
        "UPDATE production_orders SET status = 'retry_wait' "
        "WHERE status::text = 'failed_retryable'"
    )
    op.execute(
        "UPDATE agent_operations SET status = 'retry_wait' "
        "WHERE status = 'failed_retryable'"
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_consent_snapshots_tenant_asset_id", "consent_snapshots", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_asset_refs_tenant_asset_id", "asset_refs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_asset_refs_tenant_production_order_id", "asset_refs", type_="foreignkey"
    )
    op.drop_constraint("uq_assets_tenant_id", "assets", type_="unique")
    op.drop_column("assets", "locator_payload")
    op.drop_column("assets", "storage_backend")
