from typing import Any

from app.agent.contracts import AgentIntentSpec, AgentPlanSpec
from app.agent.planner import BrainPlanner, PlanGenerationResult
from app.capabilities.registry import get_capability_registry
from app.core.config import get_settings
from app.integrations.new_api_brain import NewApiBrainAdapter
from app.evaluators.registry import get_evaluator_registry
from app.product.registry import get_product_registry
from app.schemas.agent import ProductionOrderCreate


async def build_product_plan(
    payload: ProductionOrderCreate,
    intent: AgentIntentSpec,
) -> AgentPlanSpec:
    return (await build_product_plan_result(payload, intent)).plan


async def build_product_plan_result(
    payload: ProductionOrderCreate,
    intent: AgentIntentSpec,
    *,
    planning_context: dict[str, Any] | None = None,
) -> PlanGenerationResult:
    settings = get_settings()
    product = get_product_registry().require(payload.product_key)
    installed_capabilities = get_capability_registry().installed_catalog()
    if not settings.model_gateway_configured:
        plan = product.build_fallback_plan(
            payload,
            intent,
            available_capabilities={item.key for item in installed_capabilities},
        )
        if planning_context:
            plan = plan.model_copy(update={"revision_context": planning_context})
        return PlanGenerationResult(
            plan=plan,
            gateway_ref="template",
        )
    brain = NewApiBrainAdapter(
        base_url=settings.model_gateway_base_url,
        api_key=settings.model_gateway_api_key,
        default_model=settings.model_gateway_default_model,
        timeout_seconds=settings.model_gateway_timeout_seconds,
    )
    context = product.planner_context(payload)
    context.update(planning_context or {})
    return await BrainPlanner(brain).create_plan(
        intent=intent,
        capabilities=installed_capabilities,
        evaluators=get_evaluator_registry().catalog(),
        context=context,
    )
