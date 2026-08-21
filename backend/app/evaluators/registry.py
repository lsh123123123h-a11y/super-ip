from dataclasses import dataclass
from functools import lru_cache

from app.agent.evaluation import EvaluatorDefinition
from app.core.config import get_settings
from app.core.extensions import load_registrar_modules
from app.evaluators.base import QualityEvaluator


@dataclass(frozen=True, slots=True)
class EvaluatorRegistration:
    definition: EvaluatorDefinition
    evaluator: QualityEvaluator
    source: str


class EvaluatorRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, EvaluatorRegistration] = {}

    def register(
        self,
        definition: EvaluatorDefinition,
        evaluator: QualityEvaluator,
        *,
        source: str = "application",
    ) -> None:
        if definition.key in self._registrations:
            raise ValueError(f"评价器重复注册：{definition.key}")
        self._registrations[definition.key] = EvaluatorRegistration(
            definition=definition,
            evaluator=evaluator,
            source=source,
        )

    def resolve(self, key: str) -> EvaluatorRegistration | None:
        return self._registrations.get(key)

    def catalog(self) -> list[EvaluatorDefinition]:
        return [
            self._registrations[key].definition
            for key in sorted(self._registrations)
        ]


@lru_cache
def get_evaluator_registry() -> EvaluatorRegistry:
    registry = EvaluatorRegistry()
    from app.evaluators.builtin import register_builtin_evaluators

    register_builtin_evaluators(registry)
    load_registrar_modules(
        get_settings().extension_modules("evaluator"),
        hook_name="register_evaluators",
        registry=registry,
    )
    return registry
