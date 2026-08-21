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


class OpenTalkingProviderError(RuntimeError):
    pass


class OpenTalkingProvider:
    """Adapter for a managed OpenTalking deployment plus the Xingliu render bridge.

    OpenTalking's public API exposes sessions, models, avatars and offline bundle jobs.
    The `/xingliu/render` bridge is deliberately ours: it keeps backend/model-specific
    session choreography outside the business worker and returns one stable async job.
    """

    provider_id = "opentalking"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self.timeout_seconds = settings.opentalking_timeout_seconds

    def descriptor(self) -> ProviderDescriptor:
        configured = bool(self.settings.opentalking_base_url.strip())
        render_ready = configured and self.settings.opentalking_render_enabled
        reason = None
        if not configured:
            reason = "尚未配置 OpenTalking 服务地址"
        elif not self.settings.opentalking_render_enabled:
            reason = "服务可探测；视频桥接器尚未启用"
        return ProviderDescriptor(
            provider_id=self.provider_id,
            label="OpenTalking",
            category="avatar.render",
            capabilities=["avatar.render", "avatar.video_clone", "avatar.session.realtime"],
            execution_modes=[ExecutionMode.self_hosted.value, ExecutionMode.cloud_api.value],
            render_ready=render_ready,
            integration_state="production" if render_ready else "probe_only",
            reason=reason,
            poll_interval_seconds=2.0,
        )

    async def probe(self) -> dict[str, Any]:
        if not self.settings.opentalking_base_url.strip():
            return {"reachable": False, "mode": "not_configured", "message": "未配置服务地址"}
        health = await self._request("GET", "/health")
        models = await self._request("GET", "/models")
        return {
            "reachable": True,
            "mode": "render_bridge" if self.settings.opentalking_render_enabled else "probe_only",
            "health": health,
            "models": models,
        }

    async def submit_render(
        self,
        *,
        external_job_id: str,
        request: AvatarRenderInput,
    ) -> ProviderSubmission:
        if not self.descriptor().render_ready:
            raise OpenTalkingProviderError(self.descriptor().reason or "OpenTalking 视频桥接器未就绪")
        payload = {
            "external_job_id": external_job_id,
            "script": request.script,
            "audio_path": request.audio_path,
            "video_path": request.video_path,
            "aspect_ratio": request.aspect_ratio,
            "quality": request.quality,
            "options": request.provider_options,
        }
        response = await self._request("POST", self.settings.opentalking_render_submit_path, json=payload)
        job_id = str(response.get("job_id") or response.get("id") or external_job_id)
        return ProviderSubmission(external_job_id=job_id, raw=response)

    async def submit(
        self,
        *,
        external_job_id: str,
        request: ProviderExecutionRequest,
    ) -> ProviderSubmission:
        if request.capability != "avatar.render":
            raise OpenTalkingProviderError(
                f"OpenTalking 不支持能力：{request.capability}"
            )
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
        path = self.settings.opentalking_render_query_path.format(job_id=external_job_id)
        payload = await self._request("GET", path)
        raw_state = str(payload.get("status") or payload.get("state") or "processing").lower()
        progress = _progress(payload.get("progress"))
        if raw_state in {"succeeded", "completed", "done"}:
            return ProviderStatus(
                ProviderJobState.succeeded,
                100,
                payload.get("result_url") or payload.get("result_path"),
                payload.get("message"),
                payload,
                result_url=payload.get("result_url"),
                artifact_path=payload.get("result_path"),
            )
        if raw_state in {"failed", "error", "cancelled"}:
            return ProviderStatus(ProviderJobState.failed, progress, None, payload.get("message"), payload)
        if raw_state in {"queued", "pending"}:
            return ProviderStatus(ProviderJobState.queued, progress, None, payload.get("message"), payload)
        return ProviderStatus(ProviderJobState.processing, progress, None, payload.get("message"), payload)

    async def query(
        self,
        external_job_id: str,
        *,
        capability: str,
    ) -> ProviderStatus:
        if capability != "avatar.render":
            raise OpenTalkingProviderError(
                f"OpenTalking 不支持能力：{capability}"
            )
        return await self.query_render(external_job_id)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self.settings.opentalking_api_key:
            headers["Authorization"] = f"Bearer {self.settings.opentalking_api_key}"
        if self._client is not None:
            response = await self._client.request(method, path, headers=headers, **kwargs)
        else:
            async with httpx.AsyncClient(
                base_url=self.settings.opentalking_base_url,
                timeout=60.0,
                headers=headers,
            ) as client:
                response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise OpenTalkingProviderError("OpenTalking 返回了非对象 JSON")
        return data


def _progress(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 1:
        number *= 100
    return max(0, min(100, int(number)))
