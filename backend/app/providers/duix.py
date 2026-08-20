import asyncio
import uuid
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.base import ProviderJobState, ProviderStatus, ProviderSubmission


class DuixProviderError(RuntimeError):
    pass


class DuixProvider:
    """Adapter for the Duix offline `/easy/submit` and `/easy/query` APIs."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def submit_render(
        self,
        *,
        external_job_id: str,
        audio_path: str,
        video_path: str,
    ) -> ProviderSubmission:
        payload = {
            "audio_url": audio_path,
            "video_url": video_path,
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

    async def query_render(self, external_job_id: str) -> ProviderStatus:
        if self.settings.duix_mock:
            await asyncio.sleep(0.15)
            return ProviderStatus(
                state=ProviderJobState.succeeded,
                progress=100,
                result_path=f"results/{external_job_id}.mp4",
                message="mock render completed",
                raw={"code": 10000, "data": {"status": 2, "progress": 100}},
            )

        payload = await self._request("GET", "/query", params={"code": external_job_id})
        if payload.get("code") == 10004:
            return ProviderStatus(ProviderJobState.processing, 0, None, payload.get("msg"), payload)
        if payload.get("code") in {9999, 10002, 10003}:
            return ProviderStatus(ProviderJobState.failed, 0, None, payload.get("msg"), payload)
        if payload.get("code") != 10000:
            raise DuixProviderError(payload.get("msg") or f"Unexpected Duix response: {payload}")

        data: dict[str, Any] = payload.get("data") or {}
        status = data.get("status")
        progress = _progress(data.get("progress"))
        if status == 2:
            return ProviderStatus(ProviderJobState.succeeded, 100, data.get("result"), data.get("msg"), payload)
        if status == 3:
            return ProviderStatus(ProviderJobState.failed, progress, None, data.get("msg"), payload)
        return ProviderStatus(ProviderJobState.processing, progress, None, data.get("msg"), payload)

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


def _progress(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 1:
        number *= 100
    return max(0, min(100, int(number)))
