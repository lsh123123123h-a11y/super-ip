import json
from typing import Any

import httpx

from app.agent.brain import (
    BrainPort,
    StructuredBrainRequest,
    StructuredBrainResponse,
)


class BrainConfigurationError(RuntimeError):
    pass


class BrainGatewayError(RuntimeError):
    pass


def _json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise BrainGatewayError("模型网关未返回结构化文本")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BrainGatewayError("模型网关返回的内容不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise BrainGatewayError("模型网关返回的 JSON 必须是对象")
    return value


class NewApiBrainAdapter(BrainPort):
    """Thin OpenAI-compatible adapter; routing remains New API's responsibility."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        default_model: str,
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.default_model = default_model.strip()
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def _validate_configuration(self) -> None:
        if not self.base_url or not self.api_key or not self.default_model:
            raise BrainConfigurationError("模型网关地址、密钥和默认模型必须完整配置")

    def _endpoint(self, resource: str) -> str:
        root = self.base_url
        if not root.endswith("/v1"):
            root = f"{root}/v1"
        return f"{root}/{resource.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        resource: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_configuration()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    self._endpoint(resource),
                    headers=self._headers(),
                    json=json_payload,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise BrainGatewayError(
                f"模型网关请求失败（HTTP {exc.response.status_code}）"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise BrainGatewayError("模型网关请求或响应解析失败") from exc
        if not isinstance(payload, dict):
            raise BrainGatewayError("模型网关响应必须是 JSON 对象")
        return payload

    async def complete_structured(
        self,
        request: StructuredBrainRequest,
    ) -> StructuredBrainResponse:
        model = self.default_model
        payload = await self._request(
            "POST",
            "chat/completions",
            json_payload={
                "model": model,
                "messages": [
                    {"role": "system", "content": request.system_instruction},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "purpose": request.purpose,
                                "input": request.user_input,
                                "output_schema": request.output_schema,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                ],
                "temperature": request.temperature,
                "response_format": {"type": "json_object"},
                "stream": False,
            },
        )
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BrainGatewayError("模型网关响应缺少 choices.message.content") from exc
        usage_payload = payload.get("usage") or {}
        usage = {
            "input_tokens": int(usage_payload.get("prompt_tokens") or 0),
            "output_tokens": int(usage_payload.get("completion_tokens") or 0),
            "total_tokens": int(usage_payload.get("total_tokens") or 0),
        }
        return StructuredBrainResponse(
            output=_json_object(content),
            model_ref=str(payload.get("model") or model),
            gateway_ref="new-api",
            usage=usage,
            raw_response_id=str(payload["id"]) if payload.get("id") else None,
        )

    async def probe(self) -> dict[str, Any]:
        payload = await self._request("GET", "models")
        models = payload.get("data")
        return {
            "ok": isinstance(models, list),
            "gateway_ref": "new-api",
            "model_count": len(models) if isinstance(models, list) else 0,
        }
