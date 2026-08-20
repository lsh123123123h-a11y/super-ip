from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.orchestration import StepStatus, WorkflowRun, WorkflowStatus, WorkflowStep
from app.schemas.workflows import DigitalHumanRenderRequest


WORKFLOW_STEPS = [
    ("validate", "检查素材"),
    ("avatar_render", "数字人渲染"),
    ("persist_result", "保存成片"),
]


async def create_workflow(
    session: AsyncSession,
    *,
    owner_id: str,
    idempotency_key: str,
    payload: DigitalHumanRenderRequest,
) -> tuple[WorkflowRun, bool]:
    existing = await get_workflow_by_idempotency(session, owner_id, idempotency_key)
    if existing:
        return existing, False

    workflow = WorkflowRun(
        owner_id=owner_id,
        idempotency_key=idempotency_key,
        input_payload=payload.model_dump(),
        status=WorkflowStatus.queued,
        progress=0,
    )
    workflow.steps = [
        WorkflowStep(step_key=key, label=label, position=index, status=StepStatus.pending)
        for index, (key, label) in enumerate(WORKFLOW_STEPS)
    ]
    session.add(workflow)
    try:
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
        query.options(selectinload(WorkflowRun.steps), selectinload(WorkflowRun.provider_jobs))
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
    workflow.progress = 0
    workflow.error_code = None
    workflow.error_message = None
    workflow.output_payload = None
    for step in workflow.steps:
        step.status = StepStatus.pending
        step.progress = 0
        step.error_message = None
        step.started_at = None
        step.finished_at = None
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
        .options(selectinload(WorkflowRun.steps), selectinload(WorkflowRun.provider_jobs))
    )
    return result.scalar_one_or_none()


async def list_workflows(session: AsyncSession, owner_id: str, limit: int = 50) -> list[WorkflowRun]:
    result = await session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.owner_id == owner_id)
        .options(selectinload(WorkflowRun.steps))
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().unique())
