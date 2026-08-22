from datetime import UTC, datetime

from sqlalchemy import select

from app.agent.contracts import CapabilityOutcome, OutcomeStatus
from app.agent.executor import AgentExecutionRequest
from app.agent.operations import AgentOperationStatus, ExecutionPolicy
from app.capabilities.base import CapabilityContext
from app.capabilities.registry import CapabilityRegistration, CapabilityRegistry
from app.models.agent import AgentOperation


class CapabilityUnavailableError(RuntimeError):
    pass


class CapabilityDispatcher:
    """Resolve a product capability without exposing its execution mechanism.

    Normal product abilities use a CapabilityHandler. Optional external-executor
    abilities are persisted as AgentOperations and observed through the same
    outcome contract, so the Agent runtime has no Executor-specific branches.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def can_execute(self, key: str, version: str | None = None) -> bool:
        return self.registry.is_executable(key, version)

    async def execute(self, context: CapabilityContext) -> CapabilityOutcome:
        registration = self.registry.resolve(
            context.step.capability,
            context.step.capability_version,
        )
        if registration is None or not self.registry.is_executable(
            context.step.capability,
            context.step.capability_version,
        ):
            raise CapabilityUnavailableError(
                "能力实现版本尚未安装："
                f"{context.step.capability}@{context.step.capability_version or 'legacy-unpinned'}"
            )
        if registration.handler is not None:
            return await registration.handler.execute(context)
        return await self._execute_with_external_executor(context, registration)

    async def interrupt(
        self,
        context: CapabilityContext,
        external_execution_id: str | None,
    ) -> None:
        registration = self.registry.resolve(
            context.step.capability,
            context.step.capability_version,
        )
        if registration is None:
            return
        if registration.handler is not None:
            await registration.handler.interrupt(context, external_execution_id)
            return
        if not external_execution_id or not registration.external_executor_key:
            return
        operation = await context.session.get(AgentOperation, external_execution_id)
        if operation is None or operation.agent_run_id != context.run.id:
            return
        if operation.status in {
            AgentOperationStatus.succeeded.value,
            AgentOperationStatus.failed_final.value,
        }:
            return
        already_canceled = operation.status == AgentOperationStatus.canceled.value
        if operation.external_execution_id:
            from app.executors.registry import get_executor_registry

            executor = get_executor_registry().executor(
                operation.executor_key or registration.external_executor_key,
                operation.executor_version,
            )
            if executor is not None:
                await executor.interrupt(operation.external_execution_id)
        if not already_canceled:
            operation.status = AgentOperationStatus.canceled.value
            operation.finished_at = datetime.now(UTC)
            operation.fence_token += 1
            operation.lease_owner = None
            operation.lease_expires_at = None
            operation.heartbeat_at = None

    async def _execute_with_external_executor(
        self,
        context: CapabilityContext,
        registration: CapabilityRegistration,
    ) -> CapabilityOutcome:
        from app.services.agent_operation_service import (
            stage_external_executor_operation,
        )

        definition = registration.definition
        executor_key = registration.external_executor_key
        if not executor_key:
            raise CapabilityUnavailableError(
                f"能力缺少 Executor 绑定：{context.step.capability}"
            )
        executor_binding = dict(
            context.runtime_binding_payload.get("external_executor") or {}
        )
        executor_version = (
            str(executor_binding.get("version"))
            if executor_binding.get("key") == executor_key
            else None
        )
        idempotency_key = (
            f"capability:{context.run.id}:{context.plan.id}:{context.step.key}:"
            f"attempt:{context.execution_attempt}"
        )
        operation = await context.session.scalar(
            select(AgentOperation).where(
                AgentOperation.idempotency_key == idempotency_key
            )
        )
        if operation is None:
            snapshot = context.run.context_snapshot or {}
            granted_permissions = list(snapshot.get("granted_permissions") or [])
            request_inputs = dict(context.inputs)
            if context.evaluation_feedback:
                request_inputs["_evaluation_feedback"] = context.evaluation_feedback
            request = AgentExecutionRequest(
                tenant_id=context.order.tenant_id,
                production_order_id=context.order.id,
                agent_run_id=context.run.id,
                plan_version_id=context.plan.id,
                capability=context.step.capability,
                objective=(
                    f"{context.plan.goal}; produce {context.step.expected_artifact}"
                ),
                inputs=request_inputs,
                allowed_tools=list(registration.metadata.get("allowed_tools") or []),
                workspace_ref=snapshot.get("workspace_ref"),
                idempotency_key=idempotency_key,
            )
            operation, _ = await stage_external_executor_operation(
                context.session,
                order=context.order,
                run=context.run,
                executor_key=executor_key,
                executor_version=executor_version,
                request=request,
                idempotency_key=idempotency_key,
                policy=ExecutionPolicy(
                    required_permissions=definition.required_permissions,
                    granted_permissions=granted_permissions,
                    timeout_seconds=definition.timeout_seconds,
                    budget_limit=context.order.budget_limit,
                ),
            )
            return CapabilityOutcome(
                status=OutcomeStatus.dispatched,
                external_execution_id=operation.id,
                metadata={"execution_kind": "external", "executor_key": executor_key},
            )

        if operation.status == AgentOperationStatus.succeeded.value:
            payload = operation.metadata_payload.get("capability_outcome")
            if not isinstance(payload, dict):
                return CapabilityOutcome(
                    status=OutcomeStatus.failed,
                    external_execution_id=operation.id,
                    error_code="INVALID_EXECUTOR_RESULT",
                    message="Executor 未返回 CapabilityOutcome 合同",
                )
            outcome = CapabilityOutcome.model_validate(payload)
            if outcome.external_execution_id is None:
                outcome = outcome.model_copy(
                    update={"external_execution_id": operation.external_execution_id}
                )
            return outcome
        if operation.status == AgentOperationStatus.failed_final.value:
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                external_execution_id=operation.id,
                error_code=operation.error_code or "EXECUTOR_FAILED",
                message=operation.error_message or "Executor 执行失败",
            )
        if operation.status == AgentOperationStatus.canceled.value:
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                external_execution_id=operation.id,
                error_code="EXECUTOR_CANCELED",
                message="Executor 执行已取消",
            )
        return CapabilityOutcome(
            status=OutcomeStatus.waiting,
            external_execution_id=operation.id,
            metadata={"operation_status": operation.status},
        )
