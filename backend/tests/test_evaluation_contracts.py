import pytest
from pydantic import ValidationError

from app.agent.evaluation import (
    EvaluationAction,
    EvaluationResult,
    EvaluatorDefinition,
)
from app.evaluators.registry import EvaluatorRegistry, get_evaluator_registry


class AlwaysPassEvaluator:
    async def evaluate(self, context):
        return EvaluationResult(passed=True, action=EvaluationAction.accept)


def test_evaluation_result_keeps_action_consistent_with_pass_state() -> None:
    with pytest.raises(ValidationError):
        EvaluationResult(passed=False, action=EvaluationAction.accept)


def test_evaluator_registry_rejects_duplicate_keys() -> None:
    registry = EvaluatorRegistry()
    definition = EvaluatorDefinition(
        key="quality.example",
        version="1.0.0",
        label="示例评价器",
    )
    registry.register(definition, AlwaysPassEvaluator())

    with pytest.raises(ValueError, match="重复注册"):
        registry.register(definition, AlwaysPassEvaluator())


def test_all_builtin_plan_evaluators_have_real_handlers() -> None:
    registry = get_evaluator_registry()
    expected = {
        "intent_completeness_v1",
        "strategy_quality_v1",
        "script_quality_v1",
        "audio_quality_v1",
        "avatar_quality_v1",
        "video_quality_v1",
        "delivery_completeness_v1",
    }

    assert all(registry.resolve(key) is not None for key in expected)
