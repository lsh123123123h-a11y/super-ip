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
class ProviderExecutionRequest:
    capability: str
    inputs: dict[str, Any]
    provider_options: dict[str, Any]


@dataclass(slots=True)
class ProviderDescriptor:
    provider_id: str
    label: str
    category: str
    capabilities: list[str]
    execution_modes: list[str]
    ready: bool
    integration_state: str
    reason: str | None = None
    poll_interval_seconds: float = 2.0

    @property
    def render_ready(self) -> bool:
        """Compatibility alias for the original avatar-only provider catalog."""

        return self.ready


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
    artifact_path: str | None = None
    result_url: str | None = None
    transient_error_code: str | None = None
    max_transient_polls: int | None = None


class CapabilityProvider(Protocol):
    provider_id: str
    timeout_seconds: float

    def descriptor(self) -> ProviderDescriptor: ...

    async def submit(
        self,
        *,
        external_job_id: str,
        request: ProviderExecutionRequest,
    ) -> ProviderSubmission: ...

    async def query(
        self,
        external_job_id: str,
        *,
        capability: str,
    ) -> ProviderStatus: ...

    async def probe(self) -> dict[str, Any]: ...


class AvatarRenderProvider(CapabilityProvider, Protocol):
    async def submit_render(self, *, external_job_id: str, request: AvatarRenderInput) -> ProviderSubmission: ...

    async def query_render(self, external_job_id: str) -> ProviderStatus: ...
