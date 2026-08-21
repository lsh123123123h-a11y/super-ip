"""AI provider control plane

Revision ID: 20260821_0003
Revises: 20260821_0002
Create Date: 2026-08-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_0003"
down_revision: Union[str, None] = "20260821_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("adapter_type", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=32), nullable=False),
        sa.Column("capability_types", sa.JSON(), nullable=False),
        sa.Column("default_model", sa.String(length=200), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ai_provider_tenant_name"),
    )
    for column in (
        "adapter_type",
        "created_by_user_id",
        "enabled",
        "status",
        "tenant_id",
        "updated_by_user_id",
    ):
        op.create_index(
            f"ix_ai_provider_configs_{column}",
            "ai_provider_configs",
            [column],
            unique=False,
        )

    op.create_table(
        "ai_model_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider_config_id", sa.String(length=36), nullable=False),
        sa.Column("model_alias", sa.String(length=100), nullable=False),
        sa.Column("upstream_model", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["provider_config_id"], ["ai_provider_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "model_alias", name="uq_ai_model_tenant_alias"),
    )
    for column in ("enabled", "model_alias", "provider_config_id", "tenant_id"):
        op.create_index(
            f"ix_ai_model_bindings_{column}",
            "ai_model_bindings",
            [column],
            unique=False,
        )

    op.create_table(
        "ai_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider_config_id", sa.String(length=36), nullable=True),
        sa.Column("provider_source", sa.String(length=32), nullable=False),
        sa.Column("invocation_kind", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("model_alias", sa.String(length=100), nullable=False),
        sa.Column("requested_model", sa.String(length=200), nullable=False),
        sa.Column("response_model", sa.String(length=200), nullable=True),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("cost_currency", sa.String(length=16), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["provider_config_id"], ["ai_provider_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "created_at",
        "model_alias",
        "provider_config_id",
        "provider_source",
        "purpose",
        "success",
        "tenant_id",
    ):
        op.create_index(
            f"ix_ai_invocations_{column}",
            "ai_invocations",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("ai_invocations")
    op.drop_table("ai_model_bindings")
    op.drop_table("ai_provider_configs")
