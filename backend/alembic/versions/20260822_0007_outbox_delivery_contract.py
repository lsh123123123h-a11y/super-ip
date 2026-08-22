"""version outbox envelopes and persist consumer deduplication

Revision ID: 20260822_0007
Revises: 20260822_0006
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0007"
down_revision: Union[str, None] = "20260822_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "outbox_events",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_dead_lettered_at",
        "outbox_events",
        ["dead_lettered_at"],
    )
    op.create_table(
        "consumed_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("consumer_name", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="processing", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("fence_token", sa.Integer(), server_default="1", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consumer_name", "event_id", name="uq_consumed_event_consumer"),
    )
    for column in ("consumer_name", "event_id", "lease_expires_at", "status", "topic"):
        op.create_index(
            f"ix_consumed_events_{column}",
            "consumed_events",
            [column],
        )


def downgrade() -> None:
    op.drop_table("consumed_events")
    op.drop_index("ix_outbox_events_dead_lettered_at", table_name="outbox_events")
    op.drop_column("outbox_events", "dead_lettered_at")
    op.drop_column("outbox_events", "schema_version")
