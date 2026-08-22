import os
import uuid
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.core.principal import Principal
from app.agent.evaluation import (
    EvaluationAction,
    EvaluationResult,
    EvaluatorDefinition,
)
from app.agent.contracts import (
    ArtifactDraft,
    CapabilityDefinition,
    CapabilityOutcome,
    ExecutionKind,
    OutcomeStatus,
)
from app.agent.brain import StructuredBrainResponse
from app.agent.executor import AgentExecutionResult, ExecutionHandle
from app.agent.operations import ExecutorDefinition
from app.capabilities.content import (
    ContentGenerateCapability,
    ContentStrategyCapability,
)
from app.capabilities.foundation import IntentNormalizeCapability
from app.capabilities.registry import CapabilityRegistry, get_capability_registry
from app.evaluators.registry import get_evaluator_registry
from app.executors.registry import get_executor_registry
from app.models.agent import (
    AgentEvent,
    AgentOperation,
    AgentStepExecution,
    Artifact,
    ArtifactVersion,
    DecisionRequest,
    DecisionStatus,
    PlanVersion,
    ProductionOrder,
    ProductionOrderStatus,
    QualityEvaluation,
    ConsumedEvent,
)
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.schemas.agent import ProductionOrderCreate
from app.services.agent_runtime import _apply_outcome, run_agent_once
from app.services.agent_operation_service import run_agent_operation_once
from app.services.workflow_runtime import run_workflow_once
from app.services.agent_service import (
    command_production_order,
    create_production_order,
    create_project,
)
from app.services.agent_step_service import claim_ready_agent_steps
from app.worker import dispatch_envelope_once


pytestmark = [
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="需要迁移后的隔离 PostgreSQL 测试库",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


class PassOnSecondArtifactVersion:
    async def evaluate(self, context):
        passed = bool(
            context.artifact_version and context.artifact_version.version >= 2
        )
        return EvaluationResult(
            passed=passed,
            action=(
                EvaluationAction.accept if passed else EvaluationAction.rework
            ),
            issues=[] if passed else [{"code": "TEST_REWORK_ONCE"}],
            feedback="重新生成一次目标结构化产物" if not passed else "",
        )


class BlockingPassEvaluator:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def evaluate(self, context):
        self.entered.set()
        await self.release.wait()
        return EvaluationResult(passed=True, action=EvaluationAction.accept)


class SuccessfulExternalExecutor:
    async def start(self, request):
        return ExecutionHandle(
            executor_key="external.test",
            execution_id=f"execution-{request.idempotency_key}",
            state="succeeded",
        )

    async def resume(self, execution_id):
        return ExecutionHandle(
            executor_key="external.test",
            execution_id=execution_id,
            state="succeeded",
        )

    async def interrupt(self, execution_id):
        return None

    async def resolve_approval(self, execution_id, request_id, decision):
        return None

    async def collect_result(self, execution_id):
        return AgentExecutionResult(
            outcome=CapabilityOutcome(
                status=OutcomeStatus.succeeded,
                artifact=ArtifactDraft(
                    artifact_key="research_report",
                    artifact_type="document",
                    content_payload={"summary": "External execution completed"},
                    lineage_payload={"execution_id": execution_id},
                ),
            ),
            usage={"total_tokens": 12},
        )


class ContentBrain:
    def __init__(self) -> None:
        self.requests = []

    async def complete_structured(self, request):
        self.requests.append(request)
        if request.purpose == "content_strategy":
            output = {
                "audience": "内容创业者",
                "angle": "用生产闭环解释 Agent 产品",
                "core_message": "业务能力不应依赖开发工具",
                "hook": "没有 Codex，Agent 产品还能工作吗？",
                "key_points": ["Brain 决策", "Capability 执行", "Evaluator 闭环"],
                "structure": [{"section": "开头", "purpose": "澄清误区"}],
                "tone": "专业直接",
                "risks": [],
            }
        else:
            output = {
                "title": "开发工具不是 Agent 产品运行时",
                "summary": "厘清 Brain、Capability 与外部执行器的职责。",
                "body_markdown": "产品自己的 Agent Runtime 负责推进任务闭环。" * 20,
                "platform": "公众号",
                "calls_to_action": [],
                "factual_claims": [],
            }
        return StructuredBrainResponse(
            output=output,
            model_ref="content-test-model",
            gateway_ref="test-brain",
            usage={"total_tokens": 30},
        )

    async def probe(self):
        return {"ok": True}


async def test_step_claim_fencing_survives_missing_event_history() -> None:
    principal = Principal(tenant_id="fence-test-tenant", user_id="fence-test-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="Fenced Step Runtime",
            goal="验证 durable execution state",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key="fenced-step-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="验证步骤执行权转移",
                automation_mode="automatic",
                inputs={
                    "script": "fencing test",
                    "audio_path": "/code/data/fence.wav",
                    "avatar_video_path": "/code/data/fence.mp4",
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

    await run_agent_operation_once(operation_id, "planning-worker")
    async with SessionLocal() as session:
        await session.execute(delete(AgentEvent).where(AgentEvent.agent_run_id == run_id))
        await session.commit()

    first = (
        await claim_ready_agent_steps(
            order_id,
            agent_run_id=run_id,
            worker_id="worker-a",
            limit=1,
        )
    )[0]
    assert (
        await claim_ready_agent_steps(
            order_id,
            agent_run_id=run_id,
            worker_id="worker-b",
            limit=1,
        )
    ) == []

    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, first.execution_id)
        execution.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    second = (
        await claim_ready_agent_steps(
            order_id,
            agent_run_id=run_id,
            worker_id="worker-b",
            limit=1,
        )
    )[0]
    assert second.execution_id == first.execution_id
    assert second.fence_token > first.fence_token

    await _apply_outcome(
        first,
        CapabilityOutcome(
            status=OutcomeStatus.succeeded,
            artifact=ArtifactDraft(
                artifact_key="intent_spec",
                artifact_type="intent_spec",
                content_payload={"goal": "stale result"},
            ),
        ),
    )
    async with SessionLocal() as session:
        execution = await session.get(AgentStepExecution, first.execution_id)
        event_count = len(
            list(
                await session.scalars(
                    select(AgentEvent.id).where(AgentEvent.agent_run_id == run_id)
                )
            )
        )
    assert execution.lease_owner == "worker-b"
    assert execution.fence_token == second.fence_token
    assert execution.output_artifact_version_id is None
    assert event_count == 0


async def test_runtime_consumer_deduplicates_successful_event() -> None:
    event_id = str(uuid.uuid4())
    envelope = {
        "event_id": event_id,
        "schema_version": 1,
        "topic": "agent.run.requested",
        "aggregate_id": str(uuid.uuid4()),
        "payload": {"production_order_id": str(uuid.uuid4())},
    }

    await dispatch_envelope_once(envelope)
    await dispatch_envelope_once(envelope)

    async with SessionLocal() as session:
        consumed = await session.scalar(
            select(ConsumedEvent).where(ConsumedEvent.event_id == event_id)
        )
    assert consumed is not None
    assert consumed.status == "succeeded"
    assert consumed.attempts == 1


async def test_evaluator_runs_without_holding_step_row_lock() -> None:
    evaluator_key = f"test.blocking-pass-{uuid.uuid4().hex[:8]}"
    evaluator = BlockingPassEvaluator()
    registry = get_evaluator_registry()
    registry.register(
        EvaluatorDefinition(
            key=evaluator_key,
            version="1.0.0",
            label="阻塞评价器",
        ),
        evaluator,
        source="integration-test",
    )
    principal = Principal(tenant_id="evaluator-lock-tenant", user_id="evaluator-lock-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="Evaluator Lock Test",
            goal="评价器不持有 step row lock",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key="evaluator-lock-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="测试评价器事务边界",
                automation_mode="automatic",
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
    await run_agent_operation_once(operation_id, "planning-worker")
    async with SessionLocal() as session:
        plan = await session.scalar(
            select(PlanVersion).where(PlanVersion.agent_run_id == run_id)
        )
        payload = dict(plan.plan_payload)
        steps = [dict(item) for item in payload["steps"]]
        steps[0]["evaluator"] = evaluator_key
        steps[0]["evaluator_version"] = "1.0.0"
        plan.plan_payload = {**payload, "steps": steps}
        execution = await session.scalar(
            select(AgentStepExecution).where(
                AgentStepExecution.plan_version_id == plan.id,
                AgentStepExecution.plan_step_key == steps[0]["key"],
            )
        )
        execution.evaluator_key = evaluator_key
        execution.evaluator_version = "1.0.0"
        await session.commit()
    claim = (
        await claim_ready_agent_steps(
            order_id,
            agent_run_id=run_id,
            worker_id="evaluation-worker",
            limit=1,
        )
    )[0]
    task = asyncio.create_task(
        _apply_outcome(
            claim,
            CapabilityOutcome(
                status=OutcomeStatus.succeeded,
                artifact=ArtifactDraft(
                    artifact_key="intent_spec",
                    artifact_type="intent_spec",
                    content_payload={"goal": "evaluation lock boundary"},
                ),
            ),
        )
    )
    await asyncio.wait_for(evaluator.entered.wait(), timeout=5)
    async with SessionLocal() as session:
        locked = await session.scalar(
            select(AgentStepExecution)
            .where(AgentStepExecution.id == claim.execution_id)
            .with_for_update(nowait=True)
        )
        assert locked.status == "evaluating"
        await session.rollback()
    evaluator.release.set()
    await task


async def test_database_rejects_cross_tenant_aggregate_reference() -> None:
    first = Principal(tenant_id="tenant-fk-a", user_id="tenant-fk-user-a")
    second = Principal(tenant_id="tenant-fk-b", user_id="tenant-fk-user-b")
    async with SessionLocal() as session:
        first_project = await create_project(
            session,
            principal=first,
            name="Tenant A",
            goal="tenant boundary",
            settings_payload={},
        )
        second_project = await create_project(
            session,
            principal=second,
            name="Tenant B",
            goal="tenant boundary",
            settings_payload={},
        )
        first_order, _ = await create_production_order(
            session,
            principal=first,
            idempotency_key="tenant-fk-order-a",
            payload=ProductionOrderCreate(
                project_id=first_project.id,
                intent_text="tenant A order",
            ),
        )
        second_order, _ = await create_production_order(
            session,
            principal=second,
            idempotency_key="tenant-fk-order-b",
            payload=ProductionOrderCreate(
                project_id=second_project.id,
                intent_text="tenant B order",
            ),
        )
        assert first_order.order.tenant_id != second_order.order.tenant_id
        session.add(
            Artifact(
                tenant_id=first.tenant_id,
                production_order_id=second_order.order.id,
                artifact_key="cross_tenant",
                artifact_type="test",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_agent_kernel_dispatches_avatar_through_capability_plugin() -> None:
    principal = Principal(tenant_id="kernel-test-tenant", user_id="kernel-test-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="Agent Kernel Integration",
            goal="验证通用运行时与数字人插件的合同",
            settings_payload={},
        )
        overview, created = await create_production_order(
            session,
            principal=principal,
            idempotency_key="kernel-integration-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="将已有素材制作成数字人口播",
                automation_mode="automatic",
                inputs={
                    "script": "这是一条合同集成测试脚本。",
                    "audio_path": "/code/data/kernel-test.wav",
                    "avatar_video_path": "/code/data/kernel-test.mp4",
                },
            ),
        )
        assert created
        assert overview.plan is None
        assert overview.order.status == ProductionOrderStatus.planning
        order_id = overview.order.id
        run_id = overview.agent_run.id

    async with SessionLocal() as session:
        operation = await session.scalar(
            select(AgentOperation).where(AgentOperation.agent_run_id == run_id)
        )
        assert operation is not None
        operation_id = operation.id

    await run_agent_operation_once(operation_id, "integration-worker")
    await run_agent_once(order_id, run_id)

    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        workflow = await session.scalar(
            select(WorkflowRun).where(WorkflowRun.production_order_id == order_id)
        )
        operation = await session.get(AgentOperation, operation_id)
        plan = await session.scalar(
            select(PlanVersion).where(PlanVersion.agent_run_id == run_id)
        )
        events = list(
            (
                await session.execute(
                    select(AgentEvent).where(AgentEvent.agent_run_id == run_id)
                )
            ).scalars()
        )
        evaluations = list(
            (
                await session.execute(
                    select(QualityEvaluation).where(
                        QualityEvaluation.tenant_id == principal.tenant_id
                    )
                )
            ).scalars()
        )

    assert order is not None and order.status == ProductionOrderStatus.running
    assert operation is not None and operation.status == "succeeded"
    assert operation.trace_id and operation.span_id
    assert plan is not None and operation.plan_version_id == plan.id
    assert workflow is not None and workflow.status == WorkflowStatus.queued
    dispatched = next(event for event in events if event.event_type == "agent.step.dispatched")
    assert dispatched.payload["capability"] == "avatar.render"
    assert dispatched.payload["external_execution_id"] == workflow.id
    succeeded_steps = {
        event.payload["step_key"]
        for event in events
        if event.event_type == "agent.step.succeeded"
    }
    assert succeeded_steps == {
        "intent.normalize",
        "script.accept_input",
        "audio.evaluate",
    }
    assert len(evaluations) == 3
    assert all(item.passed for item in evaluations)

    await run_workflow_once(workflow.id)
    await run_workflow_once(workflow.id, ignore_schedule=True)
    async with SessionLocal() as session:
        completed_workflow = await session.get(WorkflowRun, workflow.id)
    assert completed_workflow is not None
    assert completed_workflow.status == WorkflowStatus.succeeded

    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        completed_order = await session.get(ProductionOrder, order_id)
        completed_plan = await session.get(PlanVersion, plan.id)
        final_evaluations = list(
            (
                await session.execute(
                    select(QualityEvaluation).where(
                        QualityEvaluation.tenant_id == principal.tenant_id
                    )
                )
            ).scalars()
        )
    assert completed_order is not None
    assert completed_order.status == ProductionOrderStatus.succeeded
    assert completed_plan is not None and completed_plan.status.value == "completed"
    assert len(final_evaluations) == 4


async def test_async_planning_creates_review_only_after_plan_exists() -> None:
    principal = Principal(tenant_id="planning-review-tenant", user_id="planning-review-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="Planning Review Integration",
            goal="验证异步方案审核",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key="planning-review-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="规划一条数字人口播",
                automation_mode="key_checkpoints",
                inputs={},
            ),
        )
        assert overview.plan is None
        operation = await session.scalar(
            select(AgentOperation).where(
                AgentOperation.production_order_id == overview.order.id
            )
        )
        assert operation is not None
        operation_id = operation.id

    await run_agent_operation_once(operation_id, "integration-worker")

    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, overview.order.id)
        plan = await session.scalar(
            select(PlanVersion).where(PlanVersion.agent_run_id == overview.agent_run.id)
        )
        decision = await session.scalar(
            select(DecisionRequest).where(
                DecisionRequest.agent_run_id == overview.agent_run.id,
                DecisionRequest.status == DecisionStatus.pending,
            )
        )

    assert order is not None and order.status == ProductionOrderStatus.awaiting_plan_approval
    assert plan is not None
    assert decision is not None and decision.plan_version_id == plan.id
    assert decision.scope == "plan"


async def test_cancel_before_planning_finishes_cancels_operation_without_plan() -> None:
    principal = Principal(tenant_id="planning-cancel-tenant", user_id="planning-cancel-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="Planning Cancel Integration",
            goal="验证规划前取消",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key="planning-cancel-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="创建后立即取消",
                automation_mode="automatic",
            ),
        )
        canceled = await command_production_order(
            session,
            principal=principal,
            order_id=overview.order.id,
            command="cancel",
        )
        operation = await session.scalar(
            select(AgentOperation).where(
                AgentOperation.production_order_id == overview.order.id
            )
        )

    assert canceled.order.status == ProductionOrderStatus.canceled
    assert canceled.plan is None
    assert operation is not None and operation.status == "canceled"


async def test_failed_evaluation_reworks_same_step_then_continues() -> None:
    evaluator_key = "test.rework-once"
    registry = get_evaluator_registry()
    if registry.resolve(evaluator_key) is None:
        registry.register(
            EvaluatorDefinition(
                key=evaluator_key,
                version="1.0.0",
                label="测试一次自动返工",
            ),
            PassOnSecondArtifactVersion(),
            source="integration-test",
        )
    principal = Principal(tenant_id="rework-test-tenant", user_id="rework-test-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="Evaluation Rework Integration",
            goal="验证评价失败后的自动返工",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key="evaluation-rework-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="制作可评价的数字人口播",
                automation_mode="automatic",
                max_auto_rework=2,
                inputs={
                    "script": "评价闭环测试脚本。",
                    "audio_path": "/code/data/rework-test.wav",
                    "avatar_video_path": "/code/data/rework-test.mp4",
                },
            ),
        )
        operation = await session.scalar(
            select(AgentOperation).where(
                AgentOperation.agent_run_id == overview.agent_run.id
            )
        )
        assert operation is not None
        operation_id = operation.id
        order_id = overview.order.id
        run_id = overview.agent_run.id

    await run_agent_operation_once(operation_id, "integration-worker")
    async with SessionLocal() as session:
        plan = await session.scalar(
            select(PlanVersion).where(PlanVersion.agent_run_id == run_id)
        )
        assert plan is not None
        payload = dict(plan.plan_payload)
        steps = [dict(item) for item in payload["steps"]]
        steps[0]["evaluator"] = evaluator_key
        plan.plan_payload = {**payload, "steps": steps}
        await session.commit()

    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        assert order is not None
        assert order.status == ProductionOrderStatus.retry_wait
        assert order.auto_rework_count == 1
        retry_execution = await session.scalar(
            select(AgentStepExecution)
            .where(
                AgentStepExecution.agent_run_id == run_id,
                AgentStepExecution.attempt == 2,
            )
            .order_by(AgentStepExecution.created_at)
        )
        assert retry_execution is not None
        retry_execution.next_wakeup_at = datetime.now(UTC)
        await session.commit()

    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        events = list(
            (
                await session.execute(
                    select(AgentEvent).where(AgentEvent.agent_run_id == run_id)
                )
            ).scalars()
        )
        evaluations = list(
            (
                await session.execute(
                        select(QualityEvaluation).where(
                            QualityEvaluation.tenant_id == principal.tenant_id,
                            QualityEvaluation.evaluator_key == evaluator_key,
                        ).order_by(QualityEvaluation.created_at)
                )
            ).scalars()
        )

    assert order is not None and order.status == ProductionOrderStatus.running
    assert [item.passed for item in evaluations] == [False, True]
    assert any(event.event_type == "agent.step.rework_requested" for event in events)
    assert any(
        event.event_type == "agent.step.succeeded"
        and event.payload.get("step_key") == "intent.normalize"
        for event in events
    )


async def test_content_article_runs_on_product_runtime_without_external_executor(
    monkeypatch,
) -> None:
    from app.product import planning as planning_module
    from app.services import agent_runtime as runtime_module

    brain = ContentBrain()
    capabilities = CapabilityRegistry()
    capabilities.register(
        CapabilityDefinition(
            key="agent.intent.normalize",
            version="1.0.0",
            label="目标结构化",
            execution_kind=ExecutionKind.inline,
        ),
        IntentNormalizeCapability(),
        source="integration-test",
    )
    capabilities.register(
        CapabilityDefinition(
            key="content.strategy",
            version="1.0.0",
            label="内容策略",
            execution_kind=ExecutionKind.inline,
        ),
        ContentStrategyCapability(brain),
        source="integration-test",
    )
    capabilities.register(
        CapabilityDefinition(
            key="content.generate",
            version="1.0.0",
            label="内容生成",
            execution_kind=ExecutionKind.inline,
        ),
        ContentGenerateCapability(brain),
        source="integration-test",
    )
    monkeypatch.setattr(
        planning_module,
        "get_capability_registry",
        lambda: capabilities,
    )
    monkeypatch.setattr(planning_module, "create_configured_brain", lambda: None)
    monkeypatch.setattr(
        runtime_module,
        "get_capability_registry",
        lambda: capabilities,
    )

    principal = Principal(tenant_id="content-test-tenant", user_id="content-test-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="Content Runtime Integration",
            goal="验证非数字人内容链路",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key="content-article-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                product_key="content.article",
                intent_text="生成一篇解释 Agent 产品边界的公众号文章",
                automation_mode="automatic",
                inputs={"target_platforms": ["公众号"]},
            ),
        )
        planning = await session.scalar(
            select(AgentOperation).where(
                AgentOperation.agent_run_id == overview.agent_run.id
            )
        )
        assert planning is not None
        planning_id = planning.id
        order_id = overview.order.id
        run_id = overview.agent_run.id

    await run_agent_operation_once(planning_id, "integration-worker")
    await run_agent_once(order_id, run_id)

    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        operations = list(
            (
                await session.execute(
                    select(AgentOperation).where(AgentOperation.agent_run_id == run_id)
                )
            ).scalars()
        )
        artifacts = list(
            (
                await session.execute(
                    select(Artifact.artifact_key, ArtifactVersion.content_payload)
                    .join(ArtifactVersion, ArtifactVersion.artifact_id == Artifact.id)
                    .where(Artifact.production_order_id == order_id)
                )
            ).all()
        )

    assert order is not None and order.status == ProductionOrderStatus.succeeded
    assert [operation.operation_type for operation in operations] == ["planning"]
    artifact_map = dict(artifacts)
    assert set(artifact_map) == {"intent_spec", "strategy_proposal", "content_draft"}
    assert artifact_map["content_draft"]["platform"] == "公众号"
    assert brain.requests[1].user_input["artifacts"]["strategy_proposal"][
        "content"
    ]["core_message"] == "业务能力不应依赖开发工具"


async def test_external_executor_capability_executes_through_agent_operation() -> None:
    capability_key = "test.external.generate"
    executor_key = "external.test"
    executors = get_executor_registry()
    if executors.definition(executor_key) is None:
        executors.register(
            ExecutorDefinition(
                key=executor_key,
                version="1.0.0",
                label="测试外部执行器",
                supported_operations=[capability_key],
            ),
            SuccessfulExternalExecutor(),
        )
    capabilities = get_capability_registry()
    if capabilities.definition(capability_key) is None:
        capabilities.register(
            CapabilityDefinition(
                key=capability_key,
                version="1.0.0",
                label="外部执行器生成测试",
                execution_kind=ExecutionKind.external,
            ),
            external_executor_key=executor_key,
            source="integration-test",
        )

    principal = Principal(tenant_id="external-test-tenant", user_id="external-test-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="External Executor Integration",
            goal="验证通用执行器绑定",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key="external-operation-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="通过可选外部执行器生成研究报告",
                automation_mode="automatic",
                inputs={},
            ),
        )
        planning = await session.scalar(
            select(AgentOperation).where(
                AgentOperation.agent_run_id == overview.agent_run.id
            )
        )
        assert planning is not None
        planning_id = planning.id
        order_id = overview.order.id
        run_id = overview.agent_run.id

    await run_agent_operation_once(planning_id, "integration-worker")
    async with SessionLocal() as session:
        plan = await session.scalar(
            select(PlanVersion).where(PlanVersion.agent_run_id == run_id)
        )
        assert plan is not None
        plan.plan_payload = {
            "contract": "agent.plan.v1",
            "goal": "生成研究报告",
            "steps": [
                {
                    "key": "research.generate",
                    "capability": capability_key,
                    "depends_on": [],
                    "expected_artifact": "research_report",
                    "evaluator": "script_quality_v1",
                    "checkpoint": "none",
                    "blocked_by_missing_input": False,
                }
            ],
            "termination_policy": "all_required_artifacts_approved",
            "max_auto_rework": 2,
            "planner": {"kind": "integration-test"},
            "revision_context": None,
        }
        executions = list(
            await session.scalars(
                select(AgentStepExecution)
                .where(AgentStepExecution.plan_version_id == plan.id)
                .order_by(AgentStepExecution.created_at)
            )
        )
        research_execution = executions[0]
        await session.execute(
            delete(AgentStepExecution).where(
                AgentStepExecution.plan_version_id == plan.id,
                AgentStepExecution.id != research_execution.id,
            )
        )
        research_execution.plan_step_key = "research.generate"
        research_execution.capability_key = capability_key
        research_execution.capability_version = "1.0.0"
        research_execution.evaluator_key = "script_quality_v1"
        research_execution.evaluator_version = "1.0.0"
        research_execution.execution_kind = "external"
        await session.commit()

    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        operation = await session.scalar(
            select(AgentOperation).where(
                AgentOperation.agent_run_id == run_id,
                AgentOperation.operation_type == "executor",
            )
        )
        assert operation is not None
        assert operation.plan_version_id == plan.id
        assert operation.implementation_version == "2.0.0"
        assert operation.executor_version == "1.0.0"
        operation_id = operation.id

    await run_agent_operation_once(operation_id, "integration-worker")
    await run_agent_once(order_id, run_id)
    async with SessionLocal() as session:
        order = await session.get(ProductionOrder, order_id)
        operation = await session.get(AgentOperation, operation_id)
        evaluation = await session.scalar(
            select(QualityEvaluation).where(
                QualityEvaluation.tenant_id == principal.tenant_id
            )
        )

    assert order is not None and order.status == ProductionOrderStatus.succeeded
    assert operation is not None and operation.status == "succeeded"
    assert operation.usage_payload == {"total_tokens": 12}
    assert evaluation is not None and evaluation.passed
