from functools import lru_cache

from app.agent.executor import AgentExecutorPort
from app.agent.operations import ExecutorDefinition
from app.core.config import get_settings
from app.core.extensions import load_registrar_modules


class ExecutorRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ExecutorDefinition] = {}
        self._executors: dict[str, AgentExecutorPort] = {}

    def register(
        self,
        definition: ExecutorDefinition,
        executor: AgentExecutorPort | None = None,
    ) -> None:
        if definition.key in self._definitions:
            raise ValueError(f"Executor 重复注册：{definition.key}")
        self._definitions[definition.key] = definition
        if executor is not None:
            self._executors[definition.key] = executor

    def definition(self, key: str) -> ExecutorDefinition | None:
        return self._definitions.get(key)

    def executor(self, key: str) -> AgentExecutorPort | None:
        return self._executors.get(key)

    def catalog(self) -> list[ExecutorDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]

    def installed_catalog(self) -> list[ExecutorDefinition]:
        return [
            self._definitions[key]
            for key in sorted(self._executors)
            if key in self._definitions
        ]

    def select_for(self, operation_key: str) -> str | None:
        candidates = [
            key
            for key, definition in self._definitions.items()
            if key in self._executors
            and operation_key in definition.supported_operations
        ]
        return sorted(candidates)[0] if candidates else None


@lru_cache
def get_executor_registry() -> ExecutorRegistry:
    registry = ExecutorRegistry()
    load_registrar_modules(
        get_settings().extension_modules("executor"),
        hook_name="register_executors",
        registry=registry,
    )
    return registry
