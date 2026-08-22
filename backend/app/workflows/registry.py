from functools import lru_cache

from app.core.config import get_settings
from app.core.extensions import load_registrar_modules
from app.core.versioning import version_sort_key
from app.workflows.base import WorkflowDefinition


class WorkflowRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], WorkflowDefinition] = {}

    def register(self, definition: WorkflowDefinition) -> None:
        registration = (definition.task_type, definition.version)
        if registration in self._definitions:
            raise ValueError(
                f"Workflow 重复注册：{definition.task_type}@{definition.version}"
            )
        self._definitions[registration] = definition

    def resolve(
        self,
        task_type: str,
        version: str | None = None,
    ) -> WorkflowDefinition | None:
        if version is not None:
            return self._definitions.get((task_type, version))
        matches = [
            definition
            for (registered_type, _), definition in self._definitions.items()
            if registered_type == task_type
        ]
        return max(matches, key=lambda item: version_sort_key(item.version), default=None)

    def resolve_capability(self, capability: str) -> WorkflowDefinition | None:
        task_types = {
            item.task_type
            for item in self._definitions.values()
            if item.capability == capability
        }
        if len(task_types) > 1:
            raise ValueError(f"能力 {capability} 存在多个默认 Workflow")
        if not task_types:
            return None
        return self.resolve(next(iter(task_types)))

    def catalog(self) -> list[WorkflowDefinition]:
        task_types = sorted({key[0] for key in self._definitions})
        return [item for key in task_types if (item := self.resolve(key)) is not None]


@lru_cache
def get_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    from app.workflows.avatar_render import register_avatar_workflow

    register_avatar_workflow(registry)
    load_registrar_modules(
        get_settings().extension_modules("workflow"),
        hook_name="register_workflows",
        registry=registry,
    )
    return registry
