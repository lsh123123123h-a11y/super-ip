import os

import pytest
from sqlalchemy import select

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
from app.agent.executor import AgentExecutionResult, ExecutionHandle
from app.agent.operations import ExecutorDefinition
from app.capabilities.registry import get_capability_registry
from app.evaluators.registry import get_evaluator_registry
from app.executors.registry import get_executor_registry
from app.models.agent import (
    AgentEvent,
    AgentOperation,
    DecisionRequest,
    DecisionStatus,
    PlanVersion,
    ProductionOrder,
    ProductionOrderStatus,
    QualityEvaluation,
)
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.schemas.agent import ProductionOrderCreate
from app.services.agent_runtime import run_agent_once
from app.services.agent_operation_service import run_agent_operation_once
from app.services.workflow_runtime import run_workflow_once
from app.services.agent_service import (
    command_production_order,
    create_production_order,
    create_project,
)


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


class SuccessfulHarness:
    async def start(self, request):
        return ExecutionHandle(
            executor_key="harness.test",
            execution_id=f"execution-{request.idempotency_key}",
            state="succeeded",
        )

    async def resume(self, execution_id):
        return ExecutionHandle(
            executor_key="harness.test",
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
                    content_payload={"summary": "Harness execution completed"},
                    lineage_payload={"execution_id": execution_id},
                ),
            ),
            usage={"total_tokens": 12},
        )


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
                    )
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


async def test_harness_bound_capability_executes_through_agent_operation() -> None:
    capability_key = "test.harness.generate"
    executor_key = "harness.test"
    executors = get_executor_registry()
    if executors.definition(executor_key) is None:
        executors.register(
            ExecutorDefinition(
                key=executor_key,
                version="1.0.0",
                label="测试 Harness",
                supported_operations=[capability_key],
            ),
            SuccessfulHarness(),
        )
    capabilities = get_capability_registry()
    if capabilities.definition(capability_key) is None:
        capabilities.register(
            CapabilityDefinition(
                key=capability_key,
                version="1.0.0",
                label="Harness 生成测试",
                execution_kind=ExecutionKind.harness,
            ),
            executor_key=executor_key,
            source="integration-test",
        )

    principal = Principal(tenant_id="harness-test-tenant", user_id="harness-test-user")
    async with SessionLocal() as session:
        project = await create_project(
            session,
            principal=principal,
            name="Harness Integration",
            goal="验证通用执行器绑定",
            settings_payload={},
        )
        overview, _ = await create_production_order(
            session,
            principal=principal,
            idempotency_key="harness-operation-order-v1",
            payload=ProductionOrderCreate(
                project_id=project.id,
                intent_text="通过 Harness 生成研究报告",
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
