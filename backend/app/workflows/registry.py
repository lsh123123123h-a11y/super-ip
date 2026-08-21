from functools import lru_cache

from app.core.config import get_settings
from app.core.extensions import load_registrar_modules
from app.workflows.base import WorkflowDefinition


class WorkflowRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, WorkflowDefinition] = {}

    def register(self, definition: WorkflowDefinition) -> None:
        if definition.task_type in self._definitions:
            raise ValueError(f"Workflow 重复注册：{definition.task_type}")
        self._definitions[definition.task_type] = definition

    def resolve(self, task_type: str) -> WorkflowDefinition | None:
        return self._definitions.get(task_type)

    def resolve_capability(self, capability: str) -> WorkflowDefinition | None:
        matches = [
            item for item in self._definitions.values() if item.capability == capability
        ]
        if len(matches) > 1:
            raise ValueError(f"能力 {capability} 存在多个默认 Workflow")
        return matches[0] if matches else None

    def catalog(self) -> list[WorkflowDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]


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
