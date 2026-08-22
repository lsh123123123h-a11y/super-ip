"""record exact AI routing and adapter facts

Revision ID: 20260822_0006
Revises: 20260822_0005
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0006"
down_revision: Union[str, None] = "20260822_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_invocations",
        sa.Column("model_binding_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "ai_invocations",
        sa.Column("provider_config_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ai_invocations",
        sa.Column("adapter_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_invocations",
        sa.Column("adapter_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_invocations",
        sa.Column(
            "routing_policy",
            sa.String(length=64),
            server_default="model_alias",
            nullable=False,
        ),
    )
    op.add_column(
        "ai_invocations",
        sa.Column(
            "routing_policy_version",
            sa.String(length=64),
            server_default="1.0.0",
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_ai_invocations_model_binding_id",
        "ai_invocations",
        "ai_model_bindings",
        ["model_binding_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ai_invocations_model_binding_id",
        "ai_invocations",
        ["model_binding_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_invocations_model_binding_id", table_name="ai_invocations")
    op.drop_constraint(
        "fk_ai_invocations_model_binding_id",
        "ai_invocations",
        type_="foreignkey",
    )
    op.drop_column("ai_invocations", "routing_policy_version")
    op.drop_column("ai_invocations", "routing_policy")
    op.drop_column("ai_invocations", "adapter_version")
    op.drop_column("ai_invocations", "adapter_type")
    op.drop_column("ai_invocations", "provider_config_version")
    op.drop_column("ai_invocations", "model_binding_id")
