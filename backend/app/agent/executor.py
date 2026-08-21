from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


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

    async def collect_result(self, execution_id: str) -> dict[str, Any]: ...
