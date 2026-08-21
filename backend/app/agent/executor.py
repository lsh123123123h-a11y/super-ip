from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.contracts import CapabilityOutcome, OutcomeStatus


class AgentExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    production_order_id: str
    agent_run_id: str
    plan_version_id: str
    capability: str
    objective: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    workspace_ref: str | None = None
    idempotency_key: str


class ExecutionHandle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_key: str
    execution_id: str
    state: str
    resume_token: str | None = None


class AgentExecutionResult(BaseModel):
    """Stable result envelope returned by an optional external executor adapter."""

    model_config = ConfigDict(extra="forbid")

    outcome: CapabilityOutcome
    usage: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_terminal_outcome(self) -> "AgentExecutionResult":
        if self.outcome.status in {
            OutcomeStatus.dispatched,
            OutcomeStatus.waiting,
        }:
            raise ValueError("已完成的 Executor 必须返回终态 CapabilityOutcome")
        return self


class AgentExecutorPort(Protocol):
    async def start(self, request: AgentExecutionRequest) -> ExecutionHandle: ...

    async def resume(self, execution_id: str) -> ExecutionHandle: ...

    async def interrupt(self, execution_id: str) -> None: ...

    async def resolve_approval(
        self,
        execution_id: str,
        request_id: str,
        decision: str,
    ) -> None: ...

    async def collect_result(
        self,
        execution_id: str,
    ) -> AgentExecutionResult | dict[str, Any]: ...
