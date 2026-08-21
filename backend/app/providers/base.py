from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class ProviderJobState(str, Enum):
    queued = "queued"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"


class ExecutionMode(str, Enum):
    local = "local"
    self_hosted = "self_hosted"
    cloud_api = "cloud_api"


@dataclass(slots=True)
class AvatarRenderInput:
    script: str
    audio_path: str
    video_path: str
    aspect_ratio: str
    quality: str
    provider_options: dict[str, Any]


@dataclass(slots=True)
class ProviderDescriptor:
    provider_id: str
    label: str
    category: str
    capabilities: list[str]
    execution_modes: list[str]
    render_ready: bool
    integration_state: str
    reason: str | None = None


@dataclass(slots=True)
class ProviderSubmission:
    external_job_id: str
    raw: dict[str, Any]


@dataclass(slots=True)
class ProviderStatus:
    state: ProviderJobState
    progress: int
    result_path: str | None
    message: str | None
    raw: dict[str, Any]


class AvatarRenderProvider(Protocol):
    provider_id: str
    timeout_seconds: float

    def descriptor(self) -> ProviderDescriptor: ...

    async def submit_render(self, *, external_job_id: str, request: AvatarRenderInput) -> ProviderSubmission: ...

    async def query_render(self, external_job_id: str) -> ProviderStatus: ...

    async def probe(self) -> dict[str, Any]: ...
