from typing import Any

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
from app.services.provider_registry import ProviderRegistry, get_provider_registry
from app.workflows.registry import WorkflowRegistry, get_workflow_registry
from app.services.workflow_transitions import transition_workflow

async def create_capability_workflow(
    session: AsyncSession,
    *,
    owner_id: str,
    tenant_id: str = "local-tenant",
    idempotency_key: str,
    task_type: str,
    capability: str,
    input_payload: dict[str, Any],
    requested_provider: str = "auto",
    requested_execution: str = "auto",
    production_order_id: str | None = None,
    plan_version_id: str | None = None,
    provider_registry: ProviderRegistry | None = None,
    workflow_registry: WorkflowRegistry | None = None,
    commit: bool = True,
) -> tuple[WorkflowRun, bool]:
    definitions = workflow_registry or get_workflow_registry()
    existing = await get_workflow_by_idempotency(
        session,
        owner_id,
        idempotency_key,
    )
    definition = definitions.resolve(
        task_type,
        existing.workflow_definition_version if existing else None,
    )
    if definition is None:
        raise ValueError(f"Workflow 类型尚未注册：{task_type}")
    if definition.capability != capability:
        raise ValueError(
            f"Workflow {task_type} 不承载能力 {capability}"
        )
    validated_input = definition.input_model.model_validate(input_payload)
    normalized_input = validated_input.model_dump(mode="json")
    if existing:
        existing_input = definition.input_model.model_validate(
            existing.input_payload
        ).model_dump(mode="json")
        if (
            existing.task_type != task_type
            or existing.capability != capability
            or existing.production_order_id != production_order_id
            or existing.plan_version_id != plan_version_id
            or existing_input != normalized_input
        ):
            raise ValueError(
                "同一 Idempotency-Key 不能提交不同的 Workflow 请求"
            )
        return existing, False

    providers = provider_registry or get_provider_registry()
    route = await providers.decide_live(
        capability=capability,
        requested_provider=requested_provider,
        requested_execution=requested_execution,
    )
    stored_input = dict(normalized_input)
    stored_input.update(
        {
            "selected_provider": route.selected_provider,
            "selected_adapter_version": route.selected_adapter_version,
            "selected_execution": route.selected_execution,
            "route_policy_version": route.policy_version,
        }
    )

    workflow = WorkflowRun(
        owner_id=owner_id,
        tenant_id=tenant_id,
        production_order_id=production_order_id,
        plan_version_id=plan_version_id,
        task_type=task_type,
        workflow_definition_version=definition.version,
        capability=capability,
        idempotency_key=idempotency_key,
        input_payload=stored_input,
        status=WorkflowStatus.queued,
        progress=0,
    )
    workflow.steps = [
        WorkflowStep(
            step_key=step.key,
            label=step.label,
            position=index,
            status=StepStatus.pending,
            capability=step.capability,
            depends_on=list(step.depends_on),
            expected_artifact=step.expected_artifact,
        )
        for index, step in enumerate(definition.steps)
    ]
    workflow.route_decisions = [
        WorkflowRouteDecision(
            tenant_id=tenant_id,
            capability=route.capability,
            requested_provider=route.requested_provider,
            requested_execution=route.requested_execution,
            selected_provider=route.selected_provider,
            selected_adapter_version=route.selected_adapter_version,
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
    tenant_id: str | None = None,
) -> WorkflowRun:
    query = select(WorkflowRun).where(WorkflowRun.id == workflow_id)
    if owner_id is not None:
        query = query.where(WorkflowRun.owner_id == owner_id)
    if tenant_id is not None:
        query = query.where(WorkflowRun.tenant_id == tenant_id)
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
    tenant_id: str | None = None,
) -> WorkflowRun:
    workflow = await get_workflow(session, workflow_id, owner_id, tenant_id)
    if workflow.status != WorkflowStatus.retry_wait:
        raise ValueError("只有可重试状态的任务才能重新进入队列")

    transition_workflow(workflow, WorkflowStatus.queued)
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
    return await get_workflow(session, workflow.id, owner_id, tenant_id)


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


async def list_workflows(
    session: AsyncSession,
    owner_id: str,
    limit: int = 50,
    tenant_id: str | None = None,
) -> list[WorkflowRun]:
    query = select(WorkflowRun).where(WorkflowRun.owner_id == owner_id)
    if tenant_id is not None:
        query = query.where(WorkflowRun.tenant_id == tenant_id)
    result = await session.execute(
        query
        .options(selectinload(WorkflowRun.steps), selectinload(WorkflowRun.route_decisions))
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().unique())
