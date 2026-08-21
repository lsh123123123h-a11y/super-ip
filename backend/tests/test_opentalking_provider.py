import httpx
import pytest

from app.core.config import Settings
from app.providers.base import AvatarRenderInput, ProviderJobState
from app.providers.opentalking import OpenTalkingProvider


@pytest.mark.asyncio
async def test_opentalking_probe_and_render_bridge_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/models":
            return httpx.Response(200, json={"models": ["fasterliveportrait"]})
        if request.method == "POST":
            return httpx.Response(200, json={"job_id": "ot-job-1", "status": "queued"})
        return httpx.Response(
            200,
            json={"job_id": "ot-job-1", "status": "completed", "progress": 100, "result_url": "https://cdn.local/final.mp4"},
        )

    settings = Settings(
        opentalking_base_url="http://opentalking.local",
        opentalking_render_enabled=True,
    )
    async with httpx.AsyncClient(
        base_url=settings.opentalking_base_url,
        transport=httpx.MockTransport(handler),
    ) as client:
        provider = OpenTalkingProvider(settings, client)
        probe = await provider.probe()
        submission = await provider.submit_render(
            external_job_id="workflow-1-1",
            request=AvatarRenderInput(
                script="hello",
                audio_path="/assets/audio.wav",
                video_path="/assets/avatar.mp4",
                aspect_ratio="9:16",
                quality="1080p",
                provider_options={"model": "fasterliveportrait"},
            ),
        )
        status = await provider.query_render(submission.external_job_id)

    assert probe["reachable"] is True
    assert submission.external_job_id == "ot-job-1"
    assert status.state == ProviderJobState.succeeded
    assert status.result_path == "https://cdn.local/final.mp4"
