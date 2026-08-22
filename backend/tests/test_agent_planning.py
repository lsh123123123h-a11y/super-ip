from app.schemas.agent import ProductionOrderCreate
from app.product.digital_human_plan import build_digital_human_plan, build_intent_spec
from app.capabilities.registry import get_capability_registry
from app.product.registry import get_product_registry
from app.services.agent_service import _request_hash


def make_request(**inputs):
    return ProductionOrderCreate(
        project_id="project-1",
        intent_text="制作一条可发布的数字人口播",
        automation_mode="automatic",
        inputs=inputs,
    )


def test_agent_plan_uses_supplied_script_audio_and_avatar() -> None:
    request = make_request(
        script="现成脚本",
        audio_asset_id="audio-1",
        avatar_asset_id="avatar-1",
    )
    intent = build_intent_spec(request)
    plan = build_digital_human_plan(request, intent)
    keys = [step.key for step in plan.steps]

    assert keys == [
        "intent.normalize",
        "script.accept_input",
        "audio.evaluate",
        "avatar.render",
        "video.compose",
        "delivery.package",
    ]
    assert plan.steps[3].blocked_by_missing_input is False
    assert next(step for step in plan.steps if step.key == "audio.evaluate").depends_on == [
        "intent.normalize"
    ]
    assert next(step for step in plan.steps if step.key == "avatar.render").depends_on == [
        "script.accept_input",
        "audio.evaluate",
    ]
    assert plan.contract == "agent.plan.v1"
    assert plan.planner == {"kind": "template", "version": "digital-human-v1"}


def test_agent_plan_expands_vague_intent_into_generation_steps() -> None:
    request = make_request()
    plan = build_digital_human_plan(request, build_intent_spec(request))
    keys = [step.key for step in plan.steps]

    assert "strategy.generate" in keys
    assert "script.generate" in keys
    assert "audio.prepare" in keys
    assert next(step for step in plan.steps if step.key == "avatar.render").blocked_by_missing_input


def test_production_order_request_hash_is_stable_and_payload_sensitive() -> None:
    first = make_request(script="版本 A")
    same = make_request(script="版本 A")
    changed = make_request(script="版本 B")

    assert _request_hash(first) == _request_hash(same)
    assert _request_hash(first) != _request_hash(changed)


def test_product_fallback_plan_only_uses_installed_execution_bindings() -> None:
    request = make_request()
    product = get_product_registry().require(request.product_key)
    installed = {
        item.key for item in get_capability_registry().installed_catalog()
    }

    plan = product.build_fallback_plan(
        request,
        product.build_intent(request),
        available_capabilities=installed,
    )

    assert {step.capability for step in plan.steps}.issubset(installed)
    assert [step.key for step in plan.steps] == [
        "intent.normalize",
        "strategy.generate",
        "script.generate",
        "audio.evaluate",
        "avatar.render",
    ]
