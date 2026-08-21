from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import OutboxEvent
from app.models.orchestration import (
    StepStatus,
    WorkflowRouteDecision,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStep,
)
from app.schemas.workflows import DigitalHumanRenderRequest
from app.services.provider_registry import ProviderRegistry, get_provider_registry


WORKFLOW_STEPS = [
    ("validate", "检查素材"),
    ("avatar_render", "数字人渲染"),
    ("persist_result", "保存成片"),
]


async def create_workflow(
    session: AsyncSession,
    *,
    owner_id: str,
    tenant_id: str = "local-tenant",
    idempotency_key: str,
    payload: DigitalHumanRenderRequest,
    production_order_id: str | None = None,
    plan_version_id: str | None = None,
    provider_registry: ProviderRegistry | None = None,
    commit: bool = True,
) -> tuple[WorkflowRun, bool]:
    existing = await get_workflow_by_idempotency(session, owner_id, idempotency_key)
    if existing:
        return existing, False

    registry = provider_registry or get_provider_registry()
    route = await registry.decide_live(
        requested_provider=payload.provider,
        requested_execution=payload.execution_mode,
    )
    input_payload = payload.model_dump()
    input_payload.update(
        {
            "selected_provider": route.selected_provider,
            "selected_execution": route.selected_execution,
            "route_policy_version": route.policy_version,
        }
    )

    workflow = WorkflowRun(
        owner_id=owner_id,
        tenant_id=tenant_id,
        production_order_id=production_order_id,
        plan_version_id=plan_version_id,
        idempotency_key=idempotency_key,
        input_payload=input_payload,
        status=WorkflowStatus.queued,
        progress=0,
    )
    workflow.steps = [
        WorkflowStep(
            step_key=key,
            label=label,
            position=index,
            status=StepStatus.pending,
            capability="avatar.render" if key == "avatar_render" else None,
            expected_artifact="avatar_video" if key == "avatar_render" else None,
        )
        for index, (key, label) in enumerate(WORKFLOW_STEPS)
    ]
    workflow.route_decisions = [
        WorkflowRouteDecision(
            tenant_id=tenant_id,
            capability=route.capability,
            requested_provider=route.requested_provider,
            requested_execution=route.requested_execution,
            selected_provider=route.selected_provider,
            selected_execution=route.selected_execution,
            policy_version=route.policy_version,
            reason=route.reason,
            candidates=route.candidates,
        )
    ]
    try:
        session.add(workflow)
        await session.flush()
        session.add(
            OutboxEvent(
                tenant_id=tenant_id,
                aggregate_type="workflow",
                aggregate_id=workflow.id,
                topic="workflow.run.requested",
                payload={"workflow_id": workflow.id},
                dedupe_key=f"workflow:{workflow.id}:created",
            )
        )
        await session.flush()
        if not commit:
            return workflow, True
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_workflow_by_idempotency(session, owner_id, idempotency_key)
        if existing:
            return existing, False
        raise
    return await get_workflow(session, workflow.id), True


async def get_workflow(
    session: AsyncSession,
    workflow_id: str,
    owner_id: str | None = None,
) -> WorkflowRun:
    query = select(WorkflowRun).where(WorkflowRun.id == workflow_id)
    if owner_id is not None:
        query = query.where(WorkflowRun.owner_id == owner_id)
    result = await session.execute(
        query.options(
            selectinload(WorkflowRun.steps),
            selectinload(WorkflowRun.provider_jobs),
            selectinload(WorkflowRun.route_decisions),
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise LookupError(workflow_id)
    return workflow


async def retry_workflow(
    session: AsyncSession,
    workflow_id: str,
    owner_id: str,
) -> WorkflowRun:
    workflow = await get_workflow(session, workflow_id, owner_id)
    if workflow.status != WorkflowStatus.failed_retryable:
        raise ValueError("只有可重试状态的任务才能重新进入队列")

    workflow.status = WorkflowStatus.queued
    workflow.error_code = None
    workflow.error_message = None
    failed_positions = [step.position for step in workflow.steps if step.status == StepStatus.failed]
    retry_from = min(failed_positions) if failed_positions else 0
    for step in workflow.steps:
        if step.position >= retry_from:
            step.status = StepStatus.pending
            step.progress = 0
            step.error_message = None
            step.started_at = None
            step.finished_at = None
    completed_progress = [step.progress for step in workflow.steps if step.position < retry_from]
    workflow.progress = int(sum(completed_progress) / max(len(workflow.steps), 1))
    session.add(
        OutboxEvent(
            tenant_id=workflow.tenant_id or "local-tenant",
            aggregate_type="workflow",
            aggregate_id=workflow.id,
            topic="workflow.run.requested",
            payload={"workflow_id": workflow.id},
            dedupe_key=f"workflow:{workflow.id}:retry:{max((step.attempt for step in workflow.steps), default=0) + 1}",
        )
    )
    await session.commit()
    return await get_workflow(session, workflow.id, owner_id)


async def get_workflow_by_idempotency(
    session: AsyncSession,
    owner_id: str,
    idempotency_key: str,
) -> WorkflowRun | None:
    result = await session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.owner_id == owner_id, WorkflowRun.idempotency_key == idempotency_key)
        .options(
            selectinload(WorkflowRun.steps),
            selectinload(WorkflowRun.provider_jobs),
            selectinload(WorkflowRun.route_decisions),
        )
    )
    return result.scalar_one_or_none()


async def list_workflows(session: AsyncSession, owner_id: str, limit: int = 50) -> list[WorkflowRun]:
    result = await session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.owner_id == owner_id)
        .options(selectinload(WorkflowRun.steps), selectinload(WorkflowRun.route_decisions))
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().unique())
