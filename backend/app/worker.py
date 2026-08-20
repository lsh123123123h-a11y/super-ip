import asyncio
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import SessionLocal, create_schema
from app.models.orchestration import ProviderJob, StepStatus, WorkflowRun, WorkflowStatus
from app.providers.base import ProviderJobState
from app.providers.duix import DuixProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("xingliu.worker")
settings = get_settings()


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


async def set_step(workflow: WorkflowRun, key: str, status: StepStatus, progress: int) -> None:
    step = next(item for item in workflow.steps if item.step_key == key)
    step.status = status
    step.progress = progress
    if status == StepStatus.running:
        step.attempt += 1
        step.started_at = datetime.now(UTC)
    if status in {StepStatus.succeeded, StepStatus.failed, StepStatus.skipped}:
        step.finished_at = datetime.now(UTC)


async def run_workflow(workflow_id: str) -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.id == workflow_id)
            .options(selectinload(WorkflowRun.steps), selectinload(WorkflowRun.provider_jobs))
            .with_for_update()
        )
        workflow = result.scalar_one_or_none()
        if workflow is None or workflow.status not in {WorkflowStatus.queued, WorkflowStatus.failed_retryable}:
            return

        try:
            workflow.status = WorkflowStatus.running
            workflow.progress = 5
            await set_step(workflow, "validate", StepStatus.running, 25)
            await session.commit()

            payload = workflow.input_payload
            if not payload.get("audio_path") or not payload.get("avatar_video_path"):
                raise ValueError("缺少 Duix 所需的音频或数字人参考视频")
            await set_step(workflow, "validate", StepStatus.succeeded, 100)

            await set_step(workflow, "avatar_render", StepStatus.running, 1)
            workflow.status = WorkflowStatus.waiting_provider
            workflow.progress = 20
            provider = DuixProvider(settings)
            render_step = next(item for item in workflow.steps if item.step_key == "avatar_render")
            external_job_id = f"{workflow.id}-{render_step.attempt}"
            submission = await provider.submit_render(
                external_job_id=external_job_id,
                audio_path=payload["audio_path"],
                video_path=payload["avatar_video_path"],
            )
            job = ProviderJob(
                workflow_id=workflow.id,
                provider="duix",
                external_job_id=submission.external_job_id,
                status="submitted",
                request_payload={"audio_path": payload["audio_path"], "video_path": payload["avatar_video_path"]},
                response_payload=submission.raw,
            )
            session.add(job)
            await session.commit()

            started = asyncio.get_running_loop().time()
            missing_job_polls = 0
            while True:
                provider_status = await provider.query_render(submission.external_job_id)
                if provider_status.raw.get("code") == 10004:
                    missing_job_polls += 1
                    if missing_job_polls > settings.duix_missing_job_poll_limit:
                        raise RuntimeError("Duix 未找到已提交的任务")
                else:
                    missing_job_polls = 0
                job.status = provider_status.state.value
                job.response_payload = provider_status.raw
                step = next(item for item in workflow.steps if item.step_key == "avatar_render")
                step.progress = provider_status.progress
                workflow.progress = 20 + int(provider_status.progress * 0.65)
                await session.commit()

                if provider_status.state == ProviderJobState.succeeded:
                    await set_step(workflow, "avatar_render", StepStatus.succeeded, 100)
                    await set_step(workflow, "persist_result", StepStatus.running, 50)
                    workflow.output_payload = {
                        "provider": "duix",
                        "provider_job_id": submission.external_job_id,
                        "result_path": provider_status.result_path,
                        "artifact_path": provider_result_to_asset_path(provider_status.result_path),
                        "result_url": (
                            provider_status.result_path
                            if provider_status.result_path and "://" in provider_status.result_path
                            else None
                        ),
                    }
                    await set_step(workflow, "persist_result", StepStatus.succeeded, 100)
                    workflow.status = WorkflowStatus.succeeded
                    workflow.progress = 100
                    await session.commit()
                    logger.info("workflow %s succeeded", workflow.id)
                    return
                if provider_status.state == ProviderJobState.failed:
                    raise RuntimeError(provider_status.message or "Duix 渲染失败")
                if asyncio.get_running_loop().time() - started > settings.duix_timeout_seconds:
                    raise TimeoutError("Duix 渲染超时")
                await asyncio.sleep(settings.duix_poll_interval_seconds)
        except Exception as exc:
            logger.exception("workflow %s failed", workflow_id)
            attempts = max((step.attempt for step in workflow.steps), default=1)
            workflow.status = (
                WorkflowStatus.failed_final
                if attempts >= settings.max_workflow_attempts
                else WorkflowStatus.failed_retryable
            )
            workflow.error_code = exc.__class__.__name__
            workflow.error_message = str(exc)
            for step in workflow.steps:
                if step.status == StepStatus.running:
                    step.status = StepStatus.failed
                    step.error_message = str(exc)
                    step.finished_at = datetime.now(UTC)
            await session.commit()


async def main() -> None:
    await create_schema()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("worker listening on %s", settings.workflow_queue)
    while True:
        item = await redis.blpop(settings.workflow_queue, timeout=5)
        if item:
            await run_workflow(item[1])


if __name__ == "__main__":
    asyncio.run(main())
