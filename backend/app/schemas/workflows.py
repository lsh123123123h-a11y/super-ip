from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.orchestration import StepStatus, WorkflowStatus


class DigitalHumanRenderRequest(BaseModel):
    script: str = Field(min_length=1, max_length=10000)
    avatar_video_path: str = Field(min_length=1)
    audio_path: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=200)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1)$")
    quality: str = Field(default="720p", pattern=r"^(720p|1080p)$")


class WorkflowStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_key: str
    label: str
    position: int
    status: StepStatus
    progress: int
    attempt: int
    error_message: str | None


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_type: str
    status: WorkflowStatus
    progress: int
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepRead]


class AssetUploadResponse(BaseModel):
    asset_id: str
    file_name: str
    provider_path: str
    download_url: str
    content_type: str | None
