import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import AgentIntentSpec
from app.agent.executor import AgentExecutionRequest, AgentExecutionResult
from app.agent.operations import (
    AgentOperationStatus,
    AgentOperationType,
    ExecutionPolicy,
    TraceContext,
)
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.executors.registry import get_executor_registry
from app.integrations.new_api_brain import BrainConfigurationError, BrainGatewayError
from app.integrations.managed_brain import resolve_brain_binding_snapshot
from app.models.agent import (
    AgentEvent,
    AgentOperation,
    AgentRun,
    AgentRunStatus,
    DecisionRequest,
    OutboxEvent,
    PlanVersion,
    PlanVersionStatus,
    ProductionOrder,
    ProductionOrderStatus,
)
from app.product.planning import build_product_plan_result
from app.schemas.agent import ProductionOrderCreate
from app.services.agent_step_service import (
    materialize_plan_step_executions,
    supersede_plan_step_executions,
)


TERMINAL_OPERATION_STATUSES = {
    AgentOperationStatus.succeeded.value,
    AgentOperationStatus.failed_final.value,
    AgentOperationStatus.canceled.value,
}
PLANNING_IMPLEMENTATION_VERSION = "2.0.0"
EXTERNAL_OPERATION_IMPLEMENTATION_VERSION = "2.0.0"


class PermanentOperationError(RuntimeError):
    pass


@dataclass(slots=True)
class OperationExecutionResult:
    status: AgentOperationStatus
    external_execution_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    plan_result: Any | None = None


def _trace_context(parent_trace_id: str | None = None, parent_span_id: str | None = None) -> TraceContext:
    return TraceContext(
        trace_id=parent_trace_id or uuid.uuid4().hex,
        span_id=uuid.uuid4().hex[:16],
        parent_span_id=parent_span_id,
    )


async def stage_agent_operation(
    session: AsyncSession,
    *,
    order: ProductionOrder,
    run: AgentRun,
    operation_type: AgentOperationType,
    operation_key: str,
    idempotency_key: str,
    policy: ExecutionPolicy,
    metadata: dict[str, Any] | None = None,
    implementation_version: str | None = None,
    executor_key: str | None = None,
    executor_version: str | None = None,
    trace: TraceContext | None = None,
) -> tuple[AgentOperation, bool]:
    existing = await session.scalar(
        select(AgentOperation).where(AgentOperation.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing, False
    trace_context = trace or _trace_context()
    operation = AgentOperation(
        tenant_id=order.tenant_id,
        production_order_id=order.id,
        agent_run_id=run.id,
        operation_type=operation_type.value,
        operation_key=operation_key,
        implementation_version=implementation_version,
        status=AgentOperationStatus.queued.value,
        idempotency_key=idempotency_key,
        executor_key=executor_key,
        executor_version=executor_version,
        trace_id=trace_context.trace_id,
        span_id=trace_context.span_id,
        parent_span_id=trace_context.parent_span_id,
        required_permissions=policy.required_permissions,
        granted_permissions=policy.granted_permissions,
        timeout_seconds=policy.timeout_seconds,
        budget_limit=policy.budget_limit,
        budget_reserved=policy.budget_reserve,
        budget_spent=Decimal("0"),
        metadata_payload=metadata or {},
        max_attempts=policy.max_attempts,
        next_wakeup_at=datetime.now(UTC),
    )
    session.add(operation)
    await session.flush()
    session.add(
        OutboxEvent(
            tenant_id=order.tenant_id,
            aggregate_type="agent_operation",
            aggregate_id=operation.id,
            topic="agent.operation.requested",
            payload={"agent_operation_id": operation.id},
            dedupe_key=f"agent-operation:{operation.id}:created",
        )
    )
    session.add(
        AgentEvent(
            tenant_id=order.tenant_id,
            production_order_id=order.id,
            agent_run_id=run.id,
            event_type="agent.operation.queued",
            payload={
                "agent_operation_id": operation.id,
                "operation_type": operation.operation_type,
                "operation_key": operation.operation_key,
                "trace_id": operation.trace_id,
                "span_id": operation.span_id,
            },
        )
    )
    return operation, True


async def stage_planning_operation(
    session: AsyncSession,
    *,
    order: ProductionOrder,
    run: AgentRun,
    idempotency_key: str,
    reason: str,
    planning_context: dict[str, Any] | None = None,
) -> tuple[AgentOperation, bool]:
    settings = get_settings()
    try:
        brain_binding = await resolve_brain_binding_snapshot(
            order.tenant_id,
            "reasoning.default",
        )
    except BrainConfigurationError as exc:
        brain_binding = {
            "model_alias": "reasoning.default",
            "resolution_error": str(exc),
        }
    operation, created = await stage_agent_operation(
        session,
        order=order,
        run=run,
        operation_type=AgentOperationType.planning,
        operation_key="production.plan",
        implementation_version=PLANNING_IMPLEMENTATION_VERSION,
        idempotency_key=idempotency_key,
        policy=ExecutionPolicy(
            required_permissions=["brain.plan"],
            granted_permissions=["brain.plan"],
            timeout_seconds=settings.planning_timeout_seconds,
            max_attempts=settings.planning_max_attempts,
            budget_limit=order.budget_limit,
        ),
        metadata={
            "reason": reason,
            "planning_context": planning_context or {},
            "brain_binding": brain_binding,
        },
    )
    return operation, created


async def stage_external_executor_operation(
    session: AsyncSession,
    *,
    order: ProductionOrder,
    run: AgentRun,
    executor_key: str,
    executor_version: str | None = None,
    request: AgentExecutionRequest,
    idempotency_key: str,
    policy: ExecutionPolicy,
    trace: TraceContext | None = None,
) -> tuple[AgentOperation, bool]:
    definition = get_executor_registry().definition(executor_key, executor_version)
    if definition is None:
        raise ValueError(f"Executor 尚未注册：{executor_key}")
    required_permissions = set(policy.required_permissions)
    if definition is not None:
        required_permissions.update(definition.required_permissions)
    effective_policy = policy.model_copy(
        update={"required_permissions": sorted(required_permissions)}
    )
    operation, created = await stage_agent_operation(
        session,
        order=order,
        run=run,
        operation_type=AgentOperationType.executor,
        operation_key=request.capability,
        implementation_version=EXTERNAL_OPERATION_IMPLEMENTATION_VERSION,
        idempotency_key=idempotency_key,
        policy=effective_policy,
        metadata={"execution_request": request.model_dump(mode="json")},
        executor_key=executor_key,
        executor_version=definition.version,
        trace=trace,
    )
    operation.plan_version_id = request.plan_version_id
    return operation, created


def _production_request(order: ProductionOrder, run: AgentRun) -> ProductionOrderCreate:
    context = run.context_snapshot or {}
    inputs = dict(context.get("inputs") or {})
    return ProductionOrderCreate(
        project_id=order.project_id,
        product_key=str(
            context.get("product_key")
            or inputs.get("_product_key")
            or "digital_human.video"
        ),
        title=order.title,
        intent_text=order.intent_text,
        automation_mode=order.automation_mode,
        checkpoint_policy=order.checkpoint_policy,
        external_side_effect_policy=order.external_side_effect_policy,
        budget_limit=order.budget_limit,
        max_auto_rework=order.max_auto_rework,
        content_item_id=order.content_item_id,
        inputs=inputs,
    )


async def _execute_planning(
    operation: AgentOperation,
    order: ProductionOrder,
    run: AgentRun,
) -> OperationExecutionResult:
    intent = AgentIntentSpec.model_validate(order.intent_spec)
    result = await asyncio.wait_for(
        build_product_plan_result(
            _production_request(order, run),
            intent,
            tenant_id=order.tenant_id,
            planning_context=dict(operation.metadata_payload.get("planning_context") or {}),
            invocation_metadata={
                "agent_operation_id": operation.id,
                "production_order_id": order.id,
                "trace_id": operation.trace_id,
            },
            brain_binding_snapshot=dict(
                operation.metadata_payload.get("brain_binding") or {}
            ) or None,
        ),
        timeout=operation.timeout_seconds,
    )
    return OperationExecutionResult(
        status=AgentOperationStatus.succeeded,
        usage=result.usage,
        metadata={
            "model_ref": result.model_ref,
            "gateway_ref": result.gateway_ref,
        },
        plan_result=result,
    )


async def _execute_external_executor(
    operation: AgentOperation,
) -> OperationExecutionResult:
    if not operation.executor_key:
        raise PermanentOperationError("Executor 操作缺少内部 executor_key")
    executor = get_executor_registry().executor(
        operation.executor_key,
        operation.executor_version,
    )
    if executor is None:
        raise PermanentOperationError("请求的 Executor 尚未安装")
    request_payload = operation.metadata_payload.get("execution_request") or {}
    request = AgentExecutionRequest.model_validate(request_payload)
    if operation.external_execution_id:
        handle = await asyncio.wait_for(
            executor.resume(operation.external_execution_id),
            timeout=operation.timeout_seconds,
        )
    else:
        handle = await asyncio.wait_for(
            executor.start(request),
            timeout=operation.timeout_seconds,
        )
    state = handle.state.lower()
    if state in {"succeeded", "completed"}:
        raw_result = await asyncio.wait_for(
            executor.collect_result(handle.execution_id),
            timeout=operation.timeout_seconds,
        )
        result = AgentExecutionResult.model_validate(raw_result)
        return OperationExecutionResult(
            status=AgentOperationStatus.succeeded,
            external_execution_id=handle.execution_id,
            usage=result.usage,
            metadata={
                "capability_outcome": result.outcome.model_dump(mode="json"),
                "executor_metadata": result.metadata,
            },
        )
    if state in {"failed", "canceled", "cancelled"}:
        raise PermanentOperationError(f"Executor 返回终态：{state}")
    return OperationExecutionResult(
        status=AgentOperationStatus.waiting,
        external_execution_id=handle.execution_id,
        metadata={"executor_state": state},
    )


async def _append_operation_event(
    session: AsyncSession,
    operation: AgentOperation,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    session.add(
        AgentEvent(
            tenant_id=operation.tenant_id,
            production_order_id=operation.production_order_id,
            agent_run_id=operation.agent_run_id,
            event_type=event_type,
            payload={
                "agent_operation_id": operation.id,
                "operation_type": operation.operation_type,
                "operation_key": operation.operation_key,
                "trace_id": operation.trace_id,
                "span_id": operation.span_id,
                **payload,
            },
        )
    )


async def _apply_plan_result(
    session: AsyncSession,
    operation: AgentOperation,
    order: ProductionOrder,
    run: AgentRun,
    result: OperationExecutionResult,
) -> None:
    generated = result.plan_result
    if generated is None:
        raise RuntimeError("规划操作缺少 PlanGenerationResult")
    current = await session.scalar(
        select(PlanVersion)
        .where(PlanVersion.agent_run_id == run.id)
        .order_by(PlanVersion.version.desc())
        .limit(1)
    )
    version_number = (current.version + 1) if current else 1
    if current is not None and current.status in {
        PlanVersionStatus.draft,
        PlanVersionStatus.active,
    }:
        current.status = PlanVersionStatus.superseded
        await supersede_plan_step_executions(
            session,
            plan_version_id=current.id,
        )
    plan_payload = generated.plan.model_dump(mode="json")
    plan = PlanVersion(
        tenant_id=order.tenant_id,
        agent_run_id=run.id,
        version=version_number,
        goal=generated.plan.goal,
        success_criteria=[
            "内容与项目及 IP 定位一致",
            "所需媒体质量通过",
            "交付物符合目标平台要求",
            "最终产物经过策略要求的审核",
        ],
        plan_payload=plan_payload,
        budget_estimate=Decimal("0"),
        status=PlanVersionStatus.active,
    )
    session.add(plan)
    await session.flush()
    await materialize_plan_step_executions(
        session,
        order=order,
        run=run,
        plan=plan,
        plan_spec=generated.plan,
    )
    operation.plan_version_id = plan.id
    await _append_operation_event(
        session,
        operation,
        "plan.version.created",
        {
            "plan_version_id": plan.id,
            "version": plan.version,
            "planner": generated.plan.planner,
            "usage": result.usage,
        },
    )
    requires_approval = order.automation_mode != "automatic"
    if requires_approval:
        order.status = ProductionOrderStatus.awaiting_plan_approval
        run.status = AgentRunStatus.awaiting_decision
        session.add(
            DecisionRequest(
                tenant_id=order.tenant_id,
                production_order_id=order.id,
                agent_run_id=run.id,
                plan_version_id=plan.id,
                reason_code="PLAN_REVIEW",
                title="确认本次内容生产方案",
                summary=f"Agent 已形成 {len(generated.plan.steps)} 个步骤的生产计划。",
                options=[
                    {"key": "approve_plan", "label": "采用方案并开始生产"},
                    {"key": "request_changes", "label": "调整目标或约束"},
                    {"key": "cancel_order", "label": "取消生产单"},
                ],
                recommended_option="approve_plan",
                blocking=True,
            )
        )
    else:
        order.status = ProductionOrderStatus.queued
        run.status = AgentRunStatus.running
        session.add(
            OutboxEvent(
                tenant_id=order.tenant_id,
                aggregate_type="production_order",
                aggregate_id=order.id,
                topic="agent.run.requested",
                payload={"production_order_id": order.id, "agent_run_id": run.id},
                dedupe_key=f"agent-run:{run.id}:plan:{plan.id}",
            )
        )


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, (BrainGatewayError, BrainConfigurationError, PermanentOperationError, ValueError)):
        return str(exc)[:1000]
    if isinstance(exc, TimeoutError):
        return "操作执行超时"
    return "内部操作执行异常"


async def _record_failure(
    operation_id: str,
    exc: Exception,
    *,
    expected_worker_id: str | None = None,
    expected_fence_token: int | None = None,
) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        operation = await session.scalar(
            select(AgentOperation)
            .where(AgentOperation.id == operation_id)
            .with_for_update()
        )
        if operation is None or operation.status in TERMINAL_OPERATION_STATUSES:
            return
        if expected_worker_id is not None and operation.lease_owner != expected_worker_id:
            return
        if expected_fence_token is not None and operation.fence_token != expected_fence_token:
            return
        order = await session.get(ProductionOrder, operation.production_order_id)
        run = await session.get(AgentRun, operation.agent_run_id)
        permanent = isinstance(exc, PermanentOperationError)
        exhausted = operation.attempt >= operation.max_attempts
        operation.error_code = type(exc).__name__[:128]
        operation.error_message = _safe_error_message(exc)
        operation.lease_owner = None
        operation.lease_expires_at = None
        operation.heartbeat_at = None
        if permanent or exhausted:
            operation.status = AgentOperationStatus.failed_final.value
            operation.finished_at = datetime.now(UTC)
            if order is not None:
                order.status = ProductionOrderStatus.manual_intervention
            if run is not None:
                run.status = AgentRunStatus.failed
                run.stop_reason = "agent_operation_failed"
            event_type = "agent.operation.failed_final"
        else:
            operation.status = AgentOperationStatus.retry_wait.value
            operation.started_at = None
            delay = settings.agent_operation_retry_base_seconds * (2 ** max(0, operation.attempt - 1))
            operation.next_wakeup_at = datetime.now(UTC) + timedelta(seconds=delay)
            event_type = "agent.operation.retry_scheduled"
        await _append_operation_event(
            session,
            operation,
            event_type,
            {
                "attempt": operation.attempt,
                "max_attempts": operation.max_attempts,
                "error_code": operation.error_code,
                "message": operation.error_message,
                "next_wakeup_at": (
                    operation.next_wakeup_at.isoformat() if operation.next_wakeup_at else None
                ),
            },
        )
        await session.commit()


async def _renew_operation_lease(
    operation_id: str,
    *,
    worker_id: str,
    fence_token: int,
) -> bool:
    now = datetime.now(UTC)
    settings = get_settings()
    async with SessionLocal() as session:
        result = await session.execute(
            update(AgentOperation)
            .where(
                AgentOperation.id == operation_id,
                AgentOperation.status == AgentOperationStatus.running.value,
                AgentOperation.lease_owner == worker_id,
                AgentOperation.fence_token == fence_token,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now
                + timedelta(seconds=settings.agent_operation_lease_seconds),
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def _operation_heartbeat_loop(
    operation_id: str,
    *,
    worker_id: str,
    fence_token: int,
    stopped: asyncio.Event,
) -> None:
    interval = max(1.0, get_settings().agent_operation_lease_seconds / 3)
    while not stopped.is_set():
        try:
            await asyncio.wait_for(stopped.wait(), timeout=interval)
        except TimeoutError:
            if not await _renew_operation_lease(
                operation_id,
                worker_id=worker_id,
                fence_token=fence_token,
            ):
                return


async def run_agent_operation_once(operation_id: str, worker_id: str = "agent-worker") -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        operation = await session.scalar(
            select(AgentOperation)
            .where(AgentOperation.id == operation_id)
            .with_for_update()
        )
        if operation is None or operation.status in TERMINAL_OPERATION_STATUSES:
            return
        now = datetime.now(UTC)
        if operation.next_wakeup_at and operation.next_wakeup_at > now:
            return
        if (
            operation.status == AgentOperationStatus.running.value
            and operation.lease_expires_at
            and operation.lease_expires_at > now
        ):
            return
        order = await session.get(ProductionOrder, operation.production_order_id)
        run = await session.get(AgentRun, operation.agent_run_id)
        if order is None or run is None:
            raise RuntimeError("AgentOperation 缺少所属生产单或运行")
        if order.status == ProductionOrderStatus.paused:
            operation.status = AgentOperationStatus.waiting.value
            operation.next_wakeup_at = now + timedelta(
                seconds=settings.runtime_recovery_interval_seconds
            )
            operation.lease_owner = None
            operation.lease_expires_at = None
            await session.commit()
            return
        if order.status in {
            ProductionOrderStatus.canceling,
            ProductionOrderStatus.canceled,
        }:
            operation.status = AgentOperationStatus.canceled.value
            operation.finished_at = now
            operation.lease_owner = None
            operation.lease_expires_at = None
            await _append_operation_event(
                session,
                operation,
                "agent.operation.canceled",
                {},
            )
            await session.commit()
            return
        preflight_error: Exception | None = None
        required = set(operation.required_permissions or [])
        granted = set(operation.granted_permissions or [])
        if not required.issubset(granted):
            preflight_error = PermanentOperationError("操作缺少所需权限")
        spent = Decimal(
            await session.scalar(
                select(func.coalesce(func.sum(AgentOperation.budget_spent), 0)).where(
                    AgentOperation.production_order_id == operation.production_order_id
                )
            )
            or 0
        )
        reserved = Decimal(operation.budget_reserved or 0)
        if operation.budget_limit is not None and spent + reserved > operation.budget_limit:
            preflight_error = PermanentOperationError("操作预算不足")
        if operation.started_at and now - operation.started_at > timedelta(seconds=operation.timeout_seconds):
            preflight_error = TimeoutError()
        if operation.status != AgentOperationStatus.waiting.value:
            operation.attempt += 1
        operation.status = AgentOperationStatus.running.value
        operation.started_at = operation.started_at or now
        operation.lease_owner = worker_id
        operation.fence_token += 1
        operation.heartbeat_at = now
        operation.lease_expires_at = now + timedelta(seconds=settings.agent_operation_lease_seconds)
        operation.next_wakeup_at = None
        operation.error_code = None
        operation.error_message = None
        await _append_operation_event(
            session,
            operation,
            "agent.operation.started",
            {
                "attempt": operation.attempt,
                "worker_id": worker_id,
                "fence_token": operation.fence_token,
            },
        )
        fence_token = operation.fence_token
        await session.commit()

    if preflight_error is not None:
        await _record_failure(
            operation_id,
            preflight_error,
            expected_worker_id=worker_id,
            expected_fence_token=fence_token,
        )
        return

    heartbeat_stopped = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _operation_heartbeat_loop(
            operation_id,
            worker_id=worker_id,
            fence_token=fence_token,
            stopped=heartbeat_stopped,
        )
    )
    try:
        if operation.operation_type == AgentOperationType.planning.value:
            result = await _execute_planning(operation, order, run)
        elif operation.operation_type == AgentOperationType.executor.value:
            result = await _execute_external_executor(operation)
        else:
            raise PermanentOperationError(f"未知 AgentOperation 类型：{operation.operation_type}")
    except Exception as exc:  # noqa: BLE001
        await _record_failure(
            operation_id,
            exc,
            expected_worker_id=worker_id,
            expected_fence_token=fence_token,
        )
        return
    finally:
        heartbeat_stopped.set()
        await heartbeat_task

    async with SessionLocal() as session:
        locked = await session.scalar(
            select(AgentOperation)
            .where(
                AgentOperation.id == operation_id,
                AgentOperation.status == AgentOperationStatus.running.value,
                AgentOperation.lease_owner == worker_id,
                AgentOperation.fence_token == fence_token,
            )
            .with_for_update()
        )
        if locked is None or locked.status in TERMINAL_OPERATION_STATUSES:
            return
        order = await session.get(ProductionOrder, locked.production_order_id)
        run = await session.get(AgentRun, locked.agent_run_id)
        if order is None or run is None:
            raise RuntimeError("AgentOperation 缺少所属生产单或运行")
        if order.status in {
            ProductionOrderStatus.canceling,
            ProductionOrderStatus.canceled,
        }:
            locked.status = AgentOperationStatus.canceled.value
            locked.finished_at = datetime.now(UTC)
            locked.lease_owner = None
            locked.lease_expires_at = None
            await _append_operation_event(
                session,
                locked,
                "agent.operation.canceled",
                {},
            )
            await session.commit()
            return
        was_paused = order.status == ProductionOrderStatus.paused
        locked.external_execution_id = result.external_execution_id
        locked.usage_payload = result.usage
        locked.metadata_payload = {**locked.metadata_payload, **result.metadata}
        locked.lease_owner = None
        locked.lease_expires_at = None
        locked.heartbeat_at = None
        if result.status == AgentOperationStatus.waiting:
            locked.status = AgentOperationStatus.waiting.value
            locked.next_wakeup_at = datetime.now(UTC) + timedelta(
                seconds=settings.agent_operation_retry_base_seconds
            )
            await _append_operation_event(
                session,
                locked,
                "agent.operation.waiting",
                {
                    "external_execution_id": result.external_execution_id,
                    "next_wakeup_at": locked.next_wakeup_at.isoformat(),
                },
            )
        else:
            if locked.operation_type == AgentOperationType.planning.value:
                await _apply_plan_result(session, locked, order, run, result)
                if was_paused:
                    order.status = ProductionOrderStatus.paused
                    run.status = AgentRunStatus.planning
            elif locked.operation_type == AgentOperationType.executor.value:
                session.add(
                    OutboxEvent(
                        tenant_id=order.tenant_id,
                        aggregate_type="production_order",
                        aggregate_id=order.id,
                        topic="agent.run.requested",
                        payload={
                            "production_order_id": order.id,
                            "agent_run_id": run.id,
                        },
                        dedupe_key=f"agent-observe-operation:{locked.id}:succeeded",
                    )
                )
            locked.status = AgentOperationStatus.succeeded.value
            locked.finished_at = datetime.now(UTC)
            await _append_operation_event(
                session,
                locked,
                "agent.operation.succeeded",
                {"usage": result.usage, "external_execution_id": result.external_execution_id},
            )
        await session.commit()


async def list_due_agent_operation_ids(limit: int = 20) -> list[str]:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        result = await session.scalars(
            select(AgentOperation.id)
            .where(
                AgentOperation.status.in_(
                    [
                        AgentOperationStatus.queued.value,
                        AgentOperationStatus.waiting.value,
                        AgentOperationStatus.retry_wait.value,
                        AgentOperationStatus.running.value,
                    ]
                ),
                (AgentOperation.next_wakeup_at.is_(None) | (AgentOperation.next_wakeup_at <= now)),
                (AgentOperation.lease_expires_at.is_(None) | (AgentOperation.lease_expires_at <= now)),
            )
            .order_by(AgentOperation.updated_at)
            .limit(limit)
        )
        return list(result)
