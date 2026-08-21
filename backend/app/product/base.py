from dataclasses import dataclass
from typing import Any, Protocol

from app.agent.contracts import AgentIntentSpec, AgentPlanSpec
from app.schemas.agent import ProductionOrderCreate


@dataclass(frozen=True, slots=True)
class AssetInputDefinition:
    input_key: str
    role: str
    runtime_key: str
    media_type_prefix: str


class ProductAdapter(Protocol):
    key: str
    label: str
    asset_inputs: tuple[AssetInputDefinition, ...]

    def build_intent(self, payload: ProductionOrderCreate) -> AgentIntentSpec: ...

    def build_fallback_plan(
        self,
        payload: ProductionOrderCreate,
        intent: AgentIntentSpec,
        *,
        available_capabilities: set[str],
    ) -> AgentPlanSpec: ...

    def planner_context(self, payload: ProductionOrderCreate) -> dict[str, Any]: ...

    def validate_resume_inputs(self, inputs: dict[str, Any]) -> None: ...
