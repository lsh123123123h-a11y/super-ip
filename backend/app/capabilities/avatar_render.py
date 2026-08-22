from sqlalchemy import select

from app.agent.contracts import CapabilityOutcome, DecisionSpec, OutcomeStatus
from app.capabilities.base import CapabilityContext
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.schemas.workflows import DigitalHumanRenderRequest
from app.services.avatar_workflow_service import create_avatar_workflow
from app.services.workflow_transitions import transition_workflow


ACTIVE_STATUSES = {
    WorkflowStatus.queued,
    WorkflowStatus.running,
    WorkflowStatus.waiting_provider,
    WorkflowStatus.retry_wait,
}


class AvatarRenderCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityOutcome:
        workflow_key = (
            f"agent:{context.run.id}:{context.step.key}:plan:{context.plan.version}:"
            f"attempt:{context.execution_attempt}"
        )
        workflow = await context.session.scalar(
            select(WorkflowRun)
            .where(
                WorkflowRun.production_order_id == context.order.id,
                WorkflowRun.plan_version_id == context.plan.id,
                WorkflowRun.capability == context.step.capability,
                WorkflowRun.idempotency_key == workflow_key,
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
        if workflow is not None:
            if workflow.status in ACTIVE_STATUSES:
                return CapabilityOutcome(
                    status=OutcomeStatus.waiting,
                    external_execution_id=workflow.id,
                )
            if workflow.status == WorkflowStatus.succeeded:
                return CapabilityOutcome(
                    status=OutcomeStatus.succeeded,
                    external_execution_id=workflow.id,
                )
            if workflow.status in {
                WorkflowStatus.failed_final,
                WorkflowStatus.manual_intervention,
                WorkflowStatus.canceled,
            }:
                return CapabilityOutcome(
                    status=OutcomeStatus.failed,
                    external_execution_id=workflow.id,
                    retryable=False,
                    error_code=workflow.error_code or "CAPABILITY_EXECUTION_FAILED",
                    message=workflow.error_message or "数字人执行未完成",
                )

        script_artifact = context.artifacts.get("script") or {}
        script_content = script_artifact.get("content") or {}
        script = str(
            context.inputs.get("script")
            or script_content.get("text")
            or script_content.get("body_markdown")
            or ""
        ).strip()
        missing = [
            label
            for key, label in (
                ("script", "口播脚本"),
                ("audio_path", "配音音频"),
                ("avatar_video_path", "数字人参考视频"),
            )
            if not (script if key == "script" else context.inputs.get(key))
        ]
        if missing:
            return CapabilityOutcome(
                status=OutcomeStatus.awaiting_decision,
                decision=DecisionSpec(
                    reason_code="MISSING_REQUIRED_ASSET",
                    title="补充数字人生产素材",
                    summary="继续执行需要：" + "、".join(missing) + "。",
                    options=[
                        {"key": "open_assets", "label": "补充所需素材"},
                        {"key": "cancel_order", "label": "取消生产单"},
                    ],
                    recommended_option="open_assets",
                ),
            )

        payload = DigitalHumanRenderRequest(
            script=script,
            avatar_video_path=str(context.inputs["avatar_video_path"]),
            audio_path=str(context.inputs["audio_path"]),
            title=context.order.title,
            aspect_ratio=str(context.inputs.get("aspect_ratio") or "9:16"),
            quality=str(context.inputs.get("quality") or "720p"),
            provider="auto",
            execution_mode="auto",
        )
        workflow, _ = await create_avatar_workflow(
            context.session,
            owner_id=context.order.created_by_user_id,
            tenant_id=context.order.tenant_id,
            idempotency_key=workflow_key,
            payload=payload,
            production_order_id=context.order.id,
            plan_version_id=context.plan.id,
            commit=False,
        )
        return CapabilityOutcome(
            status=OutcomeStatus.dispatched,
            external_execution_id=workflow.id,
        )

    async def interrupt(
        self,
        context: CapabilityContext,
        external_execution_id: str | None,
    ) -> None:
        if not external_execution_id:
            return
        workflow = await context.session.scalar(
            select(WorkflowRun).where(
                WorkflowRun.id == external_execution_id,
                WorkflowRun.production_order_id == context.order.id,
            )
        )
        if workflow is None or workflow.status in {
            WorkflowStatus.succeeded,
            WorkflowStatus.failed_final,
            WorkflowStatus.canceled,
        }:
            return
        transition_workflow(workflow, WorkflowStatus.canceling)
        workflow.fence_token += 1
        workflow.lease_owner = None
        workflow.lease_expires_at = None
        workflow.heartbeat_at = None
