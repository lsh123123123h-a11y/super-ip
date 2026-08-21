from app.agent.contracts import (
    ArtifactDraft,
    CapabilityOutcome,
    DecisionSpec,
    OutcomeStatus,
)
from app.capabilities.base import CapabilityContext


class IntentNormalizeCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityOutcome:
        return CapabilityOutcome(
            status=OutcomeStatus.succeeded,
            artifact=ArtifactDraft(
                artifact_key="intent_spec",
                artifact_type="intent_spec",
                content_payload=context.order.intent_spec,
                lineage_payload={
                    "source": "production_order",
                    "production_order_id": context.order.id,
                },
            ),
        )

    async def interrupt(
        self,
        context: CapabilityContext,
        external_execution_id: str | None,
    ) -> None:
        return None


class ContentIngestCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityOutcome:
        script = str(context.inputs.get("script") or "").strip()
        if not script:
            return CapabilityOutcome(
                status=OutcomeStatus.awaiting_decision,
                decision=DecisionSpec(
                    reason_code="MISSING_REQUIRED_INPUT",
                    title="补充已确认的口播脚本",
                    summary="当前计划需要一份已确认脚本才能继续。",
                    options=[
                        {"key": "open_assets", "label": "补充脚本与生产素材"},
                        {"key": "cancel_order", "label": "取消生产单"},
                    ],
                    recommended_option="open_assets",
                ),
            )
        return CapabilityOutcome(
            status=OutcomeStatus.succeeded,
            artifact=ArtifactDraft(
                artifact_key="script",
                artifact_type="script",
                content_payload={"text": script},
                lineage_payload={"source": "user_input"},
            ),
        )

    async def interrupt(
        self,
        context: CapabilityContext,
        external_execution_id: str | None,
    ) -> None:
        return None


class AudioEvaluateCapability:
    async def execute(self, context: CapabilityContext) -> CapabilityOutcome:
        asset_id = context.inputs.get("audio_asset_id")
        if not context.inputs.get("audio_path") and not asset_id:
            return CapabilityOutcome(
                status=OutcomeStatus.awaiting_decision,
                decision=DecisionSpec(
                    reason_code="MISSING_REQUIRED_INPUT",
                    title="补充配音素材",
                    summary="当前计划需要配音音频才能继续。",
                    options=[
                        {"key": "open_assets", "label": "补充配音与生产素材"},
                        {"key": "cancel_order", "label": "取消生产单"},
                    ],
                    recommended_option="open_assets",
                ),
            )
        return CapabilityOutcome(
            status=OutcomeStatus.succeeded,
            artifact=ArtifactDraft(
                artifact_key="voice_audio",
                artifact_type="audio",
                content_payload={"asset_id": asset_id},
                lineage_payload={"source": "user_input"},
            ),
        )

    async def interrupt(
        self,
        context: CapabilityContext,
        external_execution_id: str | None,
    ) -> None:
        return None
