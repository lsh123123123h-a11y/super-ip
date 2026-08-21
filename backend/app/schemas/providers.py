from typing import Literal

from pydantic import BaseModel, Field


class ProviderRoutePreviewRequest(BaseModel):
    capability: str = Field(default="avatar.render", min_length=1, max_length=100)
    provider: str = Field(default="auto", min_length=1, max_length=64)
    execution_mode: Literal["auto", "local", "self_hosted", "cloud_api"] = "auto"


class ProviderRoutePreviewResponse(BaseModel):
    capability: str
    requested_provider: str
    requested_execution: str
    selected_provider: str
    selected_execution: str
    policy_version: str
    reason: str
    candidates: list[dict[str, object]]


AvatarRoutePreviewRequest = ProviderRoutePreviewRequest
AvatarRoutePreviewResponse = ProviderRoutePreviewResponse
