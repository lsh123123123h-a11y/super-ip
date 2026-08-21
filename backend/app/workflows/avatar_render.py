import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.agent import (
    AgentEvent,
    Artifact,
    ArtifactVersion,
    ArtifactVersionStatus,
    ProductionOrder,
)
from app.models.orchestration import (
    ProviderJob,
    StepStatus,
    WorkflowRun,
    WorkflowStatus,
)
from app.providers.base import ProviderExecutionRequest, ProviderJobState
from app.schemas.workflows import DigitalHumanRenderRequest
from app.workflows.base import (
    WorkflowContext,
    WorkflowDefinition,
    WorkflowStepDefinition,
    finish_step_attempt,
    notify_agent,
    schedule_wakeup,
    start_step_attempt,
    step_by_key,
)
from app.workflows.registry import WorkflowRegistry


logger = logging.getLogger("xingliu.workflow.avatar")


class AvatarRenderWorkflow:
    async def run(self, context: WorkflowContext) -> None:
        workflow = context.workflow
        payload = workflow.input_payload
        now = datetime.now(UTC)

        validate_step = step_by_key(workflow, "validate")
        if validate_step.status != StepStatus.succeeded:
            await start_step_attempt(context, "validate", {})
            if not payload.get("audio_path") or not payload.get("avatar_video_path"):
                raise ValueError("缺少数字人渲染所需的音频或参考视频")
            await finish_step_attempt(
                context,
                "validate",
                status=StepStatus.succeeded,
                output_payload={"valid": True},
            )
            workflow.progress = 10

        render_step = step_by_key(workflow, "avatar_render")
        job = (
            max(
                workflow.provider_jobs,
                key=lambda item: item.created_at or now,
                default=None,
            )
            if render_step.status in {StepStatus.running, StepStatus.succeeded}
            else None
        )
        if render_step.status != StepStatus.succeeded and job is None:
            attempt = await start_step_attempt(
                context,
                "avatar_render",
                {"capability": workflow.capability},
            )
            provider_name = str(payload.get("selected_provider") or "")
            if not provider_name:
                raise RuntimeError("Workflow 缺少已持久化的 Provider 路由结果")
            external_job_id = f"{workflow.id}-{render_step.attempt}"
            job = ProviderJob(
                workflow_id=workflow.id,
                tenant_id=workflow.tenant_id,
                step_attempt_id=attempt.id,
                capability=workflow.capability,
                provider=provider_name,
                external_job_id=external_job_id,
                idempotency_key=external_job_id,
                status="submitting",
                request_payload={
                    "capability": workflow.capability,
                    "execution_mode": payload.get("selected_execution"),
                    "quality": payload.get("quality"),
                    "aspect_ratio": payload.get("aspect_ratio"),
                    "route_policy_version": payload.get("route_policy_version"),
                },
            )
            context.session.add(job)
            workflow.status = WorkflowStatus.running
            workflow.progress = 20
            workflow.next_wakeup_at = now
            await context.session.commit()

        if job is None:
            raise RuntimeError("数字人步骤缺少 ProviderJob")
        provider = context.providers.get_provider(
            job.provider,
            capability=workflow.capability,
        )
        descriptor = provider.descriptor()
        if job.created_at:
            created_at = job.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - created_at > timedelta(
                seconds=provider.timeout_seconds
            ):
                raise TimeoutError(
                    f"{job.provider} 执行超过 {int(provider.timeout_seconds)} 秒"
                )
        if job.status == "submitting":
            submission = await provider.submit(
                external_job_id=job.external_job_id,
                request=ProviderExecutionRequest(
                    capability=workflow.capability,
                    inputs=payload,
                    provider_options=payload.get("provider_options") or {},
                ),
            )
            job.external_job_id = submission.external_job_id
            job.status = "submitted"
            job.response_payload = submission.raw
            workflow.status = WorkflowStatus.waiting_provider
            schedule_wakeup(
                context,
                wakeup_key="poll:0",
                delay_seconds=descriptor.poll_interval_seconds,
            )
            return

        workflow.status = WorkflowStatus.waiting_provider
        provider_status = await provider.query(
            job.external_job_id,
            capability=workflow.capability,
        )
        previous_payload = job.response_payload or {}
        poll_number = int(previous_payload.get("_xingliu_poll_number", 0)) + 1
        raw = dict(provider_status.raw)
        raw["_xingliu_poll_number"] = poll_number
        job.status = provider_status.state.value
        job.response_payload = raw
        render_step.progress = provider_status.progress
        workflow.progress = 20 + int(provider_status.progress * 0.65)

        if (
            provider_status.transient_error_code
            and provider_status.max_transient_polls is not None
            and poll_number >= provider_status.max_transient_polls
        ):
            raise RuntimeError(
                f"{job.provider} 连续 {poll_number} 次返回"
                f" {provider_status.transient_error_code}，停止轮询"
            )

        if provider_status.state == ProviderJobState.succeeded:
            await finish_step_attempt(
                context,
                "avatar_render",
                status=StepStatus.succeeded,
                output_payload={"provider_job_id": job.id},
            )
            await start_step_attempt(context, "persist_result", {})
            workflow.output_payload = {
                "provider": job.provider,
                "execution_mode": payload.get("selected_execution"),
                "route_policy_version": payload.get("route_policy_version"),
                "provider_job_id": job.external_job_id,
                "result_path": provider_status.result_path,
                "artifact_path": provider_status.artifact_path,
                "result_url": provider_status.result_url,
            }
            await finish_step_attempt(
                context,
                "persist_result",
                status=StepStatus.succeeded,
                output_payload={"stored": True},
            )
            workflow.status = WorkflowStatus.succeeded
            workflow.progress = 100
            workflow.next_wakeup_at = None
            await self._persist_artifact(context, job)
            notify_agent(context, suffix="succeeded")
            logger.info("workflow %s succeeded", workflow.id)
            return
        if provider_status.state == ProviderJobState.failed:
            raise RuntimeError(
                provider_status.message or f"{job.provider} 执行失败"
            )

        schedule_wakeup(
            context,
            wakeup_key=f"poll:{poll_number}",
            delay_seconds=descriptor.poll_interval_seconds,
        )

    async def fail(self, context: WorkflowContext, exc: Exception) -> None:
        workflow = context.workflow
        logger.error("workflow %s failed: %s", workflow.id, exc, exc_info=True)
        failure_attempt = max((step.attempt for step in workflow.steps), default=0)
        workflow.status = (
            WorkflowStatus.failed_final
            if failure_attempt >= context.settings.max_workflow_attempts
            else WorkflowStatus.failed_retryable
        )
        workflow.error_code = exc.__class__.__name__
        workflow.error_message = str(exc)
        workflow.next_wakeup_at = None
        for step in workflow.steps:
            if step.status == StepStatus.running:
                await finish_step_attempt(
                    context,
                    step.step_key,
                    status=StepStatus.failed,
                    error=exc,
                )
        notify_agent(context, suffix=f"failed:{failure_attempt}")

    async def cancel(self, context: WorkflowContext) -> None:
        context.workflow.status = WorkflowStatus.canceled
        context.workflow.next_wakeup_at = None

    async def _persist_artifact(
        self,
        context: WorkflowContext,
        job: ProviderJob,
    ) -> None:
        workflow = context.workflow
        if not workflow.production_order_id or not workflow.tenant_id:
            return
        order = await context.session.get(
            ProductionOrder,
            workflow.production_order_id,
        )
        if order is None:
            return
        artifact = await context.session.scalar(
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
            context.session.add(artifact)
            await context.session.flush()
        latest_version = await context.session.scalar(
            select(ArtifactVersion.version)
            .where(ArtifactVersion.artifact_id == artifact.id)
            .order_by(ArtifactVersion.version.desc())
            .limit(1)
        )
        output = workflow.output_payload or {}
        version = ArtifactVersion(
            tenant_id=workflow.tenant_id,
            artifact_id=artifact.id,
            plan_version_id=workflow.plan_version_id,
            version=int(latest_version or 0) + 1,
            status=ArtifactVersionStatus.candidate,
            content_payload={
                "media_ref": {
                    "kind": "workflow_result",
                    "workflow_id": workflow.id,
                    "download_available": bool(output.get("artifact_path")),
                    "remote_available": bool(output.get("result_url")),
                }
            },
            lineage_payload={
                "workflow_id": workflow.id,
                "provider_job_id": job.id,
                "plan_version_id": workflow.plan_version_id,
            },
        )
        context.session.add(version)
        await context.session.flush()
        context.session.add(
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


def register_avatar_workflow(registry: WorkflowRegistry) -> None:
    registry.register(
        WorkflowDefinition(
            task_type="digital_human.render",
            capability="avatar.render",
            version="1.0.0",
            input_model=DigitalHumanRenderRequest,
            steps=(
                WorkflowStepDefinition("validate", "检查素材"),
                WorkflowStepDefinition(
                    "avatar_render",
                    "数字人渲染",
                    capability="avatar.render",
                    expected_artifact="avatar_video",
                    depends_on=("validate",),
                ),
                WorkflowStepDefinition(
                    "persist_result",
                    "保存成片",
                    depends_on=("avatar_render",),
                ),
            ),
            handler=AvatarRenderWorkflow(),
        )
    )
