from typing import Any

from app.agent.contracts import AgentIntentSpec, AgentPlanSpec
from app.agent.planner import BrainPlanner, PlanGenerationResult
from app.capabilities.registry import get_capability_registry
from app.core.config import get_settings
from app.integrations.new_api_brain import NewApiBrainAdapter
from app.product.digital_human_plan import build_digital_human_plan
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
    if not settings.model_gateway_configured:
        plan = build_digital_human_plan(payload, intent)
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
    context = {
        "product": "digital_human_content_production",
        "automation_mode": payload.automation_mode,
        "checkpoint_policy": payload.checkpoint_policy,
        "max_auto_rework": payload.max_auto_rework,
    }
    context.update(planning_context or {})
    return await BrainPlanner(brain).create_plan(
        intent=intent,
        capabilities=get_capability_registry().installed_catalog(),
        context=context,
    )
