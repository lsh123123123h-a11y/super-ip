from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.agent.contracts import CapabilityDefinition, ExecutionKind
from app.capabilities.base import CapabilityHandler
from app.core.config import get_settings
from app.core.extensions import load_registrar_modules


@dataclass(frozen=True, slots=True)
class CapabilityRegistration:
    definition: CapabilityDefinition
    handler: CapabilityHandler | None = None
    executor_key: str | None = None
    source: str = "application"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def installed(self) -> bool:
        return self.handler is not None or self.executor_key is not None


class CapabilityRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, CapabilityRegistration] = {}

    def register(
        self,
        definition: CapabilityDefinition,
        handler: CapabilityHandler | None = None,
        *,
        executor_key: str | None = None,
        source: str = "application",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if definition.key in self._registrations:
            raise ValueError(f"能力重复注册：{definition.key}")
        if handler is not None and executor_key is not None:
            raise ValueError(f"能力 {definition.key} 不能同时绑定 Handler 和 Executor")
        if executor_key is not None and definition.execution_kind != ExecutionKind.harness:
            raise ValueError(f"只有 harness 能力可以绑定 Executor：{definition.key}")
        self._registrations[definition.key] = CapabilityRegistration(
            definition=definition,
            handler=handler,
            executor_key=executor_key,
            source=source,
            metadata=metadata or {},
        )

    def bind_handler(
        self,
        key: str,
        handler: CapabilityHandler,
        *,
        source: str | None = None,
    ) -> None:
        registration = self._require(key)
        if registration.installed:
            raise ValueError(f"能力已绑定执行入口：{key}")
        self._registrations[key] = CapabilityRegistration(
            definition=registration.definition,
            handler=handler,
            source=source or registration.source,
            metadata=registration.metadata,
        )

    def bind_executor(
        self,
        key: str,
        executor_key: str,
        *,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        registration = self._require(key)
        if registration.installed:
            raise ValueError(f"能力已绑定执行入口：{key}")
        if registration.definition.execution_kind != ExecutionKind.harness:
            raise ValueError(f"只有 harness 能力可以绑定 Executor：{key}")
        self._registrations[key] = CapabilityRegistration(
            definition=registration.definition,
            executor_key=executor_key,
            source=source or registration.source,
            metadata={**registration.metadata, **(metadata or {})},
        )

    def _require(self, key: str) -> CapabilityRegistration:
        registration = self._registrations.get(key)
        if registration is None:
            raise KeyError(key)
        return registration

    def resolve(self, key: str) -> CapabilityRegistration | None:
        return self._registrations.get(key)

    def is_executable(self, key: str) -> bool:
        registration = self.resolve(key)
        if registration is None:
            return False
        if registration.handler is not None:
            return True
        if not registration.executor_key:
            return False
        from app.executors.registry import get_executor_registry

        return get_executor_registry().executor(registration.executor_key) is not None

    def definition(self, key: str) -> CapabilityDefinition | None:
        registration = self.resolve(key)
        return registration.definition if registration else None

    def handler(self, key: str) -> CapabilityHandler | None:
        registration = self.resolve(key)
        return registration.handler if registration else None

    def catalog(self) -> list[CapabilityDefinition]:
        return [
            self._registrations[key].definition
            for key in sorted(self._registrations)
        ]

    def installed_catalog(self) -> list[CapabilityDefinition]:
        return [
            self._registrations[key].definition
            for key in sorted(self._registrations)
            if self.is_executable(key)
        ]


def _definition(
    key: str,
    label: str,
    execution_kind: ExecutionKind,
    *,
    timeout_seconds: int = 300,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        version="1.0.0",
        label=label,
        execution_kind=execution_kind,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        timeout_seconds=timeout_seconds,
    )


@lru_cache
def get_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    from app.capabilities.builtin import register_builtin_capabilities

    register_builtin_capabilities(registry)
    settings = get_settings()
    load_registrar_modules(
        settings.extension_modules("capability"),
        hook_name="register_capabilities",
        registry=registry,
    )
    return registry
