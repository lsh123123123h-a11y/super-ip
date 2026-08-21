import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.agent import (
    AgentEvent,
    Artifact,
    ArtifactVersion,
    ArtifactVersionStatus,
    OutboxEvent,
    ProductionOrder,
    ProductionOrderStatus,
)
from app.models.orchestration import (
    ProviderJob,
    StepAttempt,
    StepStatus,
    WorkflowRun,
    WorkflowStatus,
)
from app.providers.base import AvatarRenderInput, ProviderJobState
from app.services.agent_operation_service import (
    list_due_agent_operation_ids,
    run_agent_operation_once,
)
from app.services.agent_runtime import run_agent_once
from app.services.outbox_service import publish_outbox_batch
from app.services.provider_registry import get_provider_registry


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("xingliu.worker")
settings = get_settings()
provider_registry = get_provider_registry()
worker_id = f"{os.getenv('HOSTNAME', 'worker')}-{uuid.uuid4().hex[:8]}"


def provider_result_to_asset_path(result_path: str | None) -> str | None:
    if not result_path:
        return None
    normalized = result_path.replace("\\", "/")
    if "://" in normalized:
        return None
    provider_root = settings.duix_container_data_root.rstrip("/")
    if normalized == provider_root:
        return None
    if normalized.startswith(f"{provider_root}/"):
        normalized = normalized[len(provider_root) + 1 :]
    normalized = normalized.lstrip("/")
    if not normalized or ".." in normalized.split("/"):
        return None
    return normalized


def step_by_key(workflow: WorkflowRun, key: str):
    return next(item for item in workflow.steps if item.step_key == key)


async def start_step_attempt(session, workflow: WorkflowRun, key: str, input_payload: dict[str, Any]) -> StepAttempt:
    step = step_by_key(workflow, key)
    step.status = StepStatus.running
    step.progress = max(step.progress, 1)
    step.attempt += 1
    step.started_at = datetime.now(UTC)
    step.finished_at = None
    attempt = StepAttempt(
        tenant_id=workflow.tenant_id,
        workflow_id=workflow.id,
        workflow_step_id=step.id,
        attempt_number=step.attempt,
        status="running",
        input_payload=input_payload,
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def finish_step_attempt(
    session,
    workflow: WorkflowRun,
    key: str,
    *,
    status: StepStatus,
    output_payload: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    step = step_by_key(workflow, key)
    step.status = status
    step.progress = 100 if status == StepStatus.succeeded else step.progress
    step.finished_at = datetime.now(UTC)
    if error:
        step.error_message = str(error)
    attempt = await session.scalar(
        select(StepAttempt)
        .where(StepAttempt.workflow_step_id == step.id, StepAttempt.attempt_number == step.attempt)
        .order_by(StepAttempt.started_at.desc())
        .limit(1)
    )
    if attempt:
        attempt.status = status.value
        attempt.output_payload = output_payload
        attempt.error_code = error.__class__.__name__ if error else None
        attempt.error_message = str(error) if error else None
        attempt.finished_at = datetime.now(UTC)


def schedule_workflow_wakeup(session, workflow: WorkflowRun, *, poll_number: int, delay_seconds: float) -> None:
    available_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    workflow.next_wakeup_at = available_at
    session.add(
        OutboxEvent(
            tenant_id=workflow.tenant_id or "local-tenant",
            aggregate_type="workflow",
            aggregate_id=workflow.id,
            topic="workflow.run.requested",
            payload={"workflow_id": workflow.id},
            dedupe_key=f"workflow:{workflow.id}:poll:{poll_number}",
            available_at=available_at,
        )
    )


def notify_agent(session, workflow: WorkflowRun, *, suffix: str) -> None:
    if not workflow.production_order_id:
        return
    session.add(
        OutboxEvent(
            tenant_id=workflow.tenant_id or "local-tenant",
            aggregate_type="production_order",
            aggregate_id=workflow.production_order_id,
            topic="agent.run.requested",
            payload={"production_order_id": workflow.production_order_id},
            dedupe_key=f"agent-observe:{workflow.id}:{suffix}",
        )
    )


async def persist_avatar_artifact(session, workflow: WorkflowRun, job: ProviderJob) -> None:
    if not workflow.production_order_id or not workflow.tenant_id:
        return
    order = await session.get(ProductionOrder, workflow.production_order_id)
    if order is None:
        return
    artifact = await session.scalar(
        select(Artifact).where(
            Artifact.production_order_id == order.id,
            Artifact.artifact_key == "avatar_video",
        )
    )
    if artifact is None:
        artifact = Artifact(
            tenant_id=workflow.tenant_id,
            production_order_id=order.id,
            content_item_id=order.content_item_id,
            artifact_key="avatar_video",
            artifact_type="video",
        )
        session.add(artifact)
        await session.flush()
    latest_version = await session.scalar(
        select(ArtifactVersion.version)
        .where(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version.desc())
        .limit(1)
    )
    result_ref = {
        "kind": "workflow_result",
        "workflow_id": workflow.id,
        "download_available": bool(workflow.output_payload and workflow.output_payload.get("artifact_path")),
        "remote_available": bool(workflow.output_payload and workflow.output_payload.get("result_url")),
    }
    version = ArtifactVersion(
        tenant_id=workflow.tenant_id,
        artifact_id=artifact.id,
        plan_version_id=workflow.plan_version_id,
        version=int(latest_version or 0) + 1,
        status=ArtifactVersionStatus.candidate,
        content_payload={"media_ref": result_ref},
        lineage_payload={
            "workflow_id": workflow.id,
            "provider_job_id": job.id,
            "plan_version_id": workflow.plan_version_id,
        },
    )
    session.add(version)
    await session.flush()
    session.add(
        AgentEvent(
            tenant_id=workflow.tenant_id,
            production_order_id=order.id,
            event_type="artifact.version.created",
            payload={
                "artifact_id": artifact.id,
                "artifact_version_id": version.id,
                "artifact_key": "avatar_video",
                "version": version.version,
            },
        )
    )


async def fail_workflow(session, workflow: WorkflowRun, exc: Exception) -> None:
    logger.error("workflow %s failed: %s", workflow.id, exc, exc_info=True)
    render_step = step_by_key(workflow, "avatar_render")
    workflow.status = (
        WorkflowStatus.failed_final
        if render_step.attempt >= settings.max_workflow_attempts
        else WorkflowStatus.failed_retryable
    )
    workflow.error_code = exc.__class__.__name__
    workflow.error_message = str(exc)
    workflow.next_wakeup_at = None
    for step in workflow.steps:
        if step.status == StepStatus.running:
            await finish_step_attempt(
                session,
                workflow,
                step.step_key,
                status=StepStatus.failed,
                error=exc,
            )
    notify_agent(session, workflow, suffix=f"failed:{render_step.attempt}")


async def run_workflow_once(workflow_id: str) -> None:
    async with SessionLocal() as session:
        workflow = await session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == workflow_id)
            .options(selectinload(WorkflowRun.steps), selectinload(WorkflowRun.provider_jobs))
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
        if workflow.lease_expires_at and workflow.lease_expires_at > now and workflow.lease_owner != worker_id:
            return
        workflow.lease_owner = worker_id
        workflow.lease_expires_at = now + timedelta(seconds=settings.workflow_lease_seconds)
        await session.commit()

        try:
            if workflow.status == WorkflowStatus.canceling:
                workflow.status = WorkflowStatus.canceled
                workflow.next_wakeup_at = None
                return

            payload = workflow.input_payload
            validate_step = step_by_key(workflow, "validate")
            if validate_step.status != StepStatus.succeeded:
                await start_step_attempt(session, workflow, "validate", {})
                if not payload.get("audio_path") or not payload.get("avatar_video_path"):
                    raise ValueError("缺少数字人渲染所需的音频或参考视频")
                await finish_step_attempt(
                    session,
                    workflow,
                    "validate",
                    status=StepStatus.succeeded,
                    output_payload={"valid": True},
                )
                workflow.progress = 10

            render_step = step_by_key(workflow, "avatar_render")
            job = max(workflow.provider_jobs, key=lambda item: item.created_at or now, default=None)
            if render_step.status != StepStatus.succeeded and job is None:
                attempt = await start_step_attempt(
                    session,
                    workflow,
                    "avatar_render",
                    {"capability": "avatar.render"},
                )
                provider_name = str(payload.get("selected_provider") or "duix")
                external_job_id = f"{workflow.id}-{render_step.attempt}"
                job = ProviderJob(
                    workflow_id=workflow.id,
                    tenant_id=workflow.tenant_id,
                    step_attempt_id=attempt.id,
                    capability="avatar.render",
                    provider=provider_name,
                    external_job_id=external_job_id,
                    idempotency_key=external_job_id,
                    status="submitting",
                    request_payload={
                        "capability": "avatar.render",
                        "execution_mode": payload.get("selected_execution"),
                        "quality": payload.get("quality"),
                        "aspect_ratio": payload.get("aspect_ratio"),
                        "route_policy_version": payload.get("route_policy_version"),
                    },
                )
                session.add(job)
                workflow.status = WorkflowStatus.running
                workflow.progress = 20
                workflow.next_wakeup_at = now
                await session.commit()

            if job is None:
                raise RuntimeError("数字人步骤缺少 ProviderJob")
            provider = provider_registry.get_provider(job.provider)
            if job.created_at:
                created_at = job.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                if datetime.now(UTC) - created_at > timedelta(seconds=provider.timeout_seconds):
                    raise TimeoutError(f"{job.provider} 渲染超过 {int(provider.timeout_seconds)} 秒")
            if job.status == "submitting":
                submission = await provider.submit_render(
                    external_job_id=job.external_job_id,
                    request=AvatarRenderInput(
                        script=payload.get("script") or "",
                        audio_path=payload["audio_path"],
                        video_path=payload["avatar_video_path"],
                        aspect_ratio=payload.get("aspect_ratio") or "9:16",
                        quality=payload.get("quality") or "720p",
                        provider_options=payload.get("provider_options") or {},
                    ),
                )
                job.external_job_id = submission.external_job_id
                job.status = "submitted"
                job.response_payload = submission.raw
                workflow.status = WorkflowStatus.waiting_provider
                schedule_workflow_wakeup(
                    session,
                    workflow,
                    poll_number=0,
                    delay_seconds=settings.duix_poll_interval_seconds,
                )
                return

            workflow.status = WorkflowStatus.waiting_provider
            provider_status = await provider.query_render(job.external_job_id)
            previous_payload = job.response_payload or {}
            poll_number = int(previous_payload.get("_xingliu_poll_number", 0)) + 1
            raw = dict(provider_status.raw)
            raw["_xingliu_poll_number"] = poll_number
            job.status = provider_status.state.value
            job.response_payload = raw
            render_step.progress = provider_status.progress
            workflow.progress = 20 + int(provider_status.progress * 0.65)

            if (
                job.provider == "duix"
                and raw.get("code") == 10004
                and poll_number >= settings.duix_missing_job_poll_limit
            ):
                raise RuntimeError(
                    f"Duix 连续 {poll_number} 次返回任务不存在，停止无限轮询"
                )

            if provider_status.state == ProviderJobState.succeeded:
                await finish_step_attempt(
                    session,
                    workflow,
                    "avatar_render",
                    status=StepStatus.succeeded,
                    output_payload={"provider_job_id": job.id},
                )
                await start_step_attempt(session, workflow, "persist_result", {})
                workflow.output_payload = {
                    "provider": job.provider,
                    "execution_mode": payload.get("selected_execution"),
                    "route_policy_version": payload.get("route_policy_version"),
                    "provider_job_id": job.external_job_id,
                    "result_path": provider_status.result_path,
                    "artifact_path": (
                        provider_result_to_asset_path(provider_status.result_path)
                        if job.provider == "duix"
                        else None
                    ),
                    "result_url": (
                        provider_status.result_path
                        if provider_status.result_path and "://" in provider_status.result_path
                        else None
                    ),
                }
                await finish_step_attempt(
                    session,
                    workflow,
                    "persist_result",
                    status=StepStatus.succeeded,
                    output_payload={"stored": True},
                )
                workflow.status = WorkflowStatus.succeeded
                workflow.progress = 100
                workflow.next_wakeup_at = None
                await persist_avatar_artifact(session, workflow, job)
                notify_agent(session, workflow, suffix="succeeded")
                logger.info("workflow %s succeeded", workflow.id)
                return
            if provider_status.state == ProviderJobState.failed:
                raise RuntimeError(provider_status.message or f"{job.provider} 渲染失败")

            schedule_workflow_wakeup(
                session,
                workflow,
                poll_number=poll_number,
                delay_seconds=settings.duix_poll_interval_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            await fail_workflow(session, workflow, exc)
        finally:
            workflow.lease_owner = None
            workflow.lease_expires_at = None
            await session.commit()


async def recover_due_work() -> tuple[list[str], list[tuple[str, ProductionOrderStatus]]]:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        workflow_result = await session.execute(
            select(WorkflowRun.id)
            .where(
                WorkflowRun.status.in_(
                    [
                        WorkflowStatus.queued,
                        WorkflowStatus.running,
                        WorkflowStatus.waiting_provider,
                        WorkflowStatus.retry_wait,
                        WorkflowStatus.canceling,
                    ]
                ),
                or_(WorkflowRun.next_wakeup_at.is_(None), WorkflowRun.next_wakeup_at <= now),
                or_(WorkflowRun.lease_expires_at.is_(None), WorkflowRun.lease_expires_at <= now),
            )
            .order_by(WorkflowRun.updated_at)
            .limit(20)
        )
        order_result = await session.execute(
            select(ProductionOrder.id, ProductionOrder.status)
            .where(
                ProductionOrder.status.in_(
                    [
                        ProductionOrderStatus.queued,
                        ProductionOrderStatus.running,
                        ProductionOrderStatus.canceling,
                    ]
                )
            )
            .order_by(ProductionOrder.updated_at)
            .limit(20)
        )
        return list(workflow_result.scalars()), list(order_result.all())


def parse_envelope(raw: str, default_topic: str) -> dict[str, Any]:
    try:
        envelope = json.loads(raw)
        if isinstance(envelope, dict) and envelope.get("topic"):
            return envelope
    except json.JSONDecodeError:
        pass
    return {"topic": default_topic, "aggregate_id": raw, "payload": {"workflow_id": raw}}


async def dispatch_envelope(envelope: dict[str, Any]) -> None:
    topic = str(envelope.get("topic") or "")
    payload = envelope.get("payload") or {}
    if topic.startswith("workflow."):
        workflow_id = str(payload.get("workflow_id") or envelope.get("aggregate_id"))
        await run_workflow_once(workflow_id)
    elif topic == "agent.operation.requested":
        operation_id = str(payload.get("agent_operation_id") or envelope.get("aggregate_id"))
        await run_agent_operation_once(operation_id, worker_id)
    elif topic in {"agent.run.requested", "agent.cancel.requested"}:
        order_id = str(payload.get("production_order_id") or envelope.get("aggregate_id"))
        await run_agent_once(order_id, payload.get("agent_run_id"))


async def main() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("runtime worker %s listening", worker_id)
    last_recovery = 0.0
    try:
        while True:
            async with SessionLocal() as session:
                await publish_outbox_batch(session, redis, settings)
            item = await redis.blpop([settings.agent_queue, settings.workflow_queue], timeout=2)
            if item:
                default_topic = "agent.run.requested" if item[0] == settings.agent_queue else "workflow.run.requested"
                try:
                    await dispatch_envelope(parse_envelope(item[1], default_topic))
                except Exception:  # noqa: BLE001
                    logger.exception("runtime envelope failed")

            clock = asyncio.get_running_loop().time()
            if clock - last_recovery >= settings.runtime_recovery_interval_seconds:
                workflow_ids, orders = await recover_due_work()
                operation_ids = await list_due_agent_operation_ids()
                for workflow_id in workflow_ids:
                    await run_workflow_once(workflow_id)
                for operation_id in operation_ids:
                    await run_agent_operation_once(operation_id, worker_id)
                for order_id, _ in orders:
                    await run_agent_once(order_id)
                last_recovery = clock
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
