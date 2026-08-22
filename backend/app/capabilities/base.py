from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import CapabilityOutcome, PlanStepSpec
from app.models.agent import AgentRun, PlanVersion, ProductionOrder


@dataclass(slots=True)
class CapabilityContext:
    session: AsyncSession
    order: ProductionOrder
    run: AgentRun
    plan: PlanVersion
    step: PlanStepSpec
    inputs: dict[str, Any]
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    execution_attempt: int = 1
    evaluation_feedback: list[dict[str, Any]] | None = None
    step_execution_id: str | None = None
    fence_token: int | None = None
    runtime_binding_payload: dict[str, Any] = field(default_factory=dict)


class CapabilityHandler(Protocol):
    async def execute(self, context: CapabilityContext) -> CapabilityOutcome: ...

    async def interrupt(
        self,
        context: CapabilityContext,
        external_execution_id: str | None,
    ) -> None: ...
