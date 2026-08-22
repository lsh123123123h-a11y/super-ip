from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import AgentPlanSpec, PlanStepSpec
from app.capabilities.registry import get_capability_registry
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.evaluators.registry import get_evaluator_registry
from app.integrations.managed_brain import resolve_brain_binding_snapshot
from app.integrations.new_api_brain import BrainConfigurationError
from app.models.agent import (
    AgentEvent,
    AgentRun,
    AgentRunStatus,
    AgentStepArtifactInput,
    AgentStepExecution,
    AgentStepExecutionStatus,
    PlanVersion,
    PlanVersionStatus,
    ProductionOrder,
    ProductionOrderStatus,
)


CLAIMABLE_ORDER_STATUSES = {
    ProductionOrderStatus.queued,
    ProductionOrderStatus.running,
    ProductionOrderStatus.retry_wait,
    ProductionOrderStatus.evaluating,
}
RECLAIMABLE_STEP_STATUSES = {
    AgentStepExecutionStatus.pending.value,
    AgentStepExecutionStatus.running.value,
    AgentStepExecutionStatus.evaluating.value,
    AgentStepExecutionStatus.waiting.value,
    AgentStepExecutionStatus.retry_wait.value,
}
TERMINAL_STEP_STATUSES = {
    AgentStepExecutionStatus.succeeded.value,
    AgentStepExecutionStatus.failed_final.value,
    AgentStepExecutionStatus.canceled.value,
    AgentStepExecutionStatus.superseded.value,
}


@dataclass(frozen=True, slots=True)
class AgentStepClaim:
    execution_id: str
    production_order_id: str
    agent_run_id: str
    plan_version_id: str
    plan_step_key: str
    attempt: int
    worker_id: str
    fence_token: int


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _execution_identity(plan_id: str, step_key: str, attempt: int) -> str:
    return f"agent-step:{plan_id}:{step_key}:attempt:{attempt}"


async def materialize_plan_step_executions(
    session: AsyncSession,
    *,
    order: ProductionOrder,
    run: AgentRun,
    plan: PlanVersion,
    plan_spec: AgentPlanSpec,
    state_origin: str = "native",
) -> list[AgentStepExecution]:
    settings = get_settings()
    existing = list(
        (
            await session.scalars(
                select(AgentStepExecution).where(
                    AgentStepExecution.plan_version_id == plan.id,
                )
            )
        ).all()
    )
    existing_attempts = {
        (item.plan_step_key, item.attempt): item for item in existing
    }
    capabilities = get_capability_registry()
    evaluators = get_evaluator_registry()
    for step in plan_spec.steps:
        if (step.key, 1) in existing_attempts:
            continue
        capability = capabilities.resolve(step.capability, step.capability_version)
        evaluator = evaluators.resolve(step.evaluator, step.evaluator_version)
        resolved_capability_version = (
            step.capability_version
            or (capability.definition.version if capability is not None else None)
        )
        resolved_evaluator_version = (
            step.evaluator_version
            or (evaluator.definition.version if evaluator is not None else None)
        )
        runtime_binding_payload: dict[str, Any] = {}
        model_alias = capability.metadata.get("model_alias") if capability else None
        if model_alias:
            try:
                brain_binding = await resolve_brain_binding_snapshot(
                    order.tenant_id,
                    str(model_alias),
                )
            except BrainConfigurationError as exc:
                brain_binding = {
                    "model_alias": str(model_alias),
                    "resolution_error": str(exc),
                }
            runtime_binding_payload["brain_binding"] = brain_binding
        if capability and capability.external_executor_key:
            from app.executors.registry import get_executor_registry

            executor_definition = get_executor_registry().definition(
                capability.external_executor_key
            )
            if executor_definition is not None:
                runtime_binding_payload["external_executor"] = {
                    "key": executor_definition.key,
                    "version": executor_definition.version,
                }
        execution = AgentStepExecution(
            tenant_id=order.tenant_id,
            production_order_id=order.id,
            agent_run_id=run.id,
            plan_version_id=plan.id,
            plan_step_key=step.key,
            capability_key=step.capability,
            capability_version=resolved_capability_version,
            evaluator_key=step.evaluator,
            evaluator_version=resolved_evaluator_version,
            execution_kind=(
                capability.definition.execution_kind.value
                if capability is not None
                else "unavailable"
            ),
            attempt=1,
            max_attempts=step.max_attempts,
            evaluation_max_attempts=settings.evaluator_max_attempts,
            status=AgentStepExecutionStatus.pending.value,
            idempotency_key=_execution_identity(plan.id, step.key, 1),
            state_origin=(
                state_origin
                if step.capability_version and step.evaluator_version
                else "legacy_unpinned"
            ),
            runtime_binding_payload=runtime_binding_payload,
        )
        session.add(execution)
        existing.append(execution)
    await session.flush()
    return existing


async def supersede_plan_step_executions(
    session: AsyncSession,
    *,
    plan_version_id: str,
) -> None:
    await session.execute(
        update(AgentStepExecution)
        .where(
            AgentStepExecution.plan_version_id == plan_version_id,
            AgentStepExecution.status.not_in(TERMINAL_STEP_STATUSES),
        )
        .values(
            status=AgentStepExecutionStatus.superseded.value,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            finished_at=datetime.now(UTC),
        )
    )


async def _bind_dependency_artifacts(
    session: AsyncSession,
    *,
    execution: AgentStepExecution,
    step: PlanStepSpec,
    steps_by_key: dict[str, PlanStepSpec],
    latest_by_key: dict[str, AgentStepExecution],
) -> None:
    existing_names = set(
        await session.scalars(
            select(AgentStepArtifactInput.input_name).where(
                AgentStepArtifactInput.step_execution_id == execution.id
            )
        )
    )
    for dependency_key in step.depends_on:
        dependency = latest_by_key.get(dependency_key)
        dependency_spec = steps_by_key.get(dependency_key)
        if (
            dependency is None
            or dependency_spec is None
            or dependency.output_artifact_version_id is None
        ):
            continue
        input_name = dependency_spec.expected_artifact
        if input_name in existing_names:
            continue
        session.add(
            AgentStepArtifactInput(
                tenant_id=execution.tenant_id,
                step_execution_id=execution.id,
                input_name=input_name,
                artifact_key=dependency_spec.expected_artifact,
                artifact_version_id=dependency.output_artifact_version_id,
            )
        )


async def claim_ready_agent_steps(
    production_order_id: str,
    *,
    agent_run_id: str | None,
    worker_id: str,
    limit: int | None = None,
    observe_waiting: bool = False,
) -> list[AgentStepClaim]:
    settings = get_settings()
    claim_limit = limit or settings.agent_step_max_concurrency
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        order = await session.scalar(
            select(ProductionOrder)
            .where(ProductionOrder.id == production_order_id)
            .with_for_update(skip_locked=True)
        )
        if order is None or order.status not in CLAIMABLE_ORDER_STATUSES:
            return []
        run_query = select(AgentRun).where(AgentRun.production_order_id == order.id)
        if agent_run_id:
            run_query = run_query.where(AgentRun.id == agent_run_id)
        run = await session.scalar(
            run_query.order_by(AgentRun.run_number.desc()).limit(1)
        )
        if run is None:
            return []
        plan = await session.scalar(
            select(PlanVersion)
            .where(
                PlanVersion.agent_run_id == run.id,
                PlanVersion.status == PlanVersionStatus.active,
            )
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        if plan is None:
            return []
        plan_spec = AgentPlanSpec.model_validate(plan.plan_payload)
        executions = list(
            await session.scalars(
                select(AgentStepExecution).where(
                    AgentStepExecution.plan_version_id == plan.id,
                )
            )
        )
        expected_keys = {step.key for step in plan_spec.steps}
        materialized_keys = {execution.plan_step_key for execution in executions}
        missing_keys = sorted(expected_keys - materialized_keys)
        if missing_keys:
            error_code = "LEGACY_RUNTIME_STATE_UNSAFE_TO_RECONCILE"
            order.status = ProductionOrderStatus.manual_intervention
            run.status = AgentRunStatus.failed
            run.stop_reason = error_code
            for execution in executions:
                if execution.status in TERMINAL_STEP_STATUSES:
                    continue
                execution.status = AgentStepExecutionStatus.failed_final.value
                execution.error_code = error_code
                execution.error_message = (
                    "Active PlanVersion is missing authoritative step executions"
                )
                execution.finished_at = now
                execution.fence_token += 1
                execution.lease_owner = None
                execution.lease_expires_at = None
                execution.heartbeat_at = None
                execution.next_wakeup_at = None
            session.add(
                AgentEvent(
                    tenant_id=order.tenant_id,
                    production_order_id=order.id,
                    agent_run_id=run.id,
                    event_type="agent.runtime.manual_intervention",
                    payload={
                        "error_code": error_code,
                        "plan_version_id": plan.id,
                        "missing_step_keys": missing_keys,
                    },
                )
            )
            await session.commit()
            return []
        executions = sorted(executions, key=lambda item: item.attempt)
        latest_by_key: dict[str, AgentStepExecution] = {}
        for execution in executions:
            latest_by_key[execution.plan_step_key] = execution
        steps_by_key = {step.key: step for step in plan_spec.steps}
        completed = {
            key
            for key, execution in latest_by_key.items()
            if execution.status == AgentStepExecutionStatus.succeeded.value
        }
        raw_inputs = (run.context_snapshot or {}).get("inputs") or {}
        stable_inputs = raw_inputs if isinstance(raw_inputs, dict) else {}
        claims: list[AgentStepClaim] = []
        evaluating_claimed = False
        for step in plan_spec.steps:
            if len(claims) >= claim_limit:
                break
            current = latest_by_key[step.key]
            if current.status == AgentStepExecutionStatus.succeeded.value:
                continue
            if not set(step.depends_on).issubset(completed):
                continue
            next_wakeup = _aware(current.next_wakeup_at)
            lease_expires = _aware(current.lease_expires_at)
            if (
                next_wakeup
                and next_wakeup > now
                and not (
                    observe_waiting
                    and current.status == AgentStepExecutionStatus.waiting.value
                )
            ):
                continue
            if (
                current.status in {
                    AgentStepExecutionStatus.running.value,
                    AgentStepExecutionStatus.evaluating.value,
                }
                and lease_expires
                and lease_expires > now
            ):
                continue
            if current.status not in RECLAIMABLE_STEP_STATUSES:
                continue
            if current.status == AgentStepExecutionStatus.retry_wait.value:
                if current.attempt >= current.max_attempts:
                    current.status = AgentStepExecutionStatus.failed_final.value
                    current.finished_at = now
                    order.status = ProductionOrderStatus.manual_intervention
                    run.status = AgentRunStatus.failed
                    run.stop_reason = "agent_step_attempts_exhausted"
                    continue
                next_attempt = current.attempt + 1
                replacement = AgentStepExecution(
                    tenant_id=current.tenant_id,
                    production_order_id=current.production_order_id,
                    agent_run_id=current.agent_run_id,
                    plan_version_id=current.plan_version_id,
                    parent_execution_id=current.id,
                    plan_step_key=current.plan_step_key,
                    capability_key=current.capability_key,
                    capability_version=current.capability_version,
                    evaluator_key=current.evaluator_key,
                    evaluator_version=current.evaluator_version,
                    execution_kind=current.execution_kind,
                    attempt=next_attempt,
                    max_attempts=current.max_attempts,
                    evaluation_max_attempts=current.evaluation_max_attempts,
                    status=AgentStepExecutionStatus.pending.value,
                    idempotency_key=_execution_identity(plan.id, step.key, next_attempt),
                    state_origin=current.state_origin,
                    input_payload=dict(current.input_payload or {}),
                    runtime_binding_payload=dict(current.runtime_binding_payload or {}),
                )
                session.add(replacement)
                await session.flush()
                current = replacement
                latest_by_key[step.key] = current
            if current.started_at is None:
                current.input_payload = dict(stable_inputs)
                current.started_at = now
            await _bind_dependency_artifacts(
                session,
                execution=current,
                step=step,
                steps_by_key=steps_by_key,
                latest_by_key=latest_by_key,
            )
            current.fence_token += 1
            if current.status != AgentStepExecutionStatus.evaluating.value:
                current.status = AgentStepExecutionStatus.running.value
            else:
                evaluating_claimed = True
            current.lease_owner = worker_id
            current.lease_expires_at = now + timedelta(
                seconds=settings.agent_step_lease_seconds
            )
            current.heartbeat_at = now
            current.next_wakeup_at = None
            current.error_code = None
            current.error_message = None
            claims.append(
                AgentStepClaim(
                    execution_id=current.id,
                    production_order_id=order.id,
                    agent_run_id=run.id,
                    plan_version_id=plan.id,
                    plan_step_key=step.key,
                    attempt=current.attempt,
                    worker_id=worker_id,
                    fence_token=current.fence_token,
                )
            )
        if claims:
            order.status = (
                ProductionOrderStatus.evaluating
                if evaluating_claimed
                else ProductionOrderStatus.running
            )
            run.status = (
                AgentRunStatus.evaluating if evaluating_claimed else AgentRunStatus.running
            )
        await session.commit()
        return claims


async def renew_agent_step_lease(claim: AgentStepClaim) -> bool:
    settings = get_settings()
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        result = await session.execute(
            update(AgentStepExecution)
            .where(
                AgentStepExecution.id == claim.execution_id,
                AgentStepExecution.status.in_(
                    [
                        AgentStepExecutionStatus.running.value,
                        AgentStepExecutionStatus.evaluating.value,
                    ]
                ),
                AgentStepExecution.lease_owner == claim.worker_id,
                AgentStepExecution.fence_token == claim.fence_token,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now
                + timedelta(seconds=settings.agent_step_lease_seconds),
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def execution_claim_is_current(
    session: AsyncSession,
    claim: AgentStepClaim,
    *,
    lock: bool = False,
) -> AgentStepExecution | None:
    query = select(AgentStepExecution).where(
        AgentStepExecution.id == claim.execution_id,
        AgentStepExecution.status.in_(
            [
                AgentStepExecutionStatus.running.value,
                AgentStepExecutionStatus.evaluating.value,
            ]
        ),
        AgentStepExecution.lease_owner == claim.worker_id,
        AgentStepExecution.fence_token == claim.fence_token,
    )
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)
