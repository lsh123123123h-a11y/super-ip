import json

import httpx
import pytest

from app.agent.brain import StructuredBrainRequest
from app.integrations.new_api_brain import BrainGatewayError, NewApiBrainAdapter


def _request() -> StructuredBrainRequest:
    return StructuredBrainRequest(
        purpose="contract-test",
        system_instruction="只返回 JSON",
        user_input={"goal": "测试"},
        output_schema={"type": "object"},
    )


@pytest.mark.asyncio
async def test_new_api_adapter_uses_openai_compatible_contract() -> None:
    observed: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "deepseek-reasoner",
                "choices": [
                    {"message": {"content": '```json\n{"goal":"ok","steps":[]}\n```'}}
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
        )

    adapter = NewApiBrainAdapter(
        base_url="https://gateway.example/v1",
        api_key="secret-test-key",
        default_model="reasoning-default",
        transport=httpx.MockTransport(handler),
    )
    response = await adapter.complete_structured(_request())

    assert observed["url"] == "https://gateway.example/v1/chat/completions"
    assert observed["authorization"] == "Bearer secret-test-key"
    assert observed["body"]["model"] == "reasoning-default"
    assert observed["body"]["response_format"] == {"type": "json_object"}
    assert response.output == {"goal": "ok", "steps": []}
    assert response.model_ref == "deepseek-reasoner"
    assert response.gateway_ref == "new-api"
    assert response.usage["total_tokens"] == 18


@pytest.mark.asyncio
async def test_new_api_adapter_fails_safely_on_non_object_content() -> None:
    adapter = NewApiBrainAdapter(
        base_url="https://gateway.example",
        api_key="secret-test-key",
        default_model="reasoning-default",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "[1, 2, 3]"}}]},
            )
        ),
    )

    with pytest.raises(BrainGatewayError, match="JSON 必须是对象"):
        await adapter.complete_structured(_request())


@pytest.mark.asyncio
async def test_new_api_probe_uses_models_endpoint() -> None:
    adapter = NewApiBrainAdapter(
        base_url="https://gateway.example",
        api_key="secret-test-key",
        default_model="reasoning-default",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"id": "model-1"}]})
        ),
    )

    assert await adapter.probe() == {
        "ok": True,
        "gateway_ref": "new-api",
        "model_count": 1,
    }
