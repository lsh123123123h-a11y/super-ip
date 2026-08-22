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
    intent_output = {
        "type": "object",
        "required": ["goal", "deliverable", "confidence"],
        "properties": {
            "goal": {"type": "string"},
            "deliverable": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    content_output = {
        "type": "object",
        "required": ["title"],
        "properties": {
            "title": {"type": "string"},
            "body_markdown": {"type": "string"},
            "text": {"type": "string"},
        },
    }
    media_input = {
        "type": "object",
        "properties": {
            "audio_asset_id": {"type": "string"},
            "audio_path": {"type": "string"},
            "avatar_video_path": {"type": "string"},
        },
        "additionalProperties": True,
    }
    media_output = {
        "type": "object",
        "required": ["media_path"],
        "properties": {"media_path": {"type": "string"}},
        "additionalProperties": True,
    }
    registry.register(
        _definition(
            "agent.intent.normalize",
            "目标结构化",
            ExecutionKind.inline,
            input_schema={"type": "object", "additionalProperties": True},
            output_schema=intent_output,
        ),
        IntentNormalizeCapability(),
        source="builtin.foundation",
    )
    registry.register(
        _definition(
            "content.ingest",
            "接收已有内容",
            ExecutionKind.inline,
            input_schema={
                "type": "object",
                "required": ["script"],
                "properties": {"script": {"type": "string", "minLength": 1}},
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
        ),
        ContentIngestCapability(),
        source="builtin.foundation",
    )
    registry.register(
        _definition(
            "audio.evaluate",
            "检查已有配音",
            ExecutionKind.inline,
            input_schema=media_input,
            output_schema=media_output,
        ),
        AudioEvaluateCapability(),
        source="builtin.foundation",
    )
    registry.register(
        _definition(
            "avatar.render",
            "生成数字人视频",
            ExecutionKind.durable,
            timeout_seconds=7200,
            input_schema=media_input,
            output_schema=media_output,
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
            input_schema={"type": "object", "additionalProperties": True},
            output_schema=content_output,
        ),
        ContentStrategyCapability(),
        source="builtin.brain",
        metadata={"requires": ["brain"], "model_alias": "reasoning.default"},
    )
    registry.register(
        _definition(
            "content.generate",
            "内容生成",
            ExecutionKind.inline,
            timeout_seconds=600,
            input_schema={"type": "object", "additionalProperties": True},
            output_schema=content_output,
        ),
        ContentGenerateCapability(),
        source="builtin.brain",
        metadata={"requires": ["brain"], "model_alias": "writing.default"},
    )
    for key, label, kind, timeout in (
        ("audio.prepare", "配音生成", ExecutionKind.durable, 1800),
        ("video.compose", "视频后期合成", ExecutionKind.durable, 3600),
        ("delivery.package", "交付包装", ExecutionKind.inline, 300),
    ):
        registry.register(
            _definition(
                key,
                label,
                kind,
                timeout_seconds=timeout,
                input_schema=media_input,
                output_schema=media_output,
            ),
            source="builtin.catalog",
        )
