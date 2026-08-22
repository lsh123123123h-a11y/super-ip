import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.agent.contracts import (
    AgentPlanSpec,
    ArtifactDraft,
    CapabilityDefinition,
    CapabilityOutcome,
    DecisionSpec,
    ExecutionKind,
    OutcomeStatus,
)
from app.agent.evaluation import EvaluationAction, EvaluationResult, EvaluatorDefinition
from app.capabilities.registry import get_capability_registry
from app.core.database import SessionLocal
from app.core.principal import Principal
from app.evaluators.registry import get_evaluator_registry
from app.models.agent import (
    AgentEvent,
    AgentOperation,
    AgentStepExecution,
    AgentStepExecutionStatus,
    Artifact,
    ConsumedEvent,
    DecisionRequest,
    DecisionStatus,
    OutboxEvent,
    PlanVersion,
    ProductionOrder,
    ProductionOrderStatus,
)
from app.schemas.agent import ProductionOrderCreate, ResolveDecisionRequest
from app.services.agent_operation_service import run_agent_operation_once
from app.services.agent_runtime import _apply_outcome, _execute_and_apply, run_agent_once
from app.services.agent_service import (
    command_production_order,
    create_production_order,
    create_project,
    resolve_decision,
)
from app.services.agent_step_service import claim_ready_agent_steps
from app.services.identity_service import ensure_principal_records
from app import worker as worker_module


pytestmark = [
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="需要迁移后的隔离 PostgreSQL 测试库",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


class DecisionResumeCapability:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, context):
        self.calls += 1
        resolution = context.runtime_binding_payload.get("decision_resolution")
        if not resolution:
            return CapabilityOutcome(
                status=OutcomeStatus.awaiting_decision,
                decision=DecisionSpec(
                    reason_code="TEST_STEP_DECISION",
                    title="确认继续",
                    options=[{"key": "continue", "label": "继续"}],
                ),
            )
        return CapabilityOutcome(
            status=OutcomeStatus.succeeded,
            artifact=ArtifactDraft(
                artifact_key="intent_spec",
                artifact_type="intent_spec",
                content_payload={"decision": resolution},
            ),
        )

    async def interrupt(self, context, external_execution_id):
        return None


class SuccessfulCapability:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, context):
        self.calls += 1
        return CapabilityOutcome(
            status=OutcomeStatus.succeeded,
            artifact=ArtifactDraft(
                artifact_key="intent_spec",
                artifact_type="intent_spec",
                content_payload={"ok": True},
            ),
        )

    async def interrupt(self, context, external_execution_id):
        return None


class InterruptFailureCapability:
    def __init__(self) -> None:
        self.interrupt_calls = 0

    async def execute(self, context):
        return CapabilityOutcome(
            status=OutcomeStatus.waiting,
            external_execution_id=f"test-external-{context.step_execution_id}",
        )

    async def interrupt(self, context, external_execution_id):
        self.interrupt_calls += 1
        persisted = await context.session.get(ProductionOrder, context.order.id)
        assert persisted.status == ProductionOrderStatus.canceled
        raise RuntimeError("simulated interrupt failure")


class PassEvaluator:
    async def evaluate(self, context):
        return EvaluationResult(passed=True, action=EvaluationAction.accept)


class FlakyEvaluator:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def evaluate(self, context):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("transient evaluator failure")
        return EvaluationResult(passed=True, action=EvaluationAction.accept)


class BlockingFirstEvaluator:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def evaluate(self, context):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            await self.release.wait()
        return EvaluationResult(passed=True, action=EvaluationAction.accept)


async def _single_step_runtime(
    *,
    principal: Principal,
    suffix: str,
    capability,
    evaluator,
) -> tuple[str, str, str]:
    capability_key = f"test.seal.capability.{suffix}"
    evaluator_key = f"test.seal.evaluator.{suffix}"
    get_capability_registry().register(
        CapabilityDefinition(
            key=capability_key,
            version="1.0.0",
            label="Runtime seal test capability",
            execution_kind=ExecutionKind.inline,
        ),
        capability,
        source="integration-test",
    )
    get_evaluator_registry().register(
        EvaluatorDefinition(
            key=evaluator_key,
            version="1.0.0",
            label="Runtime seal test evaluator",
        ),
        evaluator,
        source="integration-test",
    )
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name=f"Runtime Seal {suffix}",
            goal="runtime seal integration",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key=f"runtime-seal-{suffix}",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="runtime seal integration",
                automation_mode="automatic",
                inputs={
                    "script": "runtime seal",
                    "audio_path": "/code/data/seal.wav",
                    "avatar_video_path": "/code/data/seal.mp4",
                },
            ),
        )
        operation = await session.scalar(
            select(AgentOperation).where(
                AgentOperation.agent_run_id == overview.agent_run.id
            )
        )
        operation_id = operation.id
        order_id = overview.order.id
        run_id = overview.agent_run.id

    await run_agent_operation_once(operation_id, f"planning-{suffix}")
    async with SessionLocal() as session:
        plan = await session.scalar(
            select(PlanVersion).where(PlanVersion.agent_run_id == run_id)
        )
        executions = list(
            await session.scalars(
                select(AgentStepExecution)
                .where(AgentStepExecution.plan_version_id == plan.id)
                .order_by(AgentStepExecution.created_at)
            )
        )
        execution = executions[0]
        original = AgentPlanSpec.model_validate(plan.plan_payload)
        step = original.steps[0].model_copy(
            update={
                "capability": capability_key,
                "capability_version": "1.0.0",
                "evaluator": evaluator_key,
                "evaluator_version": "1.0.0",
                "depends_on": [],
                "expected_artifact": "intent_spec",
            }
        )
        plan.plan_payload = AgentPlanSpec(
            goal=original.goal,
            steps=[step],
            max_auto_rework=original.max_auto_rework,
            planner=original.planner,
        ).model_dump(mode="json")
        await session.execute(
            delete(AgentStepExecution).where(
                AgentStepExecution.plan_version_id == plan.id,
                AgentStepExecution.id != execution.id,
            )
        )
        execution.plan_step_key = step.key
        execution.capability_key = capability_key
        execution.capability_version = "1.0.0"
        execution.evaluator_key = evaluator_key
        execution.evaluator_version = "1.0.0"
        await session.commit()
        return order_id, run_id, execution.id


async def _create_outbox_envelope(topic: str, schema_version: int = 1):
    async with SessionLocal() as session:
        await ensure_principal_records(
            session,
            Principal(tenant_id="consumer-seal-tenant", user_id="consumer-seal-user"),
        )
        event = OutboxEvent(
            tenant_id="consumer-seal-tenant",
            aggregate_type="production_order",
            aggregate_id=str(uuid.uuid4()),
            topic=topic,
            payload={"production_order_id": str(uuid.uuid4())},
            schema_version=schema_version,
            dedupe_key=f"consumer-seal:{uuid.uuid4()}",
            published_at=datetime.now(UTC),
        )
        session.add(event)
        await session.commit()
        return worker_module._outbox_envelope(event)


async def test_step_decision_resumes_same_attempt_durably() -> None:
    suffix = uuid.uuid4().hex[:8]
    principal = Principal(
        tenant_id=f"decision-seal-tenant-{suffix}",
        user_id=f"decision-seal-user-{suffix}",
    )
    capability = DecisionResumeCapability()
    order_id, run_id, execution_id = await _single_step_runtime(
        principal=principal,
        suffix=suffix,
        capability=capability,
        evaluator=PassEvaluator(),
    )

    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        decision = await session.get(DecisionRequest, execution.decision_request_id)
        decision_id = decision.id
        assert execution.status == AgentStepExecutionStatus.awaiting_decision.value
        assert decision.scope == "step"

    async with SessionLocal() as session:
        with pytest.raises(LookupError):
            await resolve_decision(
                session,
                principal=Principal(tenant_id="wrong-tenant", user_id="wrong-user"),
                decision_id=decision_id,
                payload=ResolveDecisionRequest(option_key="continue"),
            )
        await session.rollback()

    async with SessionLocal() as session:
        await resolve_decision(
            session,
            principal=principal,
            decision_id=decision_id,
            payload=ResolveDecisionRequest(
                option_key="continue", payload={"confirmed": True}
            ),
        )
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        assert execution.status == AgentStepExecutionStatus.pending.value
        assert execution.attempt == 1
        assert execution.runtime_binding_payload["decision_resolution"][
            "decision_id"
        ] == decision_id

    async with SessionLocal() as session:
        with pytest.raises(ValueError, match="已经处理"):
            await resolve_decision(
                session,
                principal=principal,
                decision_id=decision_id,
                payload=ResolveDecisionRequest(option_key="continue"),
            )
        await session.rollback()

    await run_agent_once(order_id, run_id, worker_id="decision-resume-worker")
    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        executions = list(
            await session.scalars(
                select(AgentStepExecution).where(
                    AgentStepExecution.production_order_id == order_id
                )
            )
        )
        decisions = list(
            await session.scalars(
                select(DecisionRequest).where(
                    DecisionRequest.production_order_id == order_id
                )
            )
        )
    assert order.status == ProductionOrderStatus.succeeded
    assert [(item.id, item.attempt) for item in executions] == [(execution_id, 1)]
    assert len(decisions) == 1
    assert capability.calls == 2


async def test_legacy_active_plan_without_steps_requires_manual_intervention() -> None:
    suffix = uuid.uuid4().hex[:8]
    principal = Principal(
        tenant_id=f"legacy-seal-tenant-{suffix}",
        user_id=f"legacy-seal-user-{suffix}",
    )
    capability = SuccessfulCapability()
    order_id, run_id, _ = await _single_step_runtime(
        principal=principal,
        suffix=suffix,
        capability=capability,
        evaluator=PassEvaluator(),
    )
    async with SessionLocal() as session:
        await session.execute(
            delete(AgentStepExecution).where(
                AgentStepExecution.production_order_id == order_id
            )
        )
        await session.commit()

    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        artifacts = list(
            await session.scalars(
                select(Artifact).where(Artifact.production_order_id == order_id)
            )
        )
        event = await session.scalar(
            select(AgentEvent).where(
                AgentEvent.production_order_id == order_id,
                AgentEvent.event_type == "agent.runtime.manual_intervention",
            )
        )
    assert order.status == ProductionOrderStatus.manual_intervention
    assert event.payload["error_code"] == "LEGACY_RUNTIME_STATE_UNSAFE_TO_RECONCILE"
    assert artifacts == []
    assert capability.calls == 0


async def test_cancel_fences_every_nonterminal_step_and_decision() -> None:
    suffix = uuid.uuid4().hex[:8]
    principal = Principal(
        tenant_id=f"cancel-seal-tenant-{suffix}",
        user_id=f"cancel-seal-user-{suffix}",
    )
    order_id, run_id, execution_id = await _single_step_runtime(
        principal=principal,
        suffix=suffix,
        capability=SuccessfulCapability(),
        evaluator=PassEvaluator(),
    )
    stale_claim = (
        await claim_ready_agent_steps(
            order_id,
            agent_run_id=run_id,
            worker_id="stale-cancel-worker",
            limit=1,
        )
    )[0]
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        decision = DecisionRequest(
            tenant_id=principal.tenant_id,
            production_order_id=order_id,
            agent_run_id=run_id,
            plan_version_id=execution.plan_version_id,
            reason_code="CANCEL_TEST",
            title="Cancel test",
            options=[{"key": "continue", "label": "Continue"}],
        )
        session.add(decision)
        await session.flush()
        execution.decision_request_id = decision.id
        execution.status = AgentStepExecutionStatus.awaiting_decision.value
        statuses = [
            AgentStepExecutionStatus.pending.value,
            AgentStepExecutionStatus.running.value,
            AgentStepExecutionStatus.waiting.value,
            AgentStepExecutionStatus.retry_wait.value,
            AgentStepExecutionStatus.evaluating.value,
            AgentStepExecutionStatus.rework_requested.value,
        ]
        for index, status in enumerate(statuses, start=1):
            session.add(
                AgentStepExecution(
                    tenant_id=principal.tenant_id,
                    production_order_id=order_id,
                    agent_run_id=run_id,
                    plan_version_id=execution.plan_version_id,
                    plan_step_key=f"cancel.synthetic.{index}",
                    capability_key=execution.capability_key,
                    capability_version=execution.capability_version,
                    evaluator_key=execution.evaluator_key,
                    evaluator_version=execution.evaluator_version,
                    attempt=1,
                    status=status,
                    idempotency_key=f"cancel-seal:{suffix}:{index}",
                    lease_owner="old-worker",
                    lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    heartbeat_at=datetime.now(UTC),
                    next_wakeup_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
        await session.commit()

    async with SessionLocal() as session:
        result = await command_production_order(
            session,
            principal=principal,
            order_id=order_id,
            command="cancel",
        )
        assert result.order.status == ProductionOrderStatus.canceling
    await run_agent_once(order_id, run_id)
    await _apply_outcome(
        stale_claim,
        CapabilityOutcome(
            status=OutcomeStatus.succeeded,
            artifact=ArtifactDraft(
                artifact_key="intent_spec",
                artifact_type="intent_spec",
                content_payload={"stale": True},
            ),
        ),
    )

    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        executions = list(
            await session.scalars(
                select(AgentStepExecution).where(
                    AgentStepExecution.production_order_id == order_id
                )
            )
        )
        decision = await session.scalar(
            select(DecisionRequest).where(
                DecisionRequest.production_order_id == order_id
            )
        )
        artifacts = list(
            await session.scalars(
                select(Artifact).where(Artifact.production_order_id == order_id)
            )
        )
    assert order.status == ProductionOrderStatus.canceled
    assert decision.status == DecisionStatus.canceled
    assert artifacts == []
    assert all(item.status == AgentStepExecutionStatus.canceled.value for item in executions)
    assert all(item.lease_owner is None for item in executions)
    assert all(item.lease_expires_at is None for item in executions)
    assert all(item.heartbeat_at is None for item in executions)
    assert all(item.next_wakeup_at is None for item in executions)


async def test_cancel_commits_before_best_effort_external_interrupt() -> None:
    suffix = uuid.uuid4().hex[:8]
    principal = Principal(
        tenant_id=f"cancel-interrupt-tenant-{suffix}",
        user_id=f"cancel-interrupt-user-{suffix}",
    )
    capability = InterruptFailureCapability()
    order_id, run_id, execution_id = await _single_step_runtime(
        principal=principal,
        suffix=suffix,
        capability=capability,
        evaluator=PassEvaluator(),
    )
    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        assert execution.status == AgentStepExecutionStatus.waiting.value
        await command_production_order(
            session,
            principal=principal,
            order_id=order_id,
            command="cancel",
        )
    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        execution = await session.get(AgentStepExecution, execution_id)
    assert order.status == ProductionOrderStatus.canceled
    assert execution.status == AgentStepExecutionStatus.canceled.value
    assert capability.interrupt_calls == 1


async def test_evaluator_retry_is_bounded_and_does_not_repeat_capability() -> None:
    suffix = uuid.uuid4().hex[:8]
    principal = Principal(
        tenant_id=f"evaluator-seal-tenant-{suffix}",
        user_id=f"evaluator-seal-user-{suffix}",
    )
    capability = SuccessfulCapability()
    evaluator = FlakyEvaluator(failures=1)
    order_id, run_id, execution_id = await _single_step_runtime(
        principal=principal,
        suffix=suffix,
        capability=capability,
        evaluator=evaluator,
    )
    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        assert execution.status == AgentStepExecutionStatus.evaluating.value
        assert execution.evaluation_attempt == 1
        execution.next_wakeup_at = datetime.now(UTC)
        await session.commit()
    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        order = await session.get(ProductionOrder, order_id)
    assert execution.status == AgentStepExecutionStatus.succeeded.value
    assert execution.evaluation_attempt == 2
    assert order.status == ProductionOrderStatus.succeeded
    assert capability.calls == 1
    assert evaluator.calls == 2


async def test_evaluator_repeated_failure_reaches_manual_intervention() -> None:
    suffix = uuid.uuid4().hex[:8]
    principal = Principal(
        tenant_id=f"evaluator-final-tenant-{suffix}",
        user_id=f"evaluator-final-user-{suffix}",
    )
    capability = SuccessfulCapability()
    evaluator = FlakyEvaluator(failures=10)
    order_id, run_id, execution_id = await _single_step_runtime(
        principal=principal,
        suffix=suffix,
        capability=capability,
        evaluator=evaluator,
    )
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        execution.evaluation_max_attempts = 2
        await session.commit()
    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        execution.next_wakeup_at = datetime.now(UTC)
        await session.commit()
    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        order = await session.get(ProductionOrder, order_id)
    assert execution.status == AgentStepExecutionStatus.failed_final.value
    assert execution.evaluation_attempt == 2
    assert order.status == ProductionOrderStatus.manual_intervention
    assert capability.calls == 1


async def test_evaluator_lease_takeover_fences_stale_result() -> None:
    suffix = uuid.uuid4().hex[:8]
    principal = Principal(
        tenant_id=f"evaluator-fence-tenant-{suffix}",
        user_id=f"evaluator-fence-user-{suffix}",
    )
    capability = SuccessfulCapability()
    evaluator = BlockingFirstEvaluator()
    order_id, run_id, execution_id = await _single_step_runtime(
        principal=principal,
        suffix=suffix,
        capability=capability,
        evaluator=evaluator,
    )
    first_claim = (
        await claim_ready_agent_steps(
            order_id,
            agent_run_id=run_id,
            worker_id="evaluator-worker-a",
            limit=1,
        )
    )[0]
    first_task = asyncio.create_task(_execute_and_apply(first_claim))
    await asyncio.wait_for(evaluator.entered.wait(), timeout=5)
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        execution.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    second_claim = (
        await claim_ready_agent_steps(
            order_id,
            agent_run_id=run_id,
            worker_id="evaluator-worker-b",
            limit=1,
        )
    )[0]
    assert second_claim.fence_token > first_claim.fence_token
    await _execute_and_apply(second_claim)
    evaluator.release.set()
    await first_task

    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, execution_id)
        order = await session.get(ProductionOrder, order_id)
    assert execution.status == AgentStepExecutionStatus.succeeded.value
    assert execution.fence_token == second_claim.fence_token
    assert execution.evaluation_attempt == 2
    assert order.status == ProductionOrderStatus.succeeded
    assert capability.calls == 1
    assert evaluator.calls == 2


async def test_consumer_retries_from_outbox_and_deduplicates_success(monkeypatch) -> None:
    envelope = await _create_outbox_envelope("agent.run.requested")
    calls = 0

    async def flaky_dispatch(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("consumer transient failure")

    monkeypatch.setattr(worker_module, "dispatch_envelope", flaky_dispatch)
    with pytest.raises(RuntimeError):
        await worker_module.dispatch_envelope_once(envelope)
    async with SessionLocal() as session:
        consumed = await session.scalar(
            select(ConsumedEvent).where(ConsumedEvent.event_id == envelope["event_id"])
        )
        assert consumed.status == "failed"
        consumed.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    recovered = await worker_module.recover_consumed_envelopes()
    assert envelope["event_id"] in {item["event_id"] for item in recovered}
    await worker_module.dispatch_envelope_once(envelope)
    await worker_module.dispatch_envelope_once(envelope)
    async with SessionLocal() as session:
        consumed = await session.scalar(
            select(ConsumedEvent).where(ConsumedEvent.event_id == envelope["event_id"])
        )
    assert consumed.status == "succeeded"
    assert consumed.attempts == 2
    assert calls == 2


@pytest.mark.parametrize(
    ("topic", "schema_version"),
    [("runtime.noop", 1), ("agent.run.requested", 999)],
)
async def test_consumer_rejects_unknown_topic_and_schema(topic, schema_version) -> None:
    envelope = await _create_outbox_envelope(topic, schema_version)
    with pytest.raises(worker_module.UnsupportedRuntimeEventError):
        await worker_module.dispatch_envelope_once(envelope)
    async with SessionLocal() as session:
        consumed = await session.scalar(
            select(ConsumedEvent).where(ConsumedEvent.event_id == envelope["event_id"])
        )
    assert consumed.status == "failed"
    assert consumed.last_error


async def test_consumer_dead_letters_and_recovers_expired_claim(monkeypatch) -> None:
    monkeypatch.setattr(worker_module.settings, "runtime_consumer_max_attempts", 2)
    dead_envelope = await _create_outbox_envelope("agent.run.requested")

    async def always_fail(_):
        raise RuntimeError("consumer permanent failure")

    monkeypatch.setattr(worker_module, "dispatch_envelope", always_fail)
    with pytest.raises(RuntimeError):
        await worker_module.dispatch_envelope_once(dead_envelope)
    async with SessionLocal() as session:
        consumed = await session.scalar(
            select(ConsumedEvent).where(
                ConsumedEvent.event_id == dead_envelope["event_id"]
            )
        )
        consumed.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    with pytest.raises(RuntimeError):
        await worker_module.dispatch_envelope_once(dead_envelope)
    async with SessionLocal() as session:
        consumed = await session.scalar(
            select(ConsumedEvent).where(
                ConsumedEvent.event_id == dead_envelope["event_id"]
            )
        )
    assert consumed.status == "dead_lettered"
    assert consumed.dead_lettered_at is not None
    assert consumed.attempts == 2

    crash_envelope = await _create_outbox_envelope("agent.run.requested")
    fence = await worker_module._claim_envelope(crash_envelope)
    assert fence == 1
    async with SessionLocal() as session:
        consumed = await session.scalar(
            select(ConsumedEvent).where(
                ConsumedEvent.event_id == crash_envelope["event_id"]
            )
        )
        consumed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    recovered = await worker_module.recover_consumed_envelopes()
    assert crash_envelope["event_id"] in {item["event_id"] for item in recovered}

    async def succeed(_):
        return None

    monkeypatch.setattr(worker_module, "dispatch_envelope", succeed)
    await worker_module.dispatch_envelope_once(crash_envelope)
    async with SessionLocal() as session:
        consumed = await session.scalar(
            select(ConsumedEvent).where(
                ConsumedEvent.event_id == crash_envelope["event_id"]
            )
        )
    assert consumed.status == "succeeded"
    assert consumed.attempts == 2
