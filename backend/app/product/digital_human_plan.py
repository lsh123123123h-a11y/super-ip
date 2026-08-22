from typing import Any

from app.agent.contracts import AgentIntentSpec, AgentPlanSpec, PlanStepSpec
from app.schemas.agent import ProductionOrderCreate


def build_intent_spec(payload: ProductionOrderCreate) -> AgentIntentSpec:
    inputs = payload.inputs
    supplied = [
        key
        for key in (
            "script",
            "audio_asset_id",
            "audio_path",
            "avatar_asset_id",
            "avatar_video_path",
        )
        if inputs.get(key)
    ]
    return AgentIntentSpec(
        goal=payload.intent_text.strip(),
        deliverable=str(inputs.get("deliverable") or "9:16 数字人口播成片"),
        target_platforms=list(inputs.get("target_platforms") or ["抖音"]),
        duration_seconds=dict(inputs.get("duration_seconds") or {"min": 45, "max": 65}),
        supplied_inputs=supplied,
        constraints=dict(inputs.get("constraints") or {}),
        assumptions=[
            "首期交付形态默认为数字人口播",
            "外部发布属于高风险副作用，默认不自动执行",
        ],
        confidence=0.82 if supplied else 0.68,
    )


def build_digital_human_plan(
    payload: ProductionOrderCreate,
    intent_spec: AgentIntentSpec,
    *,
    available_capabilities: set[str] | None = None,
) -> AgentPlanSpec:
    available = available_capabilities if available_capabilities is not None else {
        "agent.intent.normalize",
        "content.ingest",
        "content.strategy",
        "content.generate",
        "audio.evaluate",
        "audio.prepare",
        "avatar.render",
        "video.compose",
        "delivery.package",
    }
    inputs = payload.inputs
    has_script = bool(inputs.get("script"))
    has_audio = bool(inputs.get("audio_asset_id") or inputs.get("audio_path"))
    has_avatar = bool(inputs.get("avatar_asset_id") or inputs.get("avatar_video_path"))
    steps: list[PlanStepSpec] = [
        PlanStepSpec(
            key="intent.normalize",
            capability="agent.intent.normalize",
            expected_artifact="intent_spec",
            evaluator="intent_completeness_v1",
        )
    ]
    if not has_script and {
        "content.strategy",
        "content.generate",
    }.issubset(available):
        steps.extend(
            [
                PlanStepSpec(
                    key="strategy.generate",
                    capability="content.strategy",
                    depends_on=["intent.normalize"],
                    expected_artifact="strategy_proposal",
                    evaluator="strategy_quality_v1",
                    checkpoint="policy",
                ),
                PlanStepSpec(
                    key="script.generate",
                    capability="content.generate",
                    depends_on=["strategy.generate"],
                    expected_artifact="script",
                    evaluator="script_quality_v1",
                    checkpoint="policy",
                ),
            ]
        )
        script_dependency = "script.generate"
    else:
        steps.append(
            PlanStepSpec(
                key="script.accept_input",
                capability="content.ingest",
                depends_on=["intent.normalize"],
                expected_artifact="script",
                evaluator="script_quality_v1",
                checkpoint="policy",
                blocked_by_missing_input=not has_script,
            )
        )
        script_dependency = "script.accept_input"

    audio_key = (
        "audio.prepare"
        if not has_audio and "audio.prepare" in available
        else "audio.evaluate"
    )
    audio_dependencies = (
        [script_dependency]
        if audio_key == "audio.prepare"
        else ["intent.normalize"]
    )
    steps.append(
        PlanStepSpec(
            key=audio_key,
            capability=audio_key,
            depends_on=audio_dependencies,
            expected_artifact="voice_audio",
            evaluator="audio_quality_v1",
            checkpoint="policy",
            blocked_by_missing_input=not has_audio,
        )
    )
    steps.append(
        PlanStepSpec(
            key="avatar.render",
            capability="avatar.render",
            depends_on=[script_dependency, audio_key],
            expected_artifact="avatar_video",
            evaluator="avatar_quality_v1",
            checkpoint="policy",
            blocked_by_missing_input=not has_avatar,
        )
    )
    final_dependency = "avatar.render"
    if "video.compose" in available:
        steps.append(
            PlanStepSpec(
                key="video.compose",
                capability="video.compose",
                depends_on=[final_dependency],
                expected_artifact="final_video",
                evaluator="video_quality_v1",
                checkpoint="final",
            )
        )
        final_dependency = "video.compose"
    if "delivery.package" in available:
        steps.append(
            PlanStepSpec(
                key="delivery.package",
                capability="delivery.package",
                depends_on=[final_dependency],
                expected_artifact="delivery_package",
                evaluator="delivery_completeness_v1",
            )
        )
    return AgentPlanSpec(
        goal=f"完成：{intent_spec.deliverable}",
        steps=steps,
        max_auto_rework=payload.max_auto_rework,
        planner={"kind": "template", "version": "digital-human-v1"},
    )
