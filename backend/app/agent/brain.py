from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class StructuredBrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=100)
    system_instruction: str
    user_input: dict[str, Any]
    output_schema: dict[str, Any]
    model_alias: str = "reasoning.default"
    temperature: float = Field(default=0.2, ge=0, le=2)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StructuredBrainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: dict[str, Any]
    model_ref: str
    gateway_ref: str
    usage: dict[str, int] = Field(default_factory=dict)
    raw_response_id: str | None = None
    reported_cost: Decimal | None = None
    cost_currency: str | None = None


class BrainPort(Protocol):
    async def complete_structured(
        self,
        request: StructuredBrainRequest,
    ) -> StructuredBrainResponse: ...

    async def probe(self) -> dict[str, Any]: ...
