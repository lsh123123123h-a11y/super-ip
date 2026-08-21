from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.agent import OutboxEvent
from app.models.orchestration import (
    StepAttempt,
    StepStatus,
    WorkflowRun,
)
from app.services.provider_registry import ProviderRegistry


@dataclass(frozen=True, slots=True)
class WorkflowStepDefinition:
    key: str
    label: str
    capability: str | None = None
    expected_artifact: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    task_type: str
    capability: str
    version: str
    input_model: type[BaseModel]
    steps: tuple[WorkflowStepDefinition, ...]
    handler: "WorkflowHandler"


@dataclass(slots=True)
class WorkflowContext:
    session: AsyncSession
    workflow: WorkflowRun
    settings: Settings
    providers: ProviderRegistry


class WorkflowHandler(Protocol):
    async def run(self, context: WorkflowContext) -> None: ...

    async def fail(self, context: WorkflowContext, exc: Exception) -> None: ...

    async def cancel(self, context: WorkflowContext) -> None: ...


def step_by_key(workflow: WorkflowRun, key: str):
    return next(item for item in workflow.steps if item.step_key == key)


async def start_step_attempt(
    context: WorkflowContext,
    key: str,
    input_payload: dict[str, Any],
) -> StepAttempt:
    step = step_by_key(context.workflow, key)
    step.status = StepStatus.running
    step.progress = max(step.progress, 1)
    step.attempt += 1
    step.started_at = datetime.now(UTC)
    step.finished_at = None
    attempt = StepAttempt(
        tenant_id=context.workflow.tenant_id,
        workflow_id=context.workflow.id,
        workflow_step_id=step.id,
        attempt_number=step.attempt,
        status="running",
        input_payload=input_payload,
    )
    context.session.add(attempt)
    await context.session.flush()
    return attempt


async def finish_step_attempt(
    context: WorkflowContext,
    key: str,
    *,
    status: StepStatus,
    output_payload: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    step = step_by_key(context.workflow, key)
    step.status = status
    step.progress = 100 if status == StepStatus.succeeded else step.progress
    step.finished_at = datetime.now(UTC)
    if error:
        step.error_message = str(error)
    attempt = await context.session.scalar(
        select(StepAttempt)
        .where(
            StepAttempt.workflow_step_id == step.id,
            StepAttempt.attempt_number == step.attempt,
        )
        .order_by(StepAttempt.started_at.desc())
        .limit(1)
    )
    if attempt:
        attempt.status = status.value
        attempt.output_payload = output_payload
        attempt.error_code = error.__class__.__name__ if error else None
        attempt.error_message = str(error) if error else None
        attempt.finished_at = datetime.now(UTC)


def schedule_wakeup(
    context: WorkflowContext,
    *,
    wakeup_key: str,
    delay_seconds: float,
) -> None:
    available_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    context.workflow.next_wakeup_at = available_at
    context.session.add(
        OutboxEvent(
            tenant_id=context.workflow.tenant_id or "local-tenant",
            aggregate_type="workflow",
            aggregate_id=context.workflow.id,
            topic="workflow.run.requested",
            payload={"workflow_id": context.workflow.id},
            dedupe_key=f"workflow:{context.workflow.id}:wakeup:{wakeup_key}",
            available_at=available_at,
        )
    )


def notify_agent(context: WorkflowContext, *, suffix: str) -> None:
    workflow = context.workflow
    if not workflow.production_order_id:
        return
    context.session.add(
        OutboxEvent(
            tenant_id=workflow.tenant_id or "local-tenant",
            aggregate_type="production_order",
            aggregate_id=workflow.production_order_id,
            topic="agent.run.requested",
            payload={"production_order_id": workflow.production_order_id},
            dedupe_key=f"agent-observe:{workflow.id}:{suffix}",
        )
    )
