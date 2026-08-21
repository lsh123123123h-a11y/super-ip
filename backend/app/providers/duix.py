import asyncio
import uuid
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.base import (
    AvatarRenderInput,
    ExecutionMode,
    ProviderDescriptor,
    ProviderJobState,
    ProviderExecutionRequest,
    ProviderStatus,
    ProviderSubmission,
)


class DuixProviderError(RuntimeError):
    pass


class DuixProvider:
    """Adapter for the Duix offline `/easy/submit` and `/easy/query` APIs."""

    provider_id = "duix"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self.timeout_seconds = settings.duix_timeout_seconds

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id=self.provider_id,
            label="Duix",
            category="avatar.render",
            capabilities=["avatar.render", "audio_driven_video", "progress_polling"],
            execution_modes=[ExecutionMode.self_hosted.value, ExecutionMode.local.value],
            ready=True,
            integration_state="production",
            poll_interval_seconds=self.settings.duix_poll_interval_seconds,
        )

    async def submit_render(
        self,
        *,
        external_job_id: str,
        request: AvatarRenderInput,
    ) -> ProviderSubmission:
        payload = {
            "audio_url": request.audio_path,
            "video_url": request.video_path,
            "code": external_job_id,
            "chaofen": 0,
            "watermark_switch": 0,
            "pn": 1,
        }
        if self.settings.duix_mock:
            return ProviderSubmission(external_job_id=external_job_id, raw={"code": 10000, "mock": True})

        response = await self._request("POST", "/submit", json=payload)
        if response.get("code") != 10000:
            raise DuixProviderError(response.get("msg") or f"Duix submit failed: {response}")
        return ProviderSubmission(external_job_id=external_job_id, raw=response)

    async def submit(
        self,
        *,
        external_job_id: str,
        request: ProviderExecutionRequest,
    ) -> ProviderSubmission:
        if request.capability != "avatar.render":
            raise DuixProviderError(f"Duix 不支持能力：{request.capability}")
        inputs = request.inputs
        return await self.submit_render(
            external_job_id=external_job_id,
            request=AvatarRenderInput(
                script=str(inputs.get("script") or ""),
                audio_path=str(inputs["audio_path"]),
                video_path=str(inputs["avatar_video_path"]),
                aspect_ratio=str(inputs.get("aspect_ratio") or "9:16"),
                quality=str(inputs.get("quality") or "720p"),
                provider_options=request.provider_options,
            ),
        )

    async def query_render(self, external_job_id: str) -> ProviderStatus:
        if self.settings.duix_mock:
            await asyncio.sleep(0.15)
            return ProviderStatus(
                state=ProviderJobState.succeeded,
                progress=100,
                result_path=f"results/{external_job_id}.mp4",
                message="mock render completed",
                raw={"code": 10000, "data": {"status": 2, "progress": 100}},
                artifact_path=f"results/{external_job_id}.mp4",
            )

        payload = await self._request("GET", "/query", params={"code": external_job_id})
        if payload.get("code") == 10004:
            return ProviderStatus(
                ProviderJobState.processing,
                0,
                None,
                payload.get("msg"),
                payload,
                transient_error_code="PROVIDER_JOB_NOT_VISIBLE",
                max_transient_polls=self.settings.duix_missing_job_poll_limit,
            )
        if payload.get("code") in {9999, 10002, 10003}:
            return ProviderStatus(ProviderJobState.failed, 0, None, payload.get("msg"), payload)
        if payload.get("code") != 10000:
            raise DuixProviderError(payload.get("msg") or f"Unexpected Duix response: {payload}")

        data: dict[str, Any] = payload.get("data") or {}
        status = data.get("status")
        progress = _progress(data.get("progress"))
        if status == 2:
            result_path = data.get("result")
            return ProviderStatus(
                ProviderJobState.succeeded,
                100,
                result_path,
                data.get("msg"),
                payload,
                artifact_path=self._artifact_path(result_path),
            )
        if status == 3:
            return ProviderStatus(ProviderJobState.failed, progress, None, data.get("msg"), payload)
        return ProviderStatus(ProviderJobState.processing, progress, None, data.get("msg"), payload)

    async def query(
        self,
        external_job_id: str,
        *,
        capability: str,
    ) -> ProviderStatus:
        if capability != "avatar.render":
            raise DuixProviderError(f"Duix 不支持能力：{capability}")
        return await self.query_render(external_job_id)

    async def probe(self) -> dict[str, Any]:
        if self.settings.duix_mock:
            return {"reachable": True, "mode": "mock", "response_code": 10000}
        payload = await self._request(
            "GET",
            "/query",
            params={"code": f"xingliu-healthcheck-{uuid.uuid4().hex}"},
        )
        return {
            "reachable": True,
            "mode": "live",
            "response_code": payload.get("code"),
            "message": payload.get("msg"),
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.request(method, path, **kwargs)
        else:
            async with httpx.AsyncClient(base_url=self.settings.duix_base_url, timeout=60.0) as client:
                response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise DuixProviderError("Duix returned a non-object JSON response")
        return data

    def _artifact_path(self, result_path: str | None) -> str | None:
        if not result_path:
            return None
        normalized = result_path.replace("\\", "/")
        if "://" in normalized:
            return None
        provider_root = self.settings.duix_container_data_root.rstrip("/")
        if normalized == provider_root:
            return None
        if normalized.startswith(f"{provider_root}/"):
            normalized = normalized[len(provider_root) + 1 :]
        normalized = normalized.lstrip("/")
        if not normalized or ".." in normalized.split("/"):
            return None
        return normalized


def _progress(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 1:
        number *= 100
    return max(0, min(100, int(number)))
