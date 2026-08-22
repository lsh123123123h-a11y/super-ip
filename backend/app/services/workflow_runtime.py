import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.services.provider_registry import get_provider_registry
from app.workflows.base import WorkflowContext, notify_agent
from app.workflows.registry import get_workflow_registry
from app.services.workflow_transitions import transition_workflow


logger = logging.getLogger("xingliu.workflow.runtime")
settings = get_settings()
workflow_registry = get_workflow_registry()
provider_registry = get_provider_registry()
worker_id = f"{os.getenv('HOSTNAME', 'worker')}-{uuid.uuid4().hex[:8]}"

TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.succeeded,
    WorkflowStatus.failed_final,
    WorkflowStatus.canceled,
    WorkflowStatus.paused,
    WorkflowStatus.manual_intervention,
}


async def _renew_workflow_lease(
    workflow_id: str,
    *,
    claim_owner: str,
    fence_token: int,
) -> bool:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        result = await session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == workflow_id,
                WorkflowRun.lease_owner == claim_owner,
                WorkflowRun.fence_token == fence_token,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now
                + timedelta(seconds=settings.workflow_lease_seconds),
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def _heartbeat_loop(
    workflow_id: str,
    *,
    claim_owner: str,
    fence_token: int,
    stopped: asyncio.Event,
) -> None:
    interval = max(1.0, settings.workflow_lease_seconds / 3)
    while not stopped.is_set():
        try:
            await asyncio.wait_for(stopped.wait(), timeout=interval)
        except TimeoutError:
            if not await _renew_workflow_lease(
                workflow_id,
                claim_owner=claim_owner,
                fence_token=fence_token,
            ):
                return


async def run_workflow_once(
    workflow_id: str,
    *,
    ignore_schedule: bool = False,
) -> None:
    """Claim briefly, execute without a row lock, then apply only with a fresh fence."""

    claim_owner = worker_id
    async with SessionLocal() as session:
        workflow = await session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == workflow_id)
            .with_for_update()
        )
        if workflow is None or workflow.status in TERMINAL_WORKFLOW_STATUSES:
            return
        now = datetime.now(UTC)
        next_wakeup_at = workflow.next_wakeup_at
        if next_wakeup_at and next_wakeup_at.tzinfo is None:
            next_wakeup_at = next_wakeup_at.replace(tzinfo=UTC)
        if not ignore_schedule and next_wakeup_at and next_wakeup_at > now:
            return
        lease_expires_at = workflow.lease_expires_at
        if lease_expires_at and lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        if lease_expires_at and lease_expires_at > now:
            return
        workflow.lease_owner = claim_owner
        workflow.lease_expires_at = now + timedelta(
            seconds=settings.workflow_lease_seconds
        )
        workflow.heartbeat_at = now
        workflow.fence_token += 1
        workflow.next_wakeup_at = None
        fence_token = workflow.fence_token
        await session.commit()

    stopped = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat_loop(
            workflow_id,
            claim_owner=claim_owner,
            fence_token=fence_token,
            stopped=stopped,
        )
    )
    try:
        async with SessionLocal() as session:
            workflow = await session.scalar(
                select(WorkflowRun)
                .where(
                    WorkflowRun.id == workflow_id,
                    WorkflowRun.lease_owner == claim_owner,
                    WorkflowRun.fence_token == fence_token,
                )
                .options(
                    selectinload(WorkflowRun.steps),
                    selectinload(WorkflowRun.provider_jobs),
                )
            )
            if workflow is None:
                return
            definition = workflow_registry.resolve(
                workflow.task_type,
                workflow.workflow_definition_version,
            )
            context = WorkflowContext(
                session=session,
                workflow=workflow,
                settings=settings,
                providers=provider_registry,
            )
            try:
                if definition is None:
                    transition_workflow(workflow, WorkflowStatus.manual_intervention)
                    workflow.error_code = "WORKFLOW_HANDLER_UNAVAILABLE"
                    workflow.error_message = (
                        "Workflow 精确版本尚未安装："
                        f"{workflow.task_type}@{workflow.workflow_definition_version}"
                    )
                    notify_agent(context, suffix="handler-unavailable")
                elif definition.capability != workflow.capability:
                    transition_workflow(workflow, WorkflowStatus.manual_intervention)
                    workflow.error_code = "WORKFLOW_CONTRACT_MISMATCH"
                    workflow.error_message = (
                        f"Workflow {workflow.task_type} 与能力 {workflow.capability} 不匹配"
                    )
                    notify_agent(context, suffix="contract-mismatch")
                elif workflow.status == WorkflowStatus.canceling:
                    await definition.handler.cancel(context)
                else:
                    await definition.handler.run(context)
            except Exception as exc:  # noqa: BLE001
                if definition is None:
                    logger.exception("workflow %s failed before dispatch", workflow.id)
                    transition_workflow(workflow, WorkflowStatus.manual_intervention)
                    workflow.error_code = type(exc).__name__
                    workflow.error_message = str(exc)
                else:
                    await definition.handler.fail(context, exc)

            stopped.set()
            await heartbeat
            with session.no_autoflush:
                current_fence = await session.scalar(
                    select(WorkflowRun.fence_token).where(
                        WorkflowRun.id == workflow_id,
                        WorkflowRun.lease_owner == claim_owner,
                    )
                )
            if current_fence != fence_token:
                await session.rollback()
                logger.warning(
                    "discarded stale workflow result workflow=%s fence=%s",
                    workflow_id,
                    fence_token,
                )
                return
            workflow.lease_owner = None
            workflow.lease_expires_at = None
            workflow.heartbeat_at = None
            await session.commit()
    finally:
        if not stopped.is_set():
            stopped.set()
            await heartbeat
