from dataclasses import dataclass
from typing import Protocol

from app.agent.contracts import CapabilityOutcome, PlanStepSpec
from app.agent.evaluation import EvaluationResult
from app.models.agent import AgentRun, ArtifactVersion, PlanVersion, ProductionOrder


@dataclass(slots=True)
class EvaluationContext:
    order: ProductionOrder
    run: AgentRun
    plan: PlanVersion
    step: PlanStepSpec
    outcome: CapabilityOutcome
    artifact_version: ArtifactVersion | None


class QualityEvaluator(Protocol):
    async def evaluate(self, context: EvaluationContext) -> EvaluationResult: ...
