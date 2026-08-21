from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.agent.brain import BrainPort, StructuredBrainRequest
from app.agent.contracts import (
    AgentIntentSpec,
    AgentPlanSpec,
    CapabilityDefinition,
)
from app.agent.evaluation import EvaluatorDefinition


class PlanGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: AgentPlanSpec
    usage: dict[str, int] = Field(default_factory=dict)
    model_ref: str | None = None
    gateway_ref: str | None = None


class PlannerPort(Protocol):
    async def create_plan(
        self,
        *,
        intent: AgentIntentSpec,
        capabilities: list[CapabilityDefinition],
        evaluators: list[EvaluatorDefinition] | None = None,
        context: dict[str, Any] | None = None,
    ) -> PlanGenerationResult: ...


class BrainPlanner(PlannerPort):
    def __init__(self, brain: BrainPort) -> None:
        self.brain = brain

    async def create_plan(
        self,
        *,
        intent: AgentIntentSpec,
        capabilities: list[CapabilityDefinition],
        evaluators: list[EvaluatorDefinition] | None = None,
        context: dict[str, Any] | None = None,
    ) -> PlanGenerationResult:
        response = await self.brain.complete_structured(
            StructuredBrainRequest(
                purpose="production_plan",
                system_instruction=(
                    "你是星流 AI 的内部生产规划器。只能使用能力目录中的 capability key，"
                    "输出满足 JSON Schema 的有向无环计划。不得输出模型、Provider、外部 Executor、"
                    "密钥或内部路由选择；这些属于基础设施。"
                ),
                user_input={
                    "intent": intent.model_dump(mode="json"),
                    "capabilities": [
                        item.model_dump(mode="json") for item in capabilities
                    ],
                    "evaluators": [
                        item.model_dump(mode="json") for item in (evaluators or [])
                    ],
                    "context": context or {},
                },
                output_schema=AgentPlanSpec.model_json_schema(),
            )
        )
        plan = AgentPlanSpec.model_validate(response.output)
        available = {item.key for item in capabilities}
        unknown = sorted({step.capability for step in plan.steps} - available)
        if unknown:
            raise ValueError(f"规划器引用了未安装的能力：{unknown}")
        if evaluators is not None:
            available_evaluators = {item.key for item in evaluators}
            unknown_evaluators = sorted(
                {step.evaluator for step in plan.steps} - available_evaluators
            )
            if unknown_evaluators:
                raise ValueError(
                    f"规划器引用了未安装的评价器：{unknown_evaluators}"
                )
        return PlanGenerationResult(
            plan=plan.model_copy(
                update={
                    "planner": {
                        "kind": "brain",
                        "model_ref": response.model_ref,
                        "gateway_ref": response.gateway_ref,
                    }
                }
            ),
            usage=response.usage,
            model_ref=response.model_ref,
            gateway_ref=response.gateway_ref,
        )
