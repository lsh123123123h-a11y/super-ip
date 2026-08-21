from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IPProfileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    promise: str = ""
    audience: str = ""
    offer: str = ""
    voice: str = ""
    evidence: str = ""
    boundary: str = ""
    is_primary: bool = False


class IPProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    promise: str | None = None
    audience: str | None = None
    offer: str | None = None
    voice: str | None = None
    evidence: str | None = None
    boundary: str | None = None
    is_primary: bool | None = None


class IPProfileRead(IPProfileWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    created_at: datetime
    updated_at: datetime


class CampaignWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str = ""
    channels: list[str] = Field(default_factory=list)
    status: str = Field(default="draft", pattern=r"^(draft|active|paused|completed)$")
    target_content_count: int = Field(default=0, ge=0, le=10000)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str | None = None
    channels: list[str] | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|active|paused|completed)$")
    target_content_count: int | None = Field(default=None, ge=0, le=10000)
    metadata_payload: dict[str, Any] | None = None


class CampaignRead(CampaignWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class ContentProjectWrite(BaseModel):
    campaign_id: str | None = None
    ip_profile_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default="idea", pattern=r"^(idea|benchmark|product|copy)$")
    platform: str = Field(default="抖音", max_length=32)
    brief: str = ""
    angle: str = Field(default="", max_length=64)
    script: str = ""
    status: str = Field(default="draft", pattern=r"^(draft|script_ready|in_production|approved|published)$")


class ContentProjectPatch(BaseModel):
    campaign_id: str | None = None
    ip_profile_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    source_type: str | None = Field(default=None, pattern=r"^(idea|benchmark|product|copy)$")
    platform: str | None = Field(default=None, max_length=32)
    brief: str | None = None
    angle: str | None = Field(default=None, max_length=64)
    script: str | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|script_ready|in_production|approved|published)$")


class ContentProjectRead(ContentProjectWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
