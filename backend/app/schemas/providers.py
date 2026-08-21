from typing import Literal

from pydantic import BaseModel


class AvatarRoutePreviewRequest(BaseModel):
    provider: Literal["auto", "duix", "opentalking"] = "auto"
    execution_mode: Literal["auto", "local", "self_hosted", "cloud_api"] = "auto"


class AvatarRoutePreviewResponse(BaseModel):
    capability: str
    requested_provider: str
    requested_execution: str
    selected_provider: str
    selected_execution: str
    policy_version: str
    reason: str
    candidates: list[dict[str, object]]
