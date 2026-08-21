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


class ContentStrategyEvaluator:
    async def evaluate(self, context: EvaluationContext) -> EvaluationResult:
        artifact = context.artifact_version
        payload = artifact.content_payload if artifact is not None else {}
        required = ("audience", "angle", "core_message", "hook", "key_points", "structure")
        missing = [key for key in required if not payload.get(key)]
        passed = artifact is not None and not missing
        return EvaluationResult(
            passed=passed,
            action=EvaluationAction.accept if passed else EvaluationAction.rework,
            score_payload={
                "artifact_present": int(artifact is not None),
                "required_fields_present": len(required) - len(missing),
                "required_fields_total": len(required),
            },
            issues=[{"code": "STRATEGY_FIELDS_MISSING", "fields": missing}] if missing else [],
            feedback=("补齐内容策略字段：" + "、".join(missing)) if missing else "",
        )


class ContentDraftEvaluator:
    def __init__(self, *, minimum_length: int = 120) -> None:
        self.minimum_length = minimum_length

    async def evaluate(self, context: EvaluationContext) -> EvaluationResult:
        artifact = context.artifact_version
        payload = artifact.content_payload if artifact is not None else {}
        title = str(payload.get("title") or "").strip()
        body = str(payload.get("body_markdown") or "").strip()
        issues = []
        if not title:
            issues.append({"code": "CONTENT_TITLE_MISSING"})
        if len(body) < self.minimum_length:
            issues.append(
                {
                    "code": "CONTENT_BODY_TOO_SHORT",
                    "minimum_length": self.minimum_length,
                    "actual_length": len(body),
                }
            )
        passed = artifact is not None and not issues
        return EvaluationResult(
            passed=passed,
            action=EvaluationAction.accept if passed else EvaluationAction.rework,
            score_payload={
                "artifact_present": int(artifact is not None),
                "title_present": int(bool(title)),
                "body_length": len(body),
                "minimum_body_length": self.minimum_length,
            },
            issues=issues,
            feedback="请补充完整标题和正文后重新生成" if issues else "",
        )


def register_builtin_evaluators(registry: EvaluatorRegistry) -> None:
    registry.register(
        EvaluatorDefinition(
            key="content_strategy_quality_v1",
            version="1.0.0",
            label="内容策略合同与完整性",
        ),
        ContentStrategyEvaluator(),
        source="builtin.content",
    )
    registry.register(
        EvaluatorDefinition(
            key="content_draft_quality_v1",
            version="1.0.0",
            label="内容草稿基础质量",
        ),
        ContentDraftEvaluator(),
        source="builtin.content",
    )
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
