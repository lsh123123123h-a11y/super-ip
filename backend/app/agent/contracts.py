from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionKind(str, Enum):
    inline = "inline"
    durable = "durable"
    harness = "harness"


class OutcomeStatus(str, Enum):
    succeeded = "succeeded"
    dispatched = "dispatched"
    waiting = "waiting"
    awaiting_decision = "awaiting_decision"
    failed = "failed"


class AgentIntentSpec(ContractModel):
    contract: Literal["agent.intent.v1"] = "agent.intent.v1"
    goal: str = Field(min_length=1)
    deliverable: str = Field(min_length=1)
    target_platforms: list[str] = Field(default_factory=list)
    duration_seconds: dict[str, int] = Field(default_factory=dict)
    supplied_inputs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    input_asset_ids: list[str] = Field(default_factory=list)


class PlanStepSpec(ContractModel):
    key: str = Field(min_length=1, max_length=100)
    capability: str = Field(min_length=1, max_length=100)
    depends_on: list[str] = Field(default_factory=list)
    expected_artifact: str = Field(min_length=1, max_length=100)
    evaluator: str = Field(min_length=1, max_length=100)
    checkpoint: Literal["none", "policy", "final"] = "none"
    blocked_by_missing_input: bool = False


class AgentPlanSpec(ContractModel):
    contract: Literal["agent.plan.v1"] = "agent.plan.v1"
    goal: str = Field(min_length=1)
    steps: list[PlanStepSpec] = Field(min_length=1)
    termination_policy: Literal["all_required_artifacts_approved"] = (
        "all_required_artifacts_approved"
    )
    max_auto_rework: int = Field(default=2, ge=0, le=10)
    planner: dict[str, str] = Field(default_factory=dict)
    revision_context: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_graph(self) -> "AgentPlanSpec":
        keys = [step.key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("计划步骤 key 必须唯一")
        known: set[str] = set()
        for step in self.steps:
            missing = set(step.depends_on) - known
            if missing:
                raise ValueError(
                    f"步骤 {step.key} 引用了尚未定义的依赖：{sorted(missing)}"
                )
            known.add(step.key)
        return self


class CapabilityDefinition(ContractModel):
    contract: Literal["agent.capability.v1"] = "agent.capability.v1"
    key: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    description: str = ""
    execution_kind: ExecutionKind
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=1)
    idempotent: bool = True


class ArtifactDraft(ContractModel):
    artifact_key: str = Field(min_length=1, max_length=100)
    artifact_type: str = Field(min_length=1, max_length=64)
    content_payload: dict[str, Any]
    lineage_payload: dict[str, Any] = Field(default_factory=dict)


class DecisionSpec(ContractModel):
    reason_code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    summary: str = ""
    options: list[dict[str, Any]] = Field(min_length=1)
    recommended_option: str | None = None
    blocking: bool = True


class CapabilityOutcome(ContractModel):
    status: OutcomeStatus
    artifact: ArtifactDraft | None = None
    decision: DecisionSpec | None = None
    external_execution_id: str | None = None
    retryable: bool = False
    error_code: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status_payload(self) -> "CapabilityOutcome":
        if self.status == OutcomeStatus.awaiting_decision and self.decision is None:
            raise ValueError("awaiting_decision 必须提供 decision")
        if self.status == OutcomeStatus.failed and not self.message:
            raise ValueError("failed 必须提供 message")
        return self
