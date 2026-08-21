from functools import lru_cache

from app.agent.executor import AgentExecutorPort
from app.agent.operations import ExecutorDefinition


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


@lru_cache
def get_executor_registry() -> ExecutorRegistry:
    # Concrete Harness adapters are registered by the deployment composition root.
    return ExecutorRegistry()
