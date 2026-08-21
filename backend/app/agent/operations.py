from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentOperationType(str, Enum):
    planning = "planning"
    executor = "executor"


class AgentOperationStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting = "waiting"
    failed_retryable = "failed_retryable"
    succeeded = "succeeded"
    failed_final = "failed_final"
    canceled = "canceled"


class TraceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=64)
    span_id: str = Field(min_length=1, max_length=64)
    parent_span_id: str | None = Field(default=None, max_length=64)


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_permissions: list[str] = Field(default_factory=list)
    granted_permissions: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    max_attempts: int = Field(default=3, ge=1, le=10)
    budget_limit: Decimal | None = Field(default=None, ge=0)
    budget_reserve: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def validate_budget(self) -> "ExecutionPolicy":
        if self.budget_limit is not None and self.budget_reserve > self.budget_limit:
            raise ValueError("预算预留不能超过任务预算上限")
        return self


class ExecutorDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal["agent.executor.v1"] = "agent.executor.v1"
    key: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    supported_operations: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    default_timeout_seconds: int = Field(default=1800, ge=1, le=86400)
    metadata: dict[str, Any] = Field(default_factory=dict)
