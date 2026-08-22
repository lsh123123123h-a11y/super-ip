from typing import Any

from app.agent.contracts import AgentIntentSpec, AgentPlanSpec
from app.agent.planner import BrainPlanner, PlanGenerationResult
from app.capabilities.registry import get_capability_registry
from app.evaluators.registry import get_evaluator_registry
from app.integrations.managed_brain import brain_alias_available, create_managed_brain
# Compatibility import for extensions/tests that previously overrode bootstrap Brain creation.
from app.integrations.brain_factory import create_configured_brain  # noqa: F401
from app.product.registry import get_product_registry
from app.schemas.agent import ProductionOrderCreate


def pin_plan_implementation_versions(
    plan: AgentPlanSpec,
    *,
    capability_registry=None,
    evaluator_registry=None,
) -> AgentPlanSpec:
    """Pin every Super-IP controlled implementation used by a new PlanVersion."""

    capabilities = capability_registry or get_capability_registry()
    evaluators = evaluator_registry or get_evaluator_registry()
    pinned_steps = []
    for step in plan.steps:
        capability = capabilities.resolve(step.capability)
        if capability is None or not capabilities.is_executable(
            step.capability,
            capability.definition.version if capability else None,
        ):
            raise ValueError(f"计划引用了不可执行能力：{step.capability}")
        evaluator = evaluators.resolve(step.evaluator)
        if evaluator is None:
            raise ValueError(f"计划引用了未安装评价器：{step.evaluator}")
        pinned_steps.append(
            step.model_copy(
                update={
                    "capability_version": capability.definition.version,
                    "evaluator_version": evaluator.definition.version,
                }
            )
        )
    return plan.model_copy(update={"steps": pinned_steps})


async def build_product_plan(
    payload: ProductionOrderCreate,
    intent: AgentIntentSpec,
    *,
    tenant_id: str = "local-tenant",
) -> AgentPlanSpec:
    return (await build_product_plan_result(payload, intent, tenant_id=tenant_id)).plan


async def build_product_plan_result(
    payload: ProductionOrderCreate,
    intent: AgentIntentSpec,
    *,
    tenant_id: str = "local-tenant",
    planning_context: dict[str, Any] | None = None,
    invocation_metadata: dict[str, Any] | None = None,
    brain_binding_snapshot: dict[str, Any] | None = None,
) -> PlanGenerationResult:
    product = get_product_registry().require(payload.product_key)
    capability_registry = get_capability_registry()
    installed_capabilities = capability_registry.installed_catalog()
    alias_requirements = {
        "content.strategy": "reasoning.default",
        "content.generate": "writing.default",
    }
    alias_availability = {
        alias: await brain_alias_available(tenant_id, alias)
        for alias in set(alias_requirements.values())
    }
    if brain_binding_snapshot is not None:
        alias_availability["reasoning.default"] = not bool(
            brain_binding_snapshot.get("resolution_error")
        )
    installed_capabilities = [
        item
        for item in installed_capabilities
        if "brain" not in (
            (capability_registry.resolve(item.key).metadata.get("requires") or [])
            if capability_registry.resolve(item.key) is not None
            else []
        )
        or alias_requirements.get(item.key) is None
        or alias_availability[alias_requirements[item.key]]
    ]
    if not alias_availability["reasoning.default"]:
        plan = product.build_fallback_plan(
            payload,
            intent,
            available_capabilities={item.key for item in installed_capabilities},
        )
        if planning_context:
            plan = plan.model_copy(update={"revision_context": planning_context})
        return PlanGenerationResult(
            plan=pin_plan_implementation_versions(
                plan,
                capability_registry=capability_registry,
                evaluator_registry=get_evaluator_registry(),
            ),
            gateway_ref="template",
        )
    context = product.planner_context(payload)
    context.update(planning_context or {})
    brain = create_managed_brain(
        tenant_id,
        (
            {"reasoning.default": brain_binding_snapshot}
            if brain_binding_snapshot is not None
            else None
        ),
    )
    result = await BrainPlanner(brain).create_plan(
        intent=intent,
        capabilities=installed_capabilities,
        evaluators=get_evaluator_registry().catalog(),
        context={**context, "_invocation_metadata": invocation_metadata or {}},
    )
    return result.model_copy(
        update={
            "plan": pin_plan_implementation_versions(
                result.plan,
                capability_registry=capability_registry,
                evaluator_registry=get_evaluator_registry(),
            )
        }
    )
