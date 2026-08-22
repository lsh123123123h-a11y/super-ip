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
    "agent_step_execution_id",
    "trace_id",
}


@dataclass(frozen=True, slots=True)
class ResolvedBrain:
    adapter: BrainPort
    provider_config_id: str | None
    provider_source: str
    requested_model: str
    model_binding_id: str | None
    provider_config_version: int | None
    adapter_type: str
    adapter_version: str
    routing_policy: str = "model_alias"
    routing_policy_version: str = "1.0.0"


async def resolve_brain_binding_snapshot(
    tenant_id: str,
    model_alias: str,
) -> dict[str, Any]:
    """Resolve mutable alias routing once without persisting any credential."""

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
            return {
                "model_alias": model_alias,
                "model_binding_id": binding.id,
                "provider_config_id": provider.id,
                "provider_config_version": provider.config_version,
                "provider_source": "database",
                "adapter_type": provider.adapter_type,
                "adapter_version": "1.0.0",
                "base_url": provider.base_url,
                "requested_model": binding.upstream_model,
                "timeout_seconds": provider.timeout_seconds,
                "routing_policy": "model_alias",
                "routing_policy_version": "1.0.0",
            }

    settings = get_settings()
    if create_configured_brain() is not None:
        return {
            "model_alias": model_alias,
            "model_binding_id": None,
            "provider_config_id": None,
            "provider_config_version": None,
            "provider_source": "bootstrap_env",
            "adapter_type": "new_api",
            "adapter_version": "1.0.0",
            "base_url": settings.model_gateway_base_url,
            "requested_model": settings.model_gateway_default_model,
            "timeout_seconds": settings.model_gateway_timeout_seconds,
            "routing_policy": "bootstrap_env",
            "routing_policy_version": "1.0.0",
        }
    raise BrainConfigurationError(
        f"model alias {model_alias} 尚未绑定可用的 AI Provider"
    )


async def _resolve_brain(
    tenant_id: str,
    model_alias: str,
    pinned_binding: dict[str, Any] | None = None,
) -> ResolvedBrain:
    if pinned_binding is not None:
        if pinned_binding.get("resolution_error"):
            raise BrainConfigurationError(str(pinned_binding["resolution_error"]))
        if pinned_binding.get("model_alias") != model_alias:
            raise BrainConfigurationError("持久化模型绑定与请求的 model alias 不一致")
        provider_source = str(pinned_binding.get("provider_source") or "")
        if provider_source == "database":
            provider_config_id = str(pinned_binding.get("provider_config_id") or "")
            async with SessionLocal() as session:
                provider = await session.get(AIProviderConfig, provider_config_id)
                if provider is None or provider.tenant_id != tenant_id:
                    raise BrainConfigurationError("持久化模型绑定对应的 Provider 已不存在")
                if not provider.enabled:
                    raise BrainConfigurationError("持久化模型绑定对应的 Provider 已停用")
                try:
                    api_key = ProviderSecretCipher().decrypt(provider.secret_ciphertext)
                except SecretEncryptionError as exc:
                    raise BrainConfigurationError(str(exc)) from exc
        elif provider_source == "bootstrap_env":
            provider_config_id = ""
            api_key = get_settings().model_gateway_api_key
        else:
            raise BrainConfigurationError("持久化模型绑定来源无效")
        return ResolvedBrain(
            adapter=NewApiBrainAdapter(
                base_url=str(pinned_binding.get("base_url") or ""),
                api_key=api_key,
                default_model=str(pinned_binding.get("requested_model") or ""),
                timeout_seconds=float(pinned_binding.get("timeout_seconds") or 120),
            ),
            provider_config_id=provider_config_id or None,
            provider_source=provider_source,
            requested_model=str(pinned_binding.get("requested_model") or ""),
            model_binding_id=pinned_binding.get("model_binding_id"),
            provider_config_version=pinned_binding.get("provider_config_version"),
            adapter_type=str(pinned_binding.get("adapter_type") or "new_api"),
            adapter_version=str(pinned_binding.get("adapter_version") or "1.0.0"),
            routing_policy=str(pinned_binding.get("routing_policy") or "model_alias"),
            routing_policy_version=str(
                pinned_binding.get("routing_policy_version") or "1.0.0"
            ),
        )
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
                model_binding_id=binding.id,
                provider_config_version=provider.config_version,
                adapter_type=provider.adapter_type,
                adapter_version="1.0.0",
            )

    bootstrap = create_configured_brain()
    settings = get_settings()
    if bootstrap is not None:
        return ResolvedBrain(
            adapter=bootstrap,
            provider_config_id=None,
            provider_source="bootstrap_env",
            requested_model=settings.model_gateway_default_model,
            model_binding_id=None,
            provider_config_version=None,
            adapter_type="new_api",
            adapter_version="1.0.0",
            routing_policy="bootstrap_env",
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

    def __init__(
        self,
        tenant_id: str,
        binding_snapshots: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.binding_snapshots = binding_snapshots or {}

    async def complete_structured(
        self,
        request: StructuredBrainRequest,
    ) -> StructuredBrainResponse:
        resolved = await _resolve_brain(
            self.tenant_id,
            request.model_alias,
            self.binding_snapshots.get(request.model_alias),
        )
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
                model_binding_id=resolved.model_binding_id,
                provider_config_version=resolved.provider_config_version,
                adapter_type=resolved.adapter_type,
                adapter_version=resolved.adapter_version,
                routing_policy=resolved.routing_policy,
                routing_policy_version=resolved.routing_policy_version,
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


def create_managed_brain(
    tenant_id: str,
    binding_snapshots: dict[str, dict[str, Any]] | None = None,
) -> BrainPort:
    return ManagedBrainPort(tenant_id, binding_snapshots)
