from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import (
    AgentRunStatus,
    ArtifactVersionStatus,
    DecisionStatus,
    PlanVersionStatus,
    ProductionOrderStatus,
)


AutomationMode = Literal["many_confirmations", "key_checkpoints", "automatic"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str = ""
    settings_payload: dict[str, Any] = Field(default_factory=dict)


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class ProductionOrderCreate(BaseModel):
    project_id: str
    title: str | None = Field(default=None, max_length=200)
    intent_text: str = Field(min_length=1, max_length=20000)
    automation_mode: AutomationMode = "key_checkpoints"
    checkpoint_policy: dict[str, Any] = Field(default_factory=dict)
    external_side_effect_policy: dict[str, Any] = Field(default_factory=dict)
    budget_limit: Decimal | None = Field(default=None, ge=0)
    max_auto_rework: int = Field(default=2, ge=0, le=10)
    ip_profile_id: str | None = None
    content_item_id: str | None = None
    content_item_title: str | None = Field(default=None, max_length=200)
    inputs: dict[str, Any] = Field(default_factory=dict)


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_number: int
    status: AgentRunStatus
    stop_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class PlanVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    goal: str
    success_criteria: list[str]
    plan_payload: dict[str, Any]
    budget_estimate: Decimal | None
    status: PlanVersionStatus
    created_at: datetime


class DecisionRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reason_code: str
    title: str
    summary: str
    options: list[dict[str, Any]]
    recommended_option: str | None
    blocking: bool
    status: DecisionStatus
    resolved_option: str | None
    resolution_payload: dict[str, Any] | None
    created_at: datetime
    resolved_at: datetime | None


class ArtifactVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_id: str
    artifact_key: str | None = None
    artifact_type: str | None = None
    version: int
    status: ArtifactVersionStatus
    content_payload: dict[str, Any]
    checksum: str | None
    created_at: datetime
    approved_at: datetime | None


class ProductionOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    project_id: str
    content_item_id: str | None
    title: str
    intent_text: str
    intent_spec: dict[str, Any]
    automation_mode: str
    checkpoint_policy: dict[str, Any]
    external_side_effect_policy: dict[str, Any]
    status: ProductionOrderStatus
    budget_limit: Decimal | None
    max_auto_rework: int
    auto_rework_count: int
    created_at: datetime
    updated_at: datetime


class ProductionOrderOverview(BaseModel):
    order: ProductionOrderRead
    agent_run: AgentRunRead
    plan: PlanVersionRead | None = None
    decisions: list[DecisionRequestRead] = Field(default_factory=list)
    artifact_versions: list[ArtifactVersionRead] = Field(default_factory=list)


class ResolveDecisionRequest(BaseModel):
    option_key: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class ProductionOrderInputsUpdate(BaseModel):
    script: str | None = Field(default=None, max_length=20000)
    audio_asset_id: str | None = None
    avatar_asset_id: str | None = None
    aspect_ratio: Literal["9:16", "16:9", "1:1"] | None = None
    quality: Literal["720p", "1080p"] | None = None


class ArtifactReviewRequest(BaseModel):
    note: str = Field(default="", max_length=4000)
