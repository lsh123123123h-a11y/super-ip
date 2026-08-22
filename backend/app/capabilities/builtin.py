from app.agent.contracts import ExecutionKind
from app.capabilities.avatar_render import AvatarRenderCapability
from app.capabilities.content import (
    ContentGenerateCapability,
    ContentStrategyCapability,
)
from app.capabilities.foundation import (
    AudioEvaluateCapability,
    ContentIngestCapability,
    IntentNormalizeCapability,
)
from app.capabilities.registry import CapabilityRegistry, _definition


def register_builtin_capabilities(registry: CapabilityRegistry) -> None:
    registry.register(
        _definition("agent.intent.normalize", "目标结构化", ExecutionKind.inline),
        IntentNormalizeCapability(),
        source="builtin.foundation",
    )
    registry.register(
        _definition("content.ingest", "接收已有内容", ExecutionKind.inline),
        ContentIngestCapability(),
        source="builtin.foundation",
    )
    registry.register(
        _definition("audio.evaluate", "检查已有配音", ExecutionKind.inline),
        AudioEvaluateCapability(),
        source="builtin.foundation",
    )
    registry.register(
        _definition(
            "avatar.render",
            "生成数字人视频",
            ExecutionKind.durable,
            timeout_seconds=7200,
        ),
        AvatarRenderCapability(),
        source="builtin.avatar",
    )
    registry.register(
        _definition(
            "content.strategy",
            "内容策略",
            ExecutionKind.inline,
            timeout_seconds=600,
        ),
        ContentStrategyCapability(),
        source="builtin.brain",
        metadata={"requires": ["brain"]},
    )
    registry.register(
        _definition(
            "content.generate",
            "内容生成",
            ExecutionKind.inline,
            timeout_seconds=600,
        ),
        ContentGenerateCapability(),
        source="builtin.brain",
        metadata={"requires": ["brain"]},
    )
    for key, label, kind, timeout in (
        ("audio.prepare", "配音生成", ExecutionKind.durable, 1800),
        ("video.compose", "视频后期合成", ExecutionKind.durable, 3600),
        ("delivery.package", "交付包装", ExecutionKind.inline, 300),
    ):
        registry.register(
            _definition(key, label, kind, timeout_seconds=timeout),
            source="builtin.catalog",
        )
