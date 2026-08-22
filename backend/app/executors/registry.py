from functools import lru_cache

from app.agent.executor import AgentExecutorPort
from app.agent.operations import ExecutorDefinition
from app.core.config import get_settings
from app.core.extensions import load_registrar_modules
from app.core.versioning import version_sort_key


class ExecutorRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], ExecutorDefinition] = {}
        self._executors: dict[tuple[str, str], AgentExecutorPort] = {}

    def register(
        self,
        definition: ExecutorDefinition,
        executor: AgentExecutorPort | None = None,
    ) -> None:
        registration = (definition.key, definition.version)
        if registration in self._definitions:
            raise ValueError(f"Executor 重复注册：{definition.key}@{definition.version}")
        self._definitions[registration] = definition
        if executor is not None:
            self._executors[registration] = executor

    def definition(
        self,
        key: str,
        version: str | None = None,
    ) -> ExecutorDefinition | None:
        if version is not None:
            return self._definitions.get((key, version))
        versions = [
            item
            for (registered_key, _), item in self._definitions.items()
            if registered_key == key
        ]
        return max(versions, key=lambda item: version_sort_key(item.version), default=None)

    def executor(
        self,
        key: str,
        version: str | None = None,
    ) -> AgentExecutorPort | None:
        definition = self.definition(key, version)
        if definition is None:
            return None
        return self._executors.get((definition.key, definition.version))

    def catalog(self) -> list[ExecutorDefinition]:
        keys = sorted({key[0] for key in self._definitions})
        return [item for key in keys if (item := self.definition(key)) is not None]

    def installed_catalog(self) -> list[ExecutorDefinition]:
        keys = sorted({key[0] for key in self._executors})
        return [
            item
            for key in keys
            if (item := self.definition(key)) is not None
            and (item.key, item.version) in self._executors
        ]

    def select_for(self, operation_key: str) -> str | None:
        candidates = [
            definition.key
            for registration, definition in self._definitions.items()
            if registration in self._executors
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
