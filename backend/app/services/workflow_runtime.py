import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.services.provider_registry import get_provider_registry
from app.workflows.base import WorkflowContext, notify_agent
from app.workflows.registry import get_workflow_registry


logger = logging.getLogger("xingliu.workflow.runtime")
settings = get_settings()
workflow_registry = get_workflow_registry()
provider_registry = get_provider_registry()
worker_id = f"{os.getenv('HOSTNAME', 'worker')}-{uuid.uuid4().hex[:8]}"


async def run_workflow_once(
    workflow_id: str,
    *,
    ignore_schedule: bool = False,
) -> None:
    async with SessionLocal() as session:
        workflow = await session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == workflow_id)
            .options(
                selectinload(WorkflowRun.steps),
                selectinload(WorkflowRun.provider_jobs),
            )
            .with_for_update()
        )
        if workflow is None or workflow.status in {
            WorkflowStatus.succeeded,
            WorkflowStatus.failed_final,
            WorkflowStatus.canceled,
            WorkflowStatus.cancelled,
            WorkflowStatus.paused,
        }:
            return
        now = datetime.now(UTC)
        next_wakeup_at = workflow.next_wakeup_at
        if next_wakeup_at and next_wakeup_at.tzinfo is None:
            next_wakeup_at = next_wakeup_at.replace(tzinfo=UTC)
        if not ignore_schedule and next_wakeup_at and next_wakeup_at > now:
            return
        if (
            workflow.lease_expires_at
            and workflow.lease_expires_at > now
            and workflow.lease_owner != worker_id
        ):
            return
        workflow.lease_owner = worker_id
        workflow.lease_expires_at = now + timedelta(
            seconds=settings.workflow_lease_seconds
        )
        await session.commit()

        definition = workflow_registry.resolve(workflow.task_type)
        context = WorkflowContext(
            session=session,
            workflow=workflow,
            settings=settings,
            providers=provider_registry,
        )
        try:
            if definition is None:
                workflow.status = WorkflowStatus.manual_intervention
                workflow.error_code = "WORKFLOW_HANDLER_UNAVAILABLE"
                workflow.error_message = (
                    f"Workflow 类型尚未安装执行入口：{workflow.task_type}"
                )
                workflow.next_wakeup_at = None
                notify_agent(context, suffix="handler-unavailable")
                return
            if definition.capability != workflow.capability:
                workflow.status = WorkflowStatus.manual_intervention
                workflow.error_code = "WORKFLOW_CONTRACT_MISMATCH"
                workflow.error_message = (
                    f"Workflow {workflow.task_type} 与能力 {workflow.capability} 不匹配"
                )
                notify_agent(context, suffix="contract-mismatch")
                return
            if workflow.status == WorkflowStatus.canceling:
                await definition.handler.cancel(context)
                return
            await definition.handler.run(context)
        except Exception as exc:  # noqa: BLE001
            if definition is None:
                logger.exception("workflow %s failed before dispatch", workflow.id)
                workflow.status = WorkflowStatus.manual_intervention
                workflow.error_code = type(exc).__name__
                workflow.error_message = str(exc)
            else:
                await definition.handler.fail(context, exc)
        finally:
            workflow.lease_owner = None
            workflow.lease_expires_at = None
            await session.commit()
