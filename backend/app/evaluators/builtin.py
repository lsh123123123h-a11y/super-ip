from app.agent.evaluation import (
    EvaluationAction,
    EvaluationResult,
    EvaluatorDefinition,
)
from app.evaluators.base import EvaluationContext
from app.evaluators.registry import EvaluatorRegistry


class ArtifactContractEvaluator:
    """Minimum deterministic gate until a domain/Brain evaluator is installed."""

    async def evaluate(self, context: EvaluationContext) -> EvaluationResult:
        artifact = context.artifact_version
        if artifact is None:
            return EvaluationResult(
                passed=False,
                action=EvaluationAction.rework,
                score_payload={"artifact_present": 0},
                issues=[
                    {
                        "code": "EXPECTED_ARTIFACT_MISSING",
                        "artifact_key": context.step.expected_artifact,
                    }
                ],
                feedback=f"缺少预期产物 {context.step.expected_artifact}",
            )
        return EvaluationResult(
            passed=True,
            action=EvaluationAction.accept,
            score_payload={"artifact_present": 1},
        )


def register_builtin_evaluators(registry: EvaluatorRegistry) -> None:
    aliases = {
        "intent_completeness_v1": "目标完整性",
        "intent_v1": "目标完整性",
        "strategy_quality_v1": "策略质量",
        "script_quality_v1": "脚本质量",
        "audio_quality_v1": "音频可用性",
        "avatar_quality_v1": "数字人成片可用性",
        "avatar_v1": "数字人成片可用性",
        "video_quality_v1": "视频质量",
        "delivery_completeness_v1": "交付完整性",
    }
    for key, label in aliases.items():
        registry.register(
            EvaluatorDefinition(key=key, version="1.0.0", label=label),
            ArtifactContractEvaluator(),
            source="builtin.contract",
        )
