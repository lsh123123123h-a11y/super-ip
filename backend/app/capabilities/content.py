from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.brain import BrainPort, StructuredBrainRequest
from app.agent.contracts import ArtifactDraft, CapabilityOutcome, OutcomeStatus
from app.capabilities.base import CapabilityContext
from app.integrations.new_api_brain import (
    BrainConfigurationError,
    BrainGatewayError,
)


class ContentStrategyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: str = Field(min_length=1)
    angle: str = Field(min_length=1)
    core_message: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)
    structure: list[dict[str, str]] = Field(min_length=1)
    tone: str = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)


class GeneratedContentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    body_markdown: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    calls_to_action: list[str] = Field(default_factory=list)
    factual_claims: list[str] = Field(default_factory=list)


class GeneratedScriptDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    text: str = Field(min_length=1)
    sections: list[dict[str, str]] = Field(default_factory=list)
    calls_to_action: list[str] = Field(default_factory=list)
    factual_claims: list[str] = Field(default_factory=list)


class _BrainContentCapability:
    purpose: str
    system_instruction: str
    output_model: type[BaseModel]
    artifact_type: str

    def __init__(self, brain: BrainPort) -> None:
        self.brain = brain

    def output_model_for(self, context: CapabilityContext) -> type[BaseModel]:
        return self.output_model

    def artifact_type_for(self, context: CapabilityContext) -> str:
        return self.artifact_type

    async def execute(self, context: CapabilityContext) -> CapabilityOutcome:
        output_model = self.output_model_for(context)
        try:
            response = await self.brain.complete_structured(
                StructuredBrainRequest(
                    purpose=self.purpose,
                    system_instruction=self.system_instruction,
                    user_input={
                        "intent": context.order.intent_spec,
                        "inputs": _public_inputs(context.inputs),
                        "artifacts": context.artifacts,
                        "evaluation_feedback": context.evaluation_feedback or [],
                        "expected_artifact": context.step.expected_artifact,
                    },
                    output_schema=output_model.model_json_schema(),
                    metadata={
                        "production_order_id": context.order.id,
                        "plan_version_id": context.plan.id,
                        "step_key": context.step.key,
                    },
                )
            )
            draft = output_model.model_validate(response.output)
        except BrainConfigurationError as exc:
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                error_code="BRAIN_NOT_CONFIGURED",
                message=str(exc),
            )
        except BrainGatewayError as exc:
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                retryable=True,
                error_code="BRAIN_GATEWAY_ERROR",
                message=str(exc),
            )
        except ValidationError as exc:
            return CapabilityOutcome(
                status=OutcomeStatus.failed,
                error_code="INVALID_BRAIN_OUTPUT",
                message=f"模型返回内容不符合能力合同：{exc.errors()[0]['msg']}",
            )

        return CapabilityOutcome(
            status=OutcomeStatus.succeeded,
            artifact=ArtifactDraft(
                artifact_key=context.step.expected_artifact,
                artifact_type=self.artifact_type_for(context),
                content_payload=draft.model_dump(mode="json"),
                lineage_payload={
                    "source": "brain",
                    "capability": context.step.capability,
                    "model_ref": response.model_ref,
                    "gateway_ref": response.gateway_ref,
                    "usage": response.usage,
                    "input_artifacts": sorted(context.artifacts),
                    "execution_attempt": context.execution_attempt,
                },
            ),
        )

    async def interrupt(
        self,
        context: CapabilityContext,
        external_execution_id: str | None,
    ) -> None:
        return None


class ContentStrategyCapability(_BrainContentCapability):
    purpose = "content_strategy"
    system_instruction = (
        "你是产品内部的内容策略能力。根据目标、平台、约束和已有产物形成可执行策略，"
        "不得虚构事实或输出模型、Provider、外部执行器等基础设施信息。"
    )
    output_model = ContentStrategyDraft
    artifact_type = "content_strategy"


class ContentGenerateCapability(_BrainContentCapability):
    purpose = "content_generate"
    system_instruction = (
        "你是产品内部的内容生成能力。严格依据意图和上游策略产物生成可发布草稿；"
        "不确定的事实必须避免断言，并把需要核验的事实列入 factual_claims。"
    )
    output_model = GeneratedContentDraft
    artifact_type = "content_draft"

    def output_model_for(self, context: CapabilityContext) -> type[BaseModel]:
        if context.step.expected_artifact in {"script", "voiceover_script"}:
            return GeneratedScriptDraft
        return GeneratedContentDraft

    def artifact_type_for(self, context: CapabilityContext) -> str:
        if context.step.expected_artifact in {"script", "voiceover_script"}:
            return "script"
        return "content_draft"


def _public_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in inputs.items() if not key.startswith("_")}
