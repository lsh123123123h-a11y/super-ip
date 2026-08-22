import json
from decimal import Decimal, InvalidOperation
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
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str = "BRAIN_GATEWAY_ERROR",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


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

    def _validate_configuration(self, *, require_model: bool = True) -> None:
        if not self.base_url or not self.api_key:
            raise BrainConfigurationError("模型网关地址和密钥必须完整配置")
        if require_model and not self.default_model:
            raise BrainConfigurationError("模型网关默认模型尚未配置")

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
        require_model: bool = True,
    ) -> dict[str, Any]:
        self._validate_configuration(require_model=require_model)
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
                f"模型网关请求失败（HTTP {exc.response.status_code}）",
                status_code=exc.response.status_code,
                error_code="BRAIN_GATEWAY_HTTP_ERROR",
            ) from exc
        except httpx.TimeoutException as exc:
            raise BrainGatewayError(
                "模型网关请求超时",
                error_code="BRAIN_GATEWAY_TIMEOUT",
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
        reported_cost = _reported_cost(payload, usage_payload)
        return StructuredBrainResponse(
            output=_json_object(content),
            model_ref=str(payload.get("model") or model),
            gateway_ref="new-api",
            usage=usage,
            raw_response_id=str(payload["id"]) if payload.get("id") else None,
            reported_cost=reported_cost,
            cost_currency=(
                str(usage_payload.get("cost_currency") or payload.get("cost_currency"))
                if reported_cost is not None
                else None
            ),
        )

    async def list_models(self) -> list[str]:
        payload = await self._request("GET", "models", require_model=False)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise BrainGatewayError("模型网关返回的模型目录格式无效")
        models = {
            str(item.get("id")).strip()
            for item in rows
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        return sorted(models)

    async def probe(self) -> dict[str, Any]:
        models = await self.list_models()
        return {
            "ok": True,
            "gateway_ref": "new-api",
            "model_count": len(models),
        }


def _reported_cost(
    payload: dict[str, Any],
    usage_payload: dict[str, Any],
) -> Decimal | None:
    value = usage_payload.get("cost")
    if value is None:
        value = payload.get("cost")
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
