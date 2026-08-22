import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import select

from app.agent.brain import BrainPort, StructuredBrainRequest, StructuredBrainResponse
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.secrets import ProviderSecretCipher, SecretEncryptionError
from app.integrations.brain_factory import create_configured_brain
from app.integrations.new_api_brain import (
    BrainConfigurationError,
    BrainGatewayError,
    NewApiBrainAdapter,
)
from app.models.ai_provider import AIInvocation, AIModelBinding, AIProviderConfig


SAFE_METADATA_KEYS = {
    "agent_operation_id",
    "plan_version_id",
    "production_order_id",
    "step_key",
    "trace_id",
}


@dataclass(frozen=True, slots=True)
class ResolvedBrain:
    adapter: BrainPort
    provider_config_id: str | None
    provider_source: str
    requested_model: str


async def _resolve_brain(
    tenant_id: str,
    model_alias: str,
) -> ResolvedBrain:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(AIModelBinding, AIProviderConfig)
                .join(
                    AIProviderConfig,
                    AIProviderConfig.id == AIModelBinding.provider_config_id,
                )
                .where(
                    AIModelBinding.tenant_id == tenant_id,
                    AIModelBinding.model_alias == model_alias,
                    AIModelBinding.enabled.is_(True),
                    AIProviderConfig.enabled.is_(True),
                )
            )
        ).one_or_none()
        if row is not None:
            binding, provider = row
            if provider.adapter_type != "new_api":
                raise BrainConfigurationError(
                    f"model alias {model_alias} 绑定了尚未支持的 Adapter"
                )
            try:
                api_key = ProviderSecretCipher().decrypt(provider.secret_ciphertext)
            except SecretEncryptionError as exc:
                raise BrainConfigurationError(str(exc)) from exc
            return ResolvedBrain(
                adapter=NewApiBrainAdapter(
                    base_url=provider.base_url,
                    api_key=api_key,
                    default_model=binding.upstream_model,
                    timeout_seconds=provider.timeout_seconds,
                ),
                provider_config_id=provider.id,
                provider_source="database",
                requested_model=binding.upstream_model,
            )

    bootstrap = create_configured_brain()
    settings = get_settings()
    if bootstrap is not None:
        return ResolvedBrain(
            adapter=bootstrap,
            provider_config_id=None,
            provider_source="bootstrap_env",
            requested_model=settings.model_gateway_default_model,
        )
    raise BrainConfigurationError(
        f"model alias {model_alias} 尚未绑定可用的 AI Provider"
    )


async def brain_alias_available(tenant_id: str, model_alias: str) -> bool:
    try:
        await _resolve_brain(tenant_id, model_alias)
    except BrainConfigurationError:
        return False
    return True


class ManagedBrainPort(BrainPort):
    """Resolve tenant model aliases per call and persist product-level facts."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    async def complete_structured(
        self,
        request: StructuredBrainRequest,
    ) -> StructuredBrainResponse:
        resolved = await _resolve_brain(self.tenant_id, request.model_alias)
        started_at = datetime.now(UTC)
        started = perf_counter()
        metadata = {
            key: value
            for key, value in request.metadata.items()
            if key in SAFE_METADATA_KEYS and value is not None
        }
        invocation_id = await self._start_invocation(
            request=request,
            resolved=resolved,
            started_at=started_at,
            metadata=metadata,
        )
        try:
            response = await resolved.adapter.complete_structured(request)
        except asyncio.CancelledError:
            await self._finish_failure(
                invocation_id=invocation_id,
                provider_config_id=resolved.provider_config_id,
                started=started,
                error_code="BRAIN_CALL_CANCELLED",
                error_message="模型调用被运行时超时或取消",
                http_status=None,
            )
            raise
        except BrainGatewayError as exc:
            await self._finish_failure(
                invocation_id=invocation_id,
                provider_config_id=resolved.provider_config_id,
                started=started,
                error_code=exc.error_code,
                error_message=str(exc),
                http_status=exc.status_code,
            )
            raise
        except Exception as exc:
            await self._finish_failure(
                invocation_id=invocation_id,
                provider_config_id=resolved.provider_config_id,
                started=started,
                error_code=type(exc).__name__,
                error_message="模型调用内部处理失败",
                http_status=None,
            )
            raise
        await self._finish_success(
            invocation_id=invocation_id,
            provider_config_id=resolved.provider_config_id,
            started=started,
            response=response,
        )
        return response

    async def probe(self) -> dict[str, Any]:
        resolved = await _resolve_brain(self.tenant_id, "reasoning.default")
        return await resolved.adapter.probe()

    async def _start_invocation(
        self,
        *,
        request: StructuredBrainRequest,
        resolved: ResolvedBrain,
        started_at: datetime,
        metadata: dict[str, Any],
    ) -> str:
        async with SessionLocal() as session:
            invocation = AIInvocation(
                tenant_id=self.tenant_id,
                provider_config_id=resolved.provider_config_id,
                provider_source=resolved.provider_source,
                invocation_kind="brain.structured",
                purpose=request.purpose,
                model_alias=request.model_alias,
                requested_model=resolved.requested_model,
                metadata_payload=metadata,
                started_at=started_at,
            )
            session.add(invocation)
            await session.commit()
            return invocation.id

    async def _finish_success(
        self,
        *,
        invocation_id: str,
        provider_config_id: str | None,
        started: float,
        response: StructuredBrainResponse,
    ) -> None:
        async with SessionLocal() as session:
            invocation = await session.get(AIInvocation, invocation_id)
            if invocation is None:
                return
            invocation.success = True
            invocation.http_status = 200
            invocation.response_model = response.model_ref
            invocation.provider_request_id = response.raw_response_id
            invocation.input_tokens = response.usage.get("input_tokens")
            invocation.output_tokens = response.usage.get("output_tokens")
            invocation.total_tokens = response.usage.get("total_tokens")
            invocation.cost_amount = response.reported_cost
            invocation.cost_currency = response.cost_currency
            invocation.latency_ms = max(0, round((perf_counter() - started) * 1000))
            invocation.finished_at = datetime.now(UTC)
            if provider_config_id:
                provider = await session.get(AIProviderConfig, provider_config_id)
                if provider is not None and provider.enabled:
                    provider.status = "ready"
                    provider.last_error_code = None
                    provider.last_error_message = None
            await session.commit()

    async def _finish_failure(
        self,
        *,
        invocation_id: str,
        provider_config_id: str | None,
        started: float,
        error_code: str,
        error_message: str,
        http_status: int | None,
    ) -> None:
        safe_message = error_message[:1000]
        async with SessionLocal() as session:
            invocation = await session.get(AIInvocation, invocation_id)
            if invocation is not None:
                invocation.success = False
                invocation.http_status = http_status
                invocation.error_code = error_code[:128]
                invocation.error_message = safe_message
                invocation.latency_ms = max(
                    0, round((perf_counter() - started) * 1000)
                )
                invocation.finished_at = datetime.now(UTC)
            if provider_config_id:
                provider = await session.get(AIProviderConfig, provider_config_id)
                if provider is not None and provider.enabled:
                    provider.status = "error"
                    provider.last_error_code = error_code[:128]
                    provider.last_error_message = safe_message
            await session.commit()


def create_managed_brain(tenant_id: str) -> BrainPort:
    return ManagedBrainPort(tenant_id)
