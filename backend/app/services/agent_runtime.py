import asyncio
import hashlib
import json
import os
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.agent.contracts import AgentPlanSpec, CapabilityOutcome, OutcomeStatus
from app.agent.evaluation import EvaluationAction
from app.agent.operations import AgentOperationStatus
from app.capabilities.base import CapabilityContext
from app.capabilities.dispatcher import CapabilityDispatcher, CapabilityUnavailableError
from app.capabilities.registry import get_capability_registry
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.agent import (
    AgentEvent,
    AgentOperation,
    AgentRun,
    AgentRunStatus,
    AgentStepArtifactInput,
    AgentStepExecution,
    AgentStepExecutionStatus,
    Artifact,
    ArtifactVersion,
    ArtifactVersionStatus,
    DecisionRequest,
    DecisionStatus,
    OutboxEvent,
    PlanVersion,
    PlanVersionStatus,
    ProductionOrder,
    ProductionOrderStatus,
)
from app.services.agent_operation_service import stage_planning_operation
from app.services.agent_step_service import (
    AgentStepClaim,
    TERMINAL_STEP_STATUSES,
    claim_ready_agent_steps,
    execution_claim_is_current,
    renew_agent_step_lease,
)
from app.services.evaluation_service import EvaluatorUnavailableError, evaluate_step


settings = get_settings()
agent_worker_id = f"{os.getenv('HOSTNAME', 'agent-worker')}-{uuid.uuid4().hex[:8]}"


async def _append_event(session, *, order, run, event_type: str, payload: dict[str, Any]) -> None:
    session.add(
        AgentEvent(
            tenant_id=order.tenant_id,
            production_order_id=order.id,
            agent_run_id=run.id,
            event_type=event_type,
            payload=payload,
        )
    )


async def _write_artifact(
    session,
    *,
    order: ProductionOrder,
    plan: PlanVersion,
    execution: AgentStepExecution,
    artifact_key: str,
    artifact_type: str,
    content_payload: dict[str, Any],
    lineage_payload: dict[str, Any],
    run: AgentRun,
) -> ArtifactVersion:
    artifact = await session.scalar(
        select(Artifact)
        .where(
            Artifact.production_order_id == order.id,
            Artifact.artifact_key == artifact_key,
        )
        .with_for_update()
    )
    if artifact is None:
        artifact = Artifact(
            tenant_id=order.tenant_id,
            production_order_id=order.id,
            content_item_id=order.content_item_id,
            artifact_key=artifact_key,
            artifact_type=artifact_type,
        )
        session.add(artifact)
        await session.flush()
    latest_version = await session.scalar(
        select(ArtifactVersion.version)
        .where(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version.desc())
        .limit(1)
    )
    checksum = hashlib.sha256(
        json.dumps(content_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    input_version_ids = list(
        await session.scalars(
            select(AgentStepArtifactInput.artifact_version_id).where(
                AgentStepArtifactInput.step_execution_id == execution.id
            )
        )
    )
    version = ArtifactVersion(
        tenant_id=order.tenant_id,
        artifact_id=artifact.id,
        plan_version_id=plan.id,
        version=int(latest_version or 0) + 1,
        status=ArtifactVersionStatus.candidate,
        content_payload=content_payload,
        lineage_payload={
            **lineage_payload,
            "agent_step_execution_id": execution.id,
            "plan_step_key": execution.plan_step_key,
            "capability": execution.capability_key,
            "capability_version": execution.capability_version,
            "input_artifact_version_ids": input_version_ids,
        },
        checksum=checksum,
    )
    session.add(version)
    await session.flush()
    await _append_event(
        session,
        order=order,
        run=run,
        event_type="artifact.version.created",
        payload={
            "artifact_id": artifact.id,
            "artifact_version_id": version.id,
            "artifact_key": artifact_key,
            "version": version.version,
            "agent_step_execution_id": execution.id,
        },
    )
    return version


async def _load_bound_artifacts(session, *, execution_id: str) -> dict[str, dict[str, Any]]:
    rows = list(
        (
            await session.execute(
                select(AgentStepArtifactInput, ArtifactVersion, Artifact)
                .join(ArtifactVersion, ArtifactVersion.id == AgentStepArtifactInput.artifact_version_id)
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(AgentStepArtifactInput.step_execution_id == execution_id)
            )
        ).all()
    )
    return {
        binding.input_name: {
            "artifact_id": artifact.id,
            "artifact_version_id": version.id,
            "artifact_type": artifact.artifact_type,
            "version": version.version,
            "status": version.status.value,
            "content": version.content_payload,
        }
        for binding, version, artifact in rows
    }


def _step_for_execution(plan_spec: AgentPlanSpec, execution: AgentStepExecution):
    step = next((item for item in plan_spec.steps if item.key == execution.plan_step_key), None)
    if step is None:
        raise RuntimeError(f"PlanVersion 缺少步骤：{execution.plan_step_key}")
    return step.model_copy(
        update={
            "capability_version": execution.capability_version,
            "evaluator_version": execution.evaluator_version,
        }
    )


async def _execute_claim(claim: AgentStepClaim) -> CapabilityOutcome:
    async with SessionLocal() as session:
        execution = await execution_claim_is_current(session, claim)
        if execution is None:
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                error_code="STALE_STEP_CLAIM",
                message="Step execution claim is no longer current",
            )
        if execution.status == AgentStepExecutionStatus.evaluating.value:
            persisted_outcome = (execution.runtime_binding_payload or {}).get(
                "capability_outcome"
            )
            if isinstance(persisted_outcome, dict):
                return CapabilityOutcome.model_validate(persisted_outcome)
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                error_code="EVALUATION_RESUME_STATE_MISSING",
                message="Persisted capability outcome is missing for evaluation resume",
            )
        order = await session.get(ProductionOrder, execution.production_order_id)
        run = await session.get(AgentRun, execution.agent_run_id)
        plan = await session.get(PlanVersion, execution.plan_version_id)
        if order is None or run is None or plan is None:
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                error_code="STEP_CONTEXT_MISSING",
                message="Step execution context is incomplete",
            )
        plan_spec = AgentPlanSpec.model_validate(plan.plan_payload)
        step = _step_for_execution(plan_spec, execution)
        artifacts = await _load_bound_artifacts(session, execution_id=execution.id)
        evaluation_feedback = list(
            (execution.runtime_binding_payload or {}).get("evaluation_feedback") or []
        )
        context = CapabilityContext(
            session=session,
            order=order,
            run=run,
            plan=plan,
            step=step,
            inputs=dict(execution.input_payload or {}),
            artifacts=artifacts,
            execution_attempt=execution.attempt,
            evaluation_feedback=evaluation_feedback or None,
            step_execution_id=execution.id,
            fence_token=claim.fence_token,
            runtime_binding_payload=dict(execution.runtime_binding_payload or {}),
        )
        registry = get_capability_registry()
        definition = registry.definition(execution.capability_key, execution.capability_version)
        if definition is None:
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                error_code="RUNTIME_VERSION_UNAVAILABLE",
                message=(
                    "Capability implementation is unavailable: "
                    f"{execution.capability_key}@{execution.capability_version}"
                ),
            )
        dispatcher = CapabilityDispatcher(registry)
        # Close context-loading transaction before remote or long-running work.
        await session.commit()
        try:
            outcome = await asyncio.wait_for(
                dispatcher.execute(context),
                timeout=definition.timeout_seconds,
            )
            # Durable handlers may have staged Workflow/Operation records.
            await session.commit()
            return outcome
        except TimeoutError:
            await session.rollback()
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                retryable=True,
                error_code="CAPABILITY_TIMEOUT",
                message="Capability execution timed out",
            )
        except CapabilityUnavailableError as exc:
            await session.rollback()
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                error_code="RUNTIME_VERSION_UNAVAILABLE",
                message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                error_code=type(exc).__name__[:128],
                message="Capability contract or execution failed",
            )


async def _heartbeat_claim(claim: AgentStepClaim) -> None:
    interval = max(1.0, settings.agent_step_lease_seconds / 3)
    while True:
        await asyncio.sleep(interval)
        if not await renew_agent_step_lease(claim):
            return


def _execution_event_payload(
    execution: AgentStepExecution,
    *,
    external_execution_id: str | None = None,
) -> dict[str, Any]:
    return {
        "agent_step_execution_id": execution.id,
        "step_key": execution.plan_step_key,
        "attempt": execution.attempt,
        "capability": execution.capability_key,
        "capability_version": execution.capability_version,
        "evaluator": execution.evaluator_key,
        "evaluator_version": execution.evaluator_version,
        "plan_version_id": execution.plan_version_id,
        "external_execution_id": external_execution_id,
    }


async def _create_rework_attempt(
    session,
    *,
    execution: AgentStepExecution,
    feedback: str,
    issues: list[dict[str, Any]],
    delay_seconds: int,
) -> AgentStepExecution:
    attempt = execution.attempt + 1
    available_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    replacement = AgentStepExecution(
        tenant_id=execution.tenant_id,
        production_order_id=execution.production_order_id,
        agent_run_id=execution.agent_run_id,
        plan_version_id=execution.plan_version_id,
        parent_execution_id=execution.id,
        plan_step_key=execution.plan_step_key,
        capability_key=execution.capability_key,
        capability_version=execution.capability_version,
        evaluator_key=execution.evaluator_key,
        evaluator_version=execution.evaluator_version,
        execution_kind=execution.execution_kind,
        attempt=attempt,
        max_attempts=execution.max_attempts,
        evaluation_max_attempts=execution.evaluation_max_attempts,
        status=AgentStepExecutionStatus.pending.value,
        idempotency_key=(
            f"agent-step:{execution.plan_version_id}:{execution.plan_step_key}:attempt:{attempt}"
        ),
        state_origin=execution.state_origin,
        input_payload=dict(execution.input_payload or {}),
        runtime_binding_payload={
            **dict(execution.runtime_binding_payload or {}),
            "evaluation_feedback": issues,
            "evaluation_feedback_text": feedback,
        },
        next_wakeup_at=available_at,
    )
    session.add(replacement)
    session.add(
        OutboxEvent(
            tenant_id=execution.tenant_id,
            aggregate_type="production_order",
            aggregate_id=execution.production_order_id,
            topic="agent.run.requested",
            payload={
                "production_order_id": execution.production_order_id,
                "agent_run_id": execution.agent_run_id,
            },
            dedupe_key=f"agent-step-rework:{replacement.id}",
            available_at=available_at,
        )
    )
    return replacement


async def _finalize_if_complete(
    session,
    *,
    order: ProductionOrder,
    run: AgentRun,
    plan: PlanVersion,
    plan_spec: AgentPlanSpec,
) -> bool:
    executions = list(
        await session.scalars(
            select(AgentStepExecution)
            .where(AgentStepExecution.plan_version_id == plan.id)
            .order_by(AgentStepExecution.attempt)
        )
    )
    latest: dict[str, AgentStepExecution] = {}
    for execution in executions:
        latest[execution.plan_step_key] = execution
    if not all(
        latest.get(step.key) is not None
        and latest[step.key].status == AgentStepExecutionStatus.succeeded.value
        for step in plan_spec.steps
    ):
        return False
    order.status = ProductionOrderStatus.succeeded
    run.status = AgentRunStatus.succeeded
    plan.status = PlanVersionStatus.completed
    run.stop_reason = "all_required_artifacts_created"
    run.finished_at = datetime.now(UTC)
    await _append_event(
        session,
        order=order,
        run=run,
        event_type="production_order.succeeded",
        payload={"plan_version_id": plan.id},
    )
    return True


async def _apply_outcome(claim: AgentStepClaim, outcome: CapabilityOutcome) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        execution = await execution_claim_is_current(session, claim, lock=True)
        if execution is None:
            return  # fenced stale result
        order = await session.get(ProductionOrder, execution.production_order_id)
        run = await session.get(AgentRun, execution.agent_run_id)
        plan = await session.get(PlanVersion, execution.plan_version_id)
        if order is None or run is None or plan is None:
            return
        if order.status in {ProductionOrderStatus.canceling, ProductionOrderStatus.canceled}:
            execution.status = AgentStepExecutionStatus.canceled.value
            execution.finished_at = now
            execution.fence_token += 1
            execution.lease_owner = None
            execution.lease_expires_at = None
            await session.commit()
            return
        if plan.status != PlanVersionStatus.active:
            execution.status = AgentStepExecutionStatus.superseded.value
            execution.finished_at = now
            execution.fence_token += 1
            execution.lease_owner = None
            execution.lease_expires_at = None
            await session.commit()
            return
        plan_spec = AgentPlanSpec.model_validate(plan.plan_payload)
        step = _step_for_execution(plan_spec, execution)
        resuming_evaluation = (
            execution.status == AgentStepExecutionStatus.evaluating.value
        )
        artifact_version = (
            await session.get(ArtifactVersion, execution.output_artifact_version_id)
            if execution.output_artifact_version_id
            else None
        )
        if not resuming_evaluation and outcome.artifact is not None:
            artifact_version = await _write_artifact(
                session,
                order=order,
                plan=plan,
                execution=execution,
                artifact_key=outcome.artifact.artifact_key,
                artifact_type=outcome.artifact.artifact_type,
                content_payload=outcome.artifact.content_payload,
                lineage_payload=outcome.artifact.lineage_payload,
                run=run,
            )
            execution.output_artifact_version_id = artifact_version.id

        if outcome.status == OutcomeStatus.succeeded:
            if not resuming_evaluation:
                execution.status = AgentStepExecutionStatus.evaluating.value
                execution.runtime_binding_payload = {
                    **dict(execution.runtime_binding_payload or {}),
                    "capability_outcome": outcome.model_dump(mode="json"),
                }
                order.status = ProductionOrderStatus.evaluating
                run.status = AgentRunStatus.evaluating
            # Persist the capability result, then release the Step row lock
            # before an evaluator is allowed to perform remote/model work.
            await session.commit()
            evaluator_error: EvaluatorUnavailableError | None = None
            evaluator_exception: Exception | None = None
            with session.no_autoflush:
                current_execution_id = await session.scalar(
                    select(AgentStepExecution.id)
                    .where(
                        AgentStepExecution.id == claim.execution_id,
                        AgentStepExecution.status
                        == AgentStepExecutionStatus.evaluating.value,
                        AgentStepExecution.lease_owner == claim.worker_id,
                        AgentStepExecution.fence_token == claim.fence_token,
                    )
                    .with_for_update()
                )
            if current_execution_id is None:
                await session.rollback()
                return
            execution.evaluation_attempt += 1
            evaluation_attempt = execution.evaluation_attempt
            await session.commit()
            try:
                evaluation = await evaluate_step(
                    session,
                    order=order,
                    run=run,
                    plan=plan,
                    step=step,
                    outcome=outcome,
                    artifact_version=artifact_version,
                )
            except EvaluatorUnavailableError as exc:
                evaluator_error = exc
            except Exception as exc:  # noqa: BLE001
                evaluator_exception = exc
            with session.no_autoflush:
                current_execution_id = await session.scalar(
                    select(AgentStepExecution.id)
                    .where(
                        AgentStepExecution.id == claim.execution_id,
                        AgentStepExecution.status
                        == AgentStepExecutionStatus.evaluating.value,
                        AgentStepExecution.lease_owner == claim.worker_id,
                        AgentStepExecution.fence_token == claim.fence_token,
                    )
                    .with_for_update()
                )
            if current_execution_id is None:
                await session.rollback()
                return
            now = datetime.now(UTC)
            if evaluator_error is not None:
                execution.status = AgentStepExecutionStatus.failed_final.value
                execution.error_code = "RUNTIME_VERSION_UNAVAILABLE"
                execution.error_message = str(evaluator_error)
                execution.finished_at = now
                order.status = ProductionOrderStatus.manual_intervention
                run.status = AgentRunStatus.failed
                run.stop_reason = "evaluator_unavailable"
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.step.evaluation_failed_final",
                    payload={
                        **_execution_event_payload(execution),
                        "error_code": execution.error_code,
                        "attempt": evaluation_attempt,
                    },
                )
            elif evaluator_exception is not None:
                execution.error_code = type(evaluator_exception).__name__[:128]
                execution.error_message = (
                    str(evaluator_exception)[:2000] or "Evaluator execution failed"
                )
                if evaluation_attempt < execution.evaluation_max_attempts:
                    delay = settings.evaluator_retry_base_seconds * (
                        2 ** max(0, evaluation_attempt - 1)
                    )
                    available_at = now + timedelta(seconds=delay)
                    execution.status = AgentStepExecutionStatus.evaluating.value
                    execution.next_wakeup_at = available_at
                    order.status = ProductionOrderStatus.evaluating
                    run.status = AgentRunStatus.evaluating
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
                            dedupe_key=(
                                f"agent-step-evaluation-retry:{execution.id}:"
                                f"{evaluation_attempt}"
                            ),
                            available_at=available_at,
                        )
                    )
                    await _append_event(
                        session,
                        order=order,
                        run=run,
                        event_type="agent.step.evaluation_retry_scheduled",
                        payload={
                            **_execution_event_payload(execution),
                            "error_code": execution.error_code,
                            "attempt": evaluation_attempt,
                            "next_wakeup_at": available_at.isoformat(),
                        },
                    )
                else:
                    execution.status = AgentStepExecutionStatus.failed_final.value
                    execution.finished_at = now
                    order.status = ProductionOrderStatus.manual_intervention
                    run.status = AgentRunStatus.failed
                    run.stop_reason = "evaluator_attempts_exhausted"
                    await _append_event(
                        session,
                        order=order,
                        run=run,
                        event_type="agent.step.evaluation_failed_final",
                        payload={
                            **_execution_event_payload(execution),
                            "error_code": execution.error_code,
                            "attempt": evaluation_attempt,
                        },
                    )
            else:
                execution.error_code = None
                execution.error_message = None
                execution.next_wakeup_at = None
                if evaluation.artifact_version is not None:
                    execution.output_artifact_version_id = evaluation.artifact_version.id
                if evaluation.record is not None:
                    execution.quality_evaluation_id = evaluation.record.id
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.step.evaluated",
                    payload={
                        **_execution_event_payload(execution),
                        "evaluation_id": evaluation.record.id if evaluation.record else None,
                        "artifact_version_id": (
                            evaluation.artifact_version.id if evaluation.artifact_version else None
                        ),
                        "passed": evaluation.result.passed,
                        "action": evaluation.result.action.value,
                        "score": evaluation.result.score_payload,
                        "issues": evaluation.result.issues,
                    },
                )
                if evaluation.result.passed:
                    execution.status = AgentStepExecutionStatus.succeeded.value
                    execution.finished_at = now
                    order.status = ProductionOrderStatus.running
                    run.status = AgentRunStatus.running
                    await _append_event(
                        session,
                        order=order,
                        run=run,
                        event_type="agent.step.succeeded",
                        payload=_execution_event_payload(
                            execution,
                            external_execution_id=outcome.external_execution_id,
                        ),
                    )
                else:
                    if evaluation.artifact_version is not None:
                        evaluation.artifact_version.status = ArtifactVersionStatus.returned
                    exhausted = (
                        execution.attempt >= execution.max_attempts
                        or order.auto_rework_count >= order.max_auto_rework
                    )
                    if evaluation.result.action == EvaluationAction.manual or exhausted:
                        execution.status = AgentStepExecutionStatus.failed_final.value
                        execution.error_code = "QUALITY_GATE_FAILED"
                        execution.error_message = evaluation.result.feedback
                        execution.finished_at = now
                        order.status = ProductionOrderStatus.manual_intervention
                        run.status = AgentRunStatus.failed
                        run.stop_reason = "quality_gate_failed"
                        await _append_event(
                            session,
                            order=order,
                            run=run,
                            event_type="agent.quality.manual_intervention",
                            payload={
                                **_execution_event_payload(execution),
                                "issues": evaluation.result.issues,
                            },
                        )
                    elif evaluation.result.action == EvaluationAction.replan:
                        execution.status = AgentStepExecutionStatus.rework_requested.value
                        execution.finished_at = now
                        order.auto_rework_count += 1
                        order.status = ProductionOrderStatus.planning
                        run.status = AgentRunStatus.planning
                        await stage_planning_operation(
                            session,
                            order=order,
                            run=run,
                            idempotency_key=(
                                f"plan:{run.id}:evaluation:"
                                f"{evaluation.record.id if evaluation.record else execution.id}"
                            ),
                            reason="quality_replan",
                            planning_context={
                                "agent_step_execution_id": execution.id,
                                "previous_plan_version_id": plan.id,
                                "issues": evaluation.result.issues,
                            },
                        )
                        await _append_event(
                            session,
                            order=order,
                            run=run,
                            event_type="agent.step.replan_requested",
                            payload={
                                **_execution_event_payload(execution),
                                "issues": evaluation.result.issues,
                            },
                        )
                    else:
                        execution.status = AgentStepExecutionStatus.rework_requested.value
                        execution.finished_at = now
                        order.auto_rework_count += 1
                        order.status = ProductionOrderStatus.retry_wait
                        run.status = AgentRunStatus.running
                        await _create_rework_attempt(
                            session,
                            execution=execution,
                            feedback=evaluation.result.feedback,
                            issues=evaluation.result.issues,
                            delay_seconds=step.retry_backoff_seconds,
                        )
                        await _append_event(
                            session,
                            order=order,
                            run=run,
                            event_type="agent.step.rework_requested",
                            payload={
                                **_execution_event_payload(execution),
                                "issues": evaluation.result.issues,
                            },
                        )

        elif outcome.status in {OutcomeStatus.dispatched, OutcomeStatus.waiting}:
            execution.status = AgentStepExecutionStatus.waiting.value
            execution.external_execution_id = outcome.external_execution_id
            execution.external_execution_type = (
                "workflow"
                if execution.execution_kind == "durable"
                else "agent_operation"
                if execution.execution_kind == "external"
                else "capability"
            )
            execution.next_wakeup_at = now + timedelta(
                seconds=settings.runtime_recovery_interval_seconds
            )
            order.status = ProductionOrderStatus.running
            run.status = AgentRunStatus.running
            if outcome.status == OutcomeStatus.dispatched:
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.step.dispatched",
                    payload=_execution_event_payload(
                        execution,
                        external_execution_id=outcome.external_execution_id,
                    ),
                )

        elif outcome.status == OutcomeStatus.awaiting_decision:
            decision_spec = outcome.decision
            if decision_spec is None:
                raise RuntimeError("awaiting_decision outcome is missing DecisionSpec")
            prior_decision = (
                await session.get(DecisionRequest, execution.decision_request_id)
                if execution.decision_request_id
                else None
            )
            if (
                prior_decision is not None
                and prior_decision.reason_code == decision_spec.reason_code
            ):
                if prior_decision.status == DecisionStatus.pending:
                    execution.status = AgentStepExecutionStatus.awaiting_decision.value
                    order.status = ProductionOrderStatus.awaiting_decision
                    run.status = AgentRunStatus.awaiting_decision
                else:
                    execution.status = AgentStepExecutionStatus.failed_final.value
                    execution.error_code = "DECISION_RESOLUTION_NOT_APPLIED"
                    execution.error_message = (
                        "Capability requested the same decision after it was resolved"
                    )
                    execution.finished_at = now
                    order.status = ProductionOrderStatus.manual_intervention
                    run.status = AgentRunStatus.failed
                    run.stop_reason = "decision_resolution_not_applied"
                    await _append_event(
                        session,
                        order=order,
                        run=run,
                        event_type="agent.step.failed_final",
                        payload={
                            **_execution_event_payload(execution),
                            "error_code": execution.error_code,
                            "decision_id": prior_decision.id,
                        },
                    )
                execution.lease_owner = None
                execution.lease_expires_at = None
                execution.heartbeat_at = None
                await session.commit()
                return
            decision = DecisionRequest(
                tenant_id=order.tenant_id,
                production_order_id=order.id,
                agent_run_id=run.id,
                plan_version_id=plan.id,
                scope="step",
                reason_code=decision_spec.reason_code,
                title=decision_spec.title,
                summary=decision_spec.summary,
                options=decision_spec.options,
                recommended_option=decision_spec.recommended_option,
                blocking=decision_spec.blocking,
            )
            session.add(decision)
            await session.flush()
            execution.decision_request_id = decision.id
            execution.status = AgentStepExecutionStatus.awaiting_decision.value
            order.status = ProductionOrderStatus.awaiting_decision
            run.status = AgentRunStatus.awaiting_decision
            await _append_event(
                session,
                order=order,
                run=run,
                event_type="decision.requested",
                payload={**_execution_event_payload(execution), "decision_id": decision.id},
            )

        elif outcome.status == OutcomeStatus.failed:
            execution.error_code = outcome.error_code or "CAPABILITY_EXECUTION_FAILED"
            execution.error_message = outcome.message
            if outcome.retryable and execution.attempt < execution.max_attempts:
                delay = step.retry_backoff_seconds * (2 ** max(0, execution.attempt - 1))
                available_at = now + timedelta(seconds=delay)
                execution.status = AgentStepExecutionStatus.retry_wait.value
                execution.next_wakeup_at = available_at
                order.status = ProductionOrderStatus.retry_wait
                run.status = AgentRunStatus.running
                session.add(
                    OutboxEvent(
                        tenant_id=order.tenant_id,
                        aggregate_type="production_order",
                        aggregate_id=order.id,
                        topic="agent.run.requested",
                        payload={"production_order_id": order.id, "agent_run_id": run.id},
                        dedupe_key=f"agent-step-retry:{execution.id}",
                        available_at=available_at,
                    )
                )
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.step.retry_scheduled",
                    payload={
                        **_execution_event_payload(execution),
                        "next_wakeup_at": available_at.isoformat(),
                        "error_code": execution.error_code,
                    },
                )
            else:
                execution.status = AgentStepExecutionStatus.failed_final.value
                execution.finished_at = now
                order.status = ProductionOrderStatus.manual_intervention
                run.status = AgentRunStatus.failed
                run.stop_reason = "capability_execution_failed"
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.step.failed_final",
                    payload={
                        **_execution_event_payload(execution),
                        "error_code": execution.error_code,
                        "message": execution.error_message,
                    },
                )

        execution.lease_owner = None
        execution.lease_expires_at = None
        execution.heartbeat_at = None
        if execution.status == AgentStepExecutionStatus.succeeded.value:
            await _finalize_if_complete(
                session,
                order=order,
                run=run,
                plan=plan,
                plan_spec=plan_spec,
            )
        await session.commit()


async def _execute_and_apply(claim: AgentStepClaim) -> None:
    heartbeat = asyncio.create_task(_heartbeat_claim(claim))
    try:
        outcome = await _execute_claim(claim)
        await _apply_outcome(claim, outcome)
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


async def _cancel_order(production_order_id: str, agent_run_id: str | None) -> None:
    interrupt_targets: list[tuple[AgentStepExecution, Any, ProductionOrder, AgentRun, PlanVersion]] = []
    async with SessionLocal() as session:
        order = await session.scalar(
            select(ProductionOrder)
            .where(ProductionOrder.id == production_order_id)
            .with_for_update()
        )
        if order is None or order.status != ProductionOrderStatus.canceling:
            return
        run_query = select(AgentRun).where(AgentRun.production_order_id == order.id)
        if agent_run_id:
            run_query = run_query.where(AgentRun.id == agent_run_id)
        run = await session.scalar(run_query.order_by(AgentRun.run_number.desc()).limit(1))
        if run is None:
            return
        now = datetime.now(UTC)
        executions = list(
            await session.scalars(
                select(AgentStepExecution).where(
                    AgentStepExecution.production_order_id == order.id,
                    AgentStepExecution.status.not_in(TERMINAL_STEP_STATUSES),
                )
            )
        )
        plan_cache: dict[str, tuple[PlanVersion, dict[str, Any]]] = {}
        for execution in executions:
            if execution.plan_version_id not in plan_cache:
                plan = await session.get(PlanVersion, execution.plan_version_id)
                if plan is not None:
                    spec = AgentPlanSpec.model_validate(plan.plan_payload)
                    plan_cache[plan.id] = (
                        plan,
                        {step.key: step for step in spec.steps},
                    )
            plan_context = plan_cache.get(execution.plan_version_id)
            if plan_context is not None and execution.external_execution_id:
                plan, by_key = plan_context
                step = by_key.get(execution.plan_step_key)
                if step is not None:
                    interrupt_targets.append((execution, step, order, run, plan))
            execution.status = AgentStepExecutionStatus.canceled.value
            execution.finished_at = now
            execution.fence_token += 1
            execution.lease_owner = None
            execution.lease_expires_at = None
            execution.heartbeat_at = None
            execution.next_wakeup_at = None
        operations = list(
            await session.scalars(
                select(AgentOperation).where(
                    AgentOperation.production_order_id == order.id,
                    AgentOperation.status.not_in(
                        [
                            AgentOperationStatus.succeeded.value,
                            AgentOperationStatus.failed_final.value,
                            AgentOperationStatus.canceled.value,
                        ]
                    ),
                )
            )
        )
        for operation in operations:
            operation.status = AgentOperationStatus.canceled.value
            operation.finished_at = now
            operation.fence_token += 1
            operation.lease_owner = None
            operation.lease_expires_at = None
            operation.heartbeat_at = None
            operation.next_wakeup_at = None
        decisions = list(
            await session.scalars(
                select(DecisionRequest).where(
                    DecisionRequest.production_order_id == order.id,
                    DecisionRequest.status == DecisionStatus.pending,
                )
            )
        )
        for decision in decisions:
            decision.status = DecisionStatus.canceled
            decision.resolved_at = now
            decision.resolution_payload = {"reason": "production_order_canceled"}
        order.status = ProductionOrderStatus.canceled
        run.status = AgentRunStatus.canceled
        run.stop_reason = "user_canceled"
        run.finished_at = now
        await _append_event(
            session,
            order=order,
            run=run,
            event_type="production_order.canceled",
            payload={
                "canceled_step_count": len(executions),
                "canceled_operation_count": len(operations),
                "canceled_decision_count": len(decisions),
            },
        )
        await session.commit()

    registry = get_capability_registry()
    dispatcher = CapabilityDispatcher(registry)
    for execution, step, order, run, plan in interrupt_targets:
        async with SessionLocal() as session:
            context = CapabilityContext(
                session=session,
                order=order,
                run=run,
                plan=plan,
                step=step.model_copy(
                    update={
                        "capability_version": execution.capability_version,
                        "evaluator_version": execution.evaluator_version,
                    }
                ),
                inputs=dict(execution.input_payload or {}),
                step_execution_id=execution.id,
            )
            with suppress(Exception):
                await dispatcher.interrupt(context, execution.external_execution_id)
                await session.commit()


async def run_agent_once(
    production_order_id: str,
    agent_run_id: str | None = None,
    *,
    worker_id: str | None = None,
) -> None:
    resolved_worker_id = worker_id or agent_worker_id
    async with SessionLocal() as session:
        status = await session.scalar(
            select(ProductionOrder.status).where(ProductionOrder.id == production_order_id)
        )
    if status == ProductionOrderStatus.canceling:
        await _cancel_order(production_order_id, agent_run_id)
        return
    if status not in {
        ProductionOrderStatus.queued,
        ProductionOrderStatus.running,
        ProductionOrderStatus.retry_wait,
        ProductionOrderStatus.evaluating,
    }:
        return

    # Each wave is a ready set. Independent nodes execute concurrently while
    # every claim remains durable and independently fenced.
    first_wave = True
    while True:
        claims = await claim_ready_agent_steps(
            production_order_id,
            agent_run_id=agent_run_id,
            worker_id=resolved_worker_id,
            observe_waiting=first_wave,
        )
        first_wave = False
        if not claims:
            return
        await asyncio.gather(*(_execute_and_apply(claim) for claim in claims))
