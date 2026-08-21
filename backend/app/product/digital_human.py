from typing import Any

from app.agent.contracts import AgentIntentSpec, AgentPlanSpec
from app.product.base import AssetInputDefinition
from app.product.digital_human_plan import (
    build_digital_human_plan,
    build_intent_spec,
)
from app.product.registry import ProductRegistry
from app.schemas.agent import ProductionOrderCreate


class DigitalHumanProduct:
    key = "digital_human.video"
    label = "数字人口播视频"
    asset_inputs = (
        AssetInputDefinition(
            input_key="audio_asset_id",
            role="voice_audio",
            runtime_key="audio_path",
            media_type_prefix="audio/",
        ),
        AssetInputDefinition(
            input_key="avatar_asset_id",
            role="avatar_reference",
            runtime_key="avatar_video_path",
            media_type_prefix="video/",
        ),
    )

    def build_intent(self, payload: ProductionOrderCreate) -> AgentIntentSpec:
        return build_intent_spec(payload)

    def build_fallback_plan(
        self,
        payload: ProductionOrderCreate,
        intent: AgentIntentSpec,
        *,
        available_capabilities: set[str],
    ) -> AgentPlanSpec:
        return build_digital_human_plan(
            payload,
            intent,
            available_capabilities=available_capabilities,
        )

    def planner_context(self, payload: ProductionOrderCreate) -> dict[str, Any]:
        return {
            "product": self.key,
            "automation_mode": payload.automation_mode,
            "checkpoint_policy": payload.checkpoint_policy,
            "max_auto_rework": payload.max_auto_rework,
        }

    def validate_resume_inputs(self, inputs: dict[str, Any]) -> None:
        required = {
            "script": bool(inputs.get("script")),
            "audio": bool(inputs.get("audio_path")),
            "avatar": bool(inputs.get("avatar_video_path")),
        }
        missing = [key for key, present in required.items() if not present]
        if missing:
            labels = {
                "script": "口播脚本",
                "audio": "配音素材",
                "avatar": "数字人参考视频",
            }
            raise ValueError("请同时补齐：" + "、".join(labels[key] for key in missing))


def register_digital_human_product(registry: ProductRegistry) -> None:
    registry.register(DigitalHumanProduct())
