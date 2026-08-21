from functools import lru_cache

from app.agent.contracts import CapabilityDefinition, ExecutionKind
from app.capabilities.avatar_render import AvatarRenderCapability
from app.capabilities.base import CapabilityHandler
from app.capabilities.foundation import (
    AudioEvaluateCapability,
    ContentIngestCapability,
    IntentNormalizeCapability,
)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._handlers: dict[str, CapabilityHandler] = {}

    def register(
        self,
        definition: CapabilityDefinition,
        handler: CapabilityHandler | None = None,
    ) -> None:
        if definition.key in self._definitions:
            raise ValueError(f"能力重复注册：{definition.key}")
        self._definitions[definition.key] = definition
        if handler is not None:
            self._handlers[definition.key] = handler

    def definition(self, key: str) -> CapabilityDefinition | None:
        return self._definitions.get(key)

    def handler(self, key: str) -> CapabilityHandler | None:
        return self._handlers.get(key)

    def catalog(self) -> list[CapabilityDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]

    def installed_catalog(self) -> list[CapabilityDefinition]:
        return [
            self._definitions[key]
            for key in sorted(self._handlers)
            if key in self._definitions
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
    registry.register(
        _definition("agent.intent.normalize", "目标结构化", ExecutionKind.inline),
        IntentNormalizeCapability(),
    )
    registry.register(
        _definition("content.ingest", "接收已有内容", ExecutionKind.inline),
        ContentIngestCapability(),
    )
    registry.register(
        _definition("audio.evaluate", "检查已有配音", ExecutionKind.inline),
        AudioEvaluateCapability(),
    )
    registry.register(
        _definition("avatar.render", "生成数字人视频", ExecutionKind.durable, timeout_seconds=7200),
        AvatarRenderCapability(),
    )
    for key, label, kind, timeout in (
        ("content.strategy", "内容策略", ExecutionKind.harness, 600),
        ("content.generate", "内容生成", ExecutionKind.harness, 600),
        ("audio.prepare", "配音生成", ExecutionKind.durable, 1800),
        ("video.compose", "视频后期合成", ExecutionKind.durable, 3600),
        ("delivery.package", "交付包装", ExecutionKind.inline, 300),
    ):
        registry.register(_definition(key, label, kind, timeout_seconds=timeout))
    return registry
