import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agent.contracts import AgentPlanSpec, OutcomeStatus
from app.capabilities.base import CapabilityContext
from app.capabilities.registry import get_capability_registry
from app.core.database import SessionLocal
from app.models.agent import (
    AgentEvent,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVersion,
    ArtifactVersionStatus,
    DecisionRequest,
    PlanVersion,
    PlanVersionStatus,
    ProductionOrder,
    ProductionOrderStatus,
)
from app.services.agent_service import next_artifact_version


async def _event_exists(
    session,
    run_id: str,
    event_type: str,
    step_key: str,
    plan_version_id: str,
) -> bool:
    events = await session.scalars(
        select(AgentEvent.payload).where(
            AgentEvent.agent_run_id == run_id,
            AgentEvent.event_type == event_type,
        )
    )
    return any(
        payload.get("step_key") == step_key
        and payload.get("plan_version_id") == plan_version_id
        for payload in events
    )


async def _append_event(
    session,
    *,
    order: ProductionOrder,
    run: AgentRun,
    event_type: str,
    payload: dict[str, Any],
) -> None:
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
    artifact_key: str,
    artifact_type: str,
    content_payload: dict[str, Any],
    lineage_payload: dict[str, Any],
    run: AgentRun,
) -> ArtifactVersion:
    artifact = await session.scalar(
        select(Artifact).where(
            Artifact.production_order_id == order.id,
            Artifact.artifact_key == artifact_key,
        )
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
    version_number = await next_artifact_version(session, artifact.id)
    checksum = hashlib.sha256(
        json.dumps(content_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    version = ArtifactVersion(
        tenant_id=order.tenant_id,
        artifact_id=artifact.id,
        plan_version_id=plan.id,
        version=version_number,
        status=ArtifactVersionStatus.candidate,
        content_payload=content_payload,
        lineage_payload=lineage_payload,
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
            "version": version_number,
        },
    )
    return version


async def run_agent_once(production_order_id: str, agent_run_id: str | None = None) -> None:
    async with SessionLocal() as session:
        order = await session.scalar(
            select(ProductionOrder)
            .where(ProductionOrder.id == production_order_id)
            .with_for_update()
        )
        if order is None or order.status in {
            ProductionOrderStatus.paused,
            ProductionOrderStatus.canceled,
            ProductionOrderStatus.succeeded,
            ProductionOrderStatus.failed_final,
        }:
            return
        run_query = select(AgentRun).where(AgentRun.production_order_id == order.id)
        if agent_run_id:
            run_query = run_query.where(AgentRun.id == agent_run_id)
        run = await session.scalar(run_query.order_by(AgentRun.run_number.desc()).limit(1))
        if run is None:
            raise RuntimeError("生产单缺少 AgentRun")

        plan = await session.scalar(
            select(PlanVersion)
            .where(PlanVersion.agent_run_id == run.id)
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        if plan is None:
            raise RuntimeError("AgentRun 缺少 PlanVersion")
        try:
            plan_spec = AgentPlanSpec.model_validate(plan.plan_payload)
        except ValueError as exc:
            order.status = ProductionOrderStatus.manual_intervention
            run.status = AgentRunStatus.failed
            run.stop_reason = "invalid_plan_contract"
            await _append_event(
                session,
                order=order,
                run=run,
                event_type="agent.plan.invalid",
                payload={
                    "plan_version_id": plan.id,
                    "error_type": type(exc).__name__,
                },
            )
            await session.commit()
            return

        registry = get_capability_registry()
        raw_inputs = (run.context_snapshot or {}).get("inputs") or {}
        inputs = raw_inputs if isinstance(raw_inputs, dict) else {}

        if order.status == ProductionOrderStatus.canceling:
            dispatched_events = list(
                (
                    await session.execute(
                        select(AgentEvent.payload).where(
                            AgentEvent.agent_run_id == run.id,
                            AgentEvent.event_type == "agent.step.dispatched",
                        )
                    )
                ).scalars()
            )
            steps_by_key = {step.key: step for step in plan_spec.steps}
            for event_payload in dispatched_events:
                if event_payload.get("plan_version_id") != plan.id:
                    continue
                step = steps_by_key.get(str(event_payload.get("step_key") or ""))
                handler = registry.handler(step.capability) if step else None
                if step is None or handler is None:
                    continue
                context = CapabilityContext(
                    session=session,
                    order=order,
                    run=run,
                    plan=plan,
                    step=step,
                    inputs=inputs,
                )
                await handler.interrupt(
                    context,
                    str(event_payload.get("external_execution_id") or "") or None,
                )
            order.status = ProductionOrderStatus.canceled
            run.status = AgentRunStatus.canceled
            run.stop_reason = "user_canceled"
            run.finished_at = datetime.now(UTC)
            await _append_event(
                session,
                order=order,
                run=run,
                event_type="production_order.canceled",
                payload={},
            )
            await session.commit()
            return

        order.status = ProductionOrderStatus.running
        run.status = AgentRunStatus.running
        await session.flush()

        completed_events = list(
            (
                await session.execute(
                    select(AgentEvent.payload).where(
                        AgentEvent.agent_run_id == run.id,
                        AgentEvent.event_type == "agent.step.succeeded",
                    )
                )
            ).scalars()
        )
        completed = {
            str(item.get("step_key"))
            for item in completed_events
            if item.get("plan_version_id") == plan.id
        }

        for step in plan_spec.steps:
            step_key = step.key
            if step_key in completed:
                continue
            dependencies = set(step.depends_on)
            if not dependencies.issubset(completed):
                continue
            definition = registry.definition(step.capability)
            handler = registry.handler(step.capability)
            if definition is None or handler is None:
                order.status = ProductionOrderStatus.manual_intervention
                run.status = AgentRunStatus.failed
                run.stop_reason = "capability_unavailable"
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.capability.unavailable",
                    payload={
                        "step_key": step_key,
                        "capability": step.capability,
                        "capability_version": definition.version if definition else None,
                        "plan_version_id": plan.id,
                    },
                )
                await session.commit()
                return

            context = CapabilityContext(
                session=session,
                order=order,
                run=run,
                plan=plan,
                step=step,
                inputs=inputs,
            )
            try:
                outcome = await handler.execute(context)
            except Exception as exc:
                order.status = ProductionOrderStatus.manual_intervention
                run.status = AgentRunStatus.failed
                run.stop_reason = "capability_contract_error"
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.capability.failed",
                    payload={
                        "step_key": step_key,
                        "capability": step.capability,
                        "plan_version_id": plan.id,
                        "error_type": type(exc).__name__,
                    },
                )
                await session.commit()
                return

            if outcome.artifact is not None:
                artifact = outcome.artifact
                await _write_artifact(
                    session,
                    order=order,
                    plan=plan,
                    artifact_key=artifact.artifact_key,
                    artifact_type=artifact.artifact_type,
                    content_payload=artifact.content_payload,
                    lineage_payload=artifact.lineage_payload,
                    run=run,
                )

            if outcome.status == OutcomeStatus.succeeded:
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.step.succeeded",
                    payload={
                        "step_key": step_key,
                        "capability": step.capability,
                        "capability_version": definition.version,
                        "plan_version_id": plan.id,
                        "external_execution_id": outcome.external_execution_id,
                    },
                )
                completed.add(step_key)
                continue

            if outcome.status == OutcomeStatus.dispatched:
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.step.dispatched",
                    payload={
                        "step_key": step_key,
                        "capability": step.capability,
                        "capability_version": definition.version,
                        "plan_version_id": plan.id,
                        "external_execution_id": outcome.external_execution_id,
                    },
                )
                await session.commit()
                return

            if outcome.status == OutcomeStatus.waiting:
                await session.commit()
                return

            if outcome.status == OutcomeStatus.awaiting_decision:
                order.status = ProductionOrderStatus.awaiting_decision
                run.status = AgentRunStatus.awaiting_decision
                if not await _event_exists(
                    session,
                    run.id,
                    "decision.requested",
                    step_key,
                    plan.id,
                ):
                    decision_spec = outcome.decision
                    if decision_spec is None:
                        raise RuntimeError("能力返回了无决策内容的 awaiting_decision")
                    decision = DecisionRequest(
                        tenant_id=order.tenant_id,
                        production_order_id=order.id,
                        agent_run_id=run.id,
                        plan_version_id=plan.id,
                        reason_code=decision_spec.reason_code,
                        title=decision_spec.title,
                        summary=decision_spec.summary,
                        options=decision_spec.options,
                        recommended_option=decision_spec.recommended_option,
                        blocking=decision_spec.blocking,
                    )
                    session.add(decision)
                    await session.flush()
                    await _append_event(
                        session,
                        order=order,
                        run=run,
                        event_type="decision.requested",
                        payload={
                            "decision_id": decision.id,
                            "step_key": step_key,
                            "capability": step.capability,
                            "plan_version_id": plan.id,
                        },
                    )
                await session.commit()
                return

            if outcome.status == OutcomeStatus.failed:
                order.status = (
                    ProductionOrderStatus.failed_retryable
                    if outcome.retryable
                    else ProductionOrderStatus.manual_intervention
                )
                run.status = AgentRunStatus.failed
                run.stop_reason = "capability_execution_failed"
                await _append_event(
                    session,
                    order=order,
                    run=run,
                    event_type="agent.tool.failed",
                    payload={
                        "step_key": step_key,
                        "capability": step.capability,
                        "plan_version_id": plan.id,
                        "external_execution_id": outcome.external_execution_id,
                        "error_code": outcome.error_code,
                        "message": outcome.message,
                        "retryable": outcome.retryable,
                    },
                )
                await session.commit()
                return

        required_keys = {step.key for step in plan_spec.steps}
        if required_keys.issubset(completed):
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
                payload={},
            )
        await session.commit()
