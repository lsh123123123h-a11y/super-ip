import httpx
import pytest

from app.core.config import Settings
from app.providers.base import ProviderJobState
from app.providers.duix import DuixProvider


@pytest.mark.asyncio
async def test_duix_submit_and_success_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/submit"):
            return httpx.Response(200, json={"code": 10000, "msg": "ok"})
        return httpx.Response(
            200,
            json={"code": 10000, "data": {"status": 2, "progress": 1, "result": "results/final.mp4"}},
        )

    async with httpx.AsyncClient(
        base_url="http://duix.local/easy",
        transport=httpx.MockTransport(handler),
    ) as client:
        provider = DuixProvider(Settings(), client)
        submission = await provider.submit_render(
            external_job_id="job-1",
            audio_path="/code/data/a.wav",
            video_path="/code/data/v.mp4",
        )
        status = await provider.query_render(submission.external_job_id)

    assert submission.external_job_id == "job-1"
    assert status.state == ProviderJobState.succeeded
    assert status.progress == 100
    assert status.result_path == "results/final.mp4"


@pytest.mark.asyncio
async def test_duix_failure_mapping() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"code": 10003, "msg": "render failed"})
    )
    async with httpx.AsyncClient(base_url="http://duix.local/easy", transport=transport) as client:
        status = await DuixProvider(Settings(), client).query_render("job-2")

    assert status.state == ProviderJobState.failed
    assert status.message == "render failed"


@pytest.mark.asyncio
async def test_duix_missing_job_is_treated_as_short_lived_processing_state() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"code": 10004, "msg": "任务不存在", "data": {}})
    )
    async with httpx.AsyncClient(base_url="http://duix.local/easy", transport=transport) as client:
        provider = DuixProvider(Settings(), client)
        status = await provider.query_render("job-not-yet-visible")
        probe = await provider.probe()

    assert status.state == ProviderJobState.processing
    assert status.raw["code"] == 10004
    assert probe["reachable"] is True
    assert probe["response_code"] == 10004
