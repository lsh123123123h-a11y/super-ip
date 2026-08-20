from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class ProviderJobState(str, Enum):
    queued = "queued"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"


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


class OfflineAvatarProvider(Protocol):
    async def submit_render(self, *, external_job_id: str, audio_path: str, video_path: str) -> ProviderSubmission: ...

    async def query_render(self, external_job_id: str) -> ProviderStatus: ...
