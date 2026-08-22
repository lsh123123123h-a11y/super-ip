"""bound evaluator retries and recover consumed runtime events

Revision ID: 20260822_0011
Revises: 20260822_0010
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0011"
down_revision: Union[str, None] = "20260822_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "decision_requests",
        sa.Column("scope", sa.String(length=16), server_default="order", nullable=False),
    )
    op.execute(
        "UPDATE decision_requests SET scope = 'plan' WHERE reason_code = 'PLAN_REVIEW'"
    )
    op.execute(
        "UPDATE decision_requests SET scope = 'step' "
        "WHERE id IN (SELECT decision_request_id FROM agent_step_executions "
        "WHERE decision_request_id IS NOT NULL)"
    )
    op.create_index("ix_decision_requests_scope", "decision_requests", ["scope"])
    op.add_column(
        "agent_step_executions",
        sa.Column("evaluation_attempt", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_step_executions",
        sa.Column(
            "evaluation_max_attempts",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.add_column(
        "consumed_events",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "consumed_events",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_consumed_events_next_attempt_at",
        "consumed_events",
        ["next_attempt_at"],
    )
    op.create_index(
        "ix_consumed_events_dead_lettered_at",
        "consumed_events",
        ["dead_lettered_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_consumed_events_dead_lettered_at", table_name="consumed_events")
    op.drop_index("ix_consumed_events_next_attempt_at", table_name="consumed_events")
    op.drop_column("consumed_events", "dead_lettered_at")
    op.drop_column("consumed_events", "next_attempt_at")
    op.drop_column("agent_step_executions", "evaluation_max_attempts")
    op.drop_column("agent_step_executions", "evaluation_attempt")
    op.drop_index("ix_decision_requests_scope", table_name="decision_requests")
    op.drop_column("decision_requests", "scope")
