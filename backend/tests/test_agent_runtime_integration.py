import os

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.principal import Principal
from app.models.agent import (
    AgentEvent,
    AgentOperation,
    DecisionRequest,
    DecisionStatus,
    PlanVersion,
    ProductionOrder,
    ProductionOrderStatus,
)
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.schemas.agent import ProductionOrderCreate
from app.services.agent_runtime import run_agent_once
from app.services.agent_operation_service import run_agent_operation_once
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
