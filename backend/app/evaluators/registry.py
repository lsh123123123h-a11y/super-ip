from dataclasses import dataclass
from functools import lru_cache

from app.agent.evaluation import EvaluatorDefinition
from app.core.config import get_settings
from app.core.extensions import load_registrar_modules
from app.evaluators.base import QualityEvaluator
from app.core.versioning import version_sort_key


@dataclass(frozen=True, slots=True)
class EvaluatorRegistration:
    definition: EvaluatorDefinition
    evaluator: QualityEvaluator
    source: str


class EvaluatorRegistry:
    def __init__(self) -> None:
        self._registrations: dict[tuple[str, str], EvaluatorRegistration] = {}

    def register(
        self,
        definition: EvaluatorDefinition,
        evaluator: QualityEvaluator,
        *,
        source: str = "application",
    ) -> None:
        identity = (definition.key, definition.version)
        if identity in self._registrations:
            raise ValueError(f"评价器重复注册：{definition.key}@{definition.version}")
        self._registrations[identity] = EvaluatorRegistration(
            definition=definition,
            evaluator=evaluator,
            source=source,
        )

    def resolve(
        self,
        key: str,
        version: str | None = None,
    ) -> EvaluatorRegistration | None:
        if version is not None:
            return self._registrations.get((key, version))
        candidates = [
            registration
            for (registered_key, _), registration in self._registrations.items()
            if registered_key == key
        ]
        return max(
            candidates,
            key=lambda item: version_sort_key(item.definition.version),
            default=None,
        )

    def catalog(self) -> list[EvaluatorDefinition]:
        return [
            self.resolve(key).definition
            for key in sorted({key for key, _ in self._registrations})
        ]

    def versions(self, key: str) -> list[str]:
        return sorted(
            [version for registered_key, version in self._registrations if registered_key == key],
            key=version_sort_key,
        )


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
