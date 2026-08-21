from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import Principal
from app.core.secrets import ProviderSecretCipher, SecretEncryptionError, secret_hint
from app.integrations.new_api_brain import BrainGatewayError, NewApiBrainAdapter
from app.models.ai_provider import AIInvocation, AIModelBinding, AIProviderConfig
from app.schemas.ai_providers import (
    AIInvocationPage,
    AIInvocationRead,
    AIInvocationSummary,
    AIModelBindingRead,
    AIModelBindingWrite,
    AIProviderConnectionResult,
    AIProviderRead,
    AIProviderWrite,
)


DEFAULT_BRAIN_ALIASES = ("reasoning.default", "writing.default")


class AIProviderNotFoundError(LookupError):
    pass


class AIProviderConflictError(ValueError):
    pass


async def _provider_or_error(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider_id: str,
) -> AIProviderConfig:
    provider = await session.scalar(
        select(AIProviderConfig).where(
            AIProviderConfig.id == provider_id,
            AIProviderConfig.tenant_id == tenant_id,
        )
    )
    if provider is None:
        raise AIProviderNotFoundError("AI Provider 不存在")
    return provider


async def _write_bindings(
    session: AsyncSession,
    *,
    provider: AIProviderConfig,
    bindings: list[AIModelBindingWrite],
) -> None:
    aliases = [item.model_alias for item in bindings]
    if len(aliases) != len(set(aliases)):
        raise AIProviderConflictError("同一个 model alias 不能重复绑定")
    enabled_aliases = {item.model_alias for item in bindings if item.enabled}
    missing_defaults = sorted(set(DEFAULT_BRAIN_ALIASES) - enabled_aliases)
    if missing_defaults:
        raise AIProviderConflictError(
            "New API Brain 必须绑定 reasoning.default 与 writing.default"
        )

    existing = list(
        (
            await session.scalars(
                select(AIModelBinding).where(
                    AIModelBinding.tenant_id == provider.tenant_id,
                    AIModelBinding.model_alias.in_(aliases),
                )
            )
        ).all()
    ) if aliases else []
    by_alias = {item.model_alias: item for item in existing}
    for binding in bindings:
        row = by_alias.get(binding.model_alias)
        if row is None:
            row = AIModelBinding(
                tenant_id=provider.tenant_id,
                provider_config_id=provider.id,
                model_alias=binding.model_alias,
                upstream_model=binding.upstream_model.strip(),
                enabled=binding.enabled,
            )
            session.add(row)
        else:
            row.provider_config_id = provider.id
            row.upstream_model = binding.upstream_model.strip()
            row.enabled = binding.enabled

    delete_statement = delete(AIModelBinding).where(
        AIModelBinding.provider_config_id == provider.id
    )
    if aliases:
        delete_statement = delete_statement.where(
            AIModelBinding.model_alias.not_in(aliases)
        )
    await session.execute(delete_statement)
    await session.flush()


async def create_ai_provider(
    session: AsyncSession,
    *,
    principal: Principal,
    payload: AIProviderWrite,
) -> AIProviderConfig:
    if payload.api_key is None:
        raise AIProviderConflictError("新建 Provider 必须填写 API Key")
    duplicate = await session.scalar(
        select(AIProviderConfig.id).where(
            AIProviderConfig.tenant_id == principal.tenant_id,
            AIProviderConfig.name == payload.name.strip(),
        )
    )
    if duplicate:
        raise AIProviderConflictError("同名 AI Provider 已存在")
    api_key = payload.api_key.get_secret_value().strip()
    cipher = ProviderSecretCipher()
    provider = AIProviderConfig(
        tenant_id=principal.tenant_id,
        name=payload.name.strip(),
        adapter_type=payload.adapter_type,
        base_url=payload.base_url,
        secret_ciphertext=cipher.encrypt(api_key),
        secret_hint=secret_hint(api_key),
        capability_types=["brain", "llm"],
        default_model=payload.default_model.strip(),
        timeout_seconds=payload.timeout_seconds,
        enabled=payload.enabled,
        status="untested" if payload.enabled else "disabled",
        created_by_user_id=principal.user_id,
        updated_by_user_id=principal.user_id,
    )
    session.add(provider)
    await session.flush()
    bindings = payload.bindings or [
        AIModelBindingWrite(model_alias=alias, upstream_model=provider.default_model)
        for alias in DEFAULT_BRAIN_ALIASES
    ]
    await _write_bindings(session, provider=provider, bindings=bindings)
    await session.commit()
    await session.refresh(provider)
    return provider


async def update_ai_provider(
    session: AsyncSession,
    *,
    principal: Principal,
    provider_id: str,
    payload: AIProviderWrite,
) -> AIProviderConfig:
    provider = await _provider_or_error(
        session, tenant_id=principal.tenant_id, provider_id=provider_id
    )
    duplicate = await session.scalar(
        select(AIProviderConfig.id).where(
            AIProviderConfig.tenant_id == principal.tenant_id,
            AIProviderConfig.name == payload.name.strip(),
            AIProviderConfig.id != provider.id,
        )
    )
    if duplicate:
        raise AIProviderConflictError("同名 AI Provider 已存在")

    provider.name = payload.name.strip()
    provider.adapter_type = payload.adapter_type
    provider.base_url = payload.base_url
    provider.default_model = payload.default_model.strip()
    provider.timeout_seconds = payload.timeout_seconds
    provider.enabled = payload.enabled
    provider.status = "untested" if payload.enabled else "disabled"
    provider.last_error_code = None
    provider.last_error_message = None
    provider.config_version += 1
    provider.updated_by_user_id = principal.user_id
    if payload.api_key is not None and payload.api_key.get_secret_value().strip():
        api_key = payload.api_key.get_secret_value().strip()
        provider.secret_ciphertext = ProviderSecretCipher().encrypt(api_key)
        provider.secret_hint = secret_hint(api_key)
    if payload.bindings is not None:
        await _write_bindings(session, provider=provider, bindings=payload.bindings)
    await session.commit()
    await session.refresh(provider)
    return provider


async def set_ai_provider_enabled(
    session: AsyncSession,
    *,
    principal: Principal,
    provider_id: str,
    enabled: bool,
) -> AIProviderConfig:
    provider = await _provider_or_error(
        session, tenant_id=principal.tenant_id, provider_id=provider_id
    )
    provider.enabled = enabled
    provider.status = "untested" if enabled else "disabled"
    provider.updated_by_user_id = principal.user_id
    provider.config_version += 1
    await session.commit()
    await session.refresh(provider)
    return provider


async def test_ai_provider_connection(
    *,
    base_url: str,
    api_key: str,
    timeout_seconds: int,
) -> AIProviderConnectionResult:
    adapter = NewApiBrainAdapter(
        base_url=base_url,
        api_key=api_key,
        default_model="",
        timeout_seconds=timeout_seconds,
    )
    started = perf_counter()
    models = await adapter.list_models()
    if not models:
        raise BrainGatewayError("模型网关连接成功，但当前 Token 没有可用模型")
    return AIProviderConnectionResult(
        ok=True,
        gateway_ref="new-api",
        model_count=len(models),
        models=models,
        latency_ms=max(0, round((perf_counter() - started) * 1000)),
    )


async def test_saved_ai_provider(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider_id: str,
) -> AIProviderConnectionResult:
    provider = await _provider_or_error(
        session, tenant_id=tenant_id, provider_id=provider_id
    )
    tested_at = datetime.now(UTC)
    try:
        api_key = ProviderSecretCipher().decrypt(provider.secret_ciphertext)
        result = await test_ai_provider_connection(
            base_url=provider.base_url,
            api_key=api_key,
            timeout_seconds=min(provider.timeout_seconds, 120),
        )
    except (BrainGatewayError, SecretEncryptionError) as exc:
        provider.status = "error"
        provider.last_tested_at = tested_at
        provider.last_error_code = getattr(exc, "error_code", type(exc).__name__)[:128]
        provider.last_error_message = str(exc)[:1000]
        await session.commit()
        raise
    provider.status = "ready" if provider.enabled else "disabled"
    provider.last_tested_at = tested_at
    provider.last_error_code = None
    provider.last_error_message = None
    await session.commit()
    return result


async def resolve_connection_test_inputs(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider_id: str | None,
    base_url: str | None,
    api_key: str | None,
    timeout_seconds: int | None,
) -> tuple[str, str, int]:
    provider = None
    if provider_id:
        provider = await _provider_or_error(
            session, tenant_id=tenant_id, provider_id=provider_id
        )
    resolved_url = (base_url or (provider.base_url if provider else "")).strip().rstrip("/")
    resolved_key = (api_key or "").strip()
    if not resolved_key and provider is not None:
        resolved_key = ProviderSecretCipher().decrypt(provider.secret_ciphertext)
    resolved_timeout = timeout_seconds or (provider.timeout_seconds if provider else 30)
    if not resolved_url or not resolved_key:
        raise AIProviderConflictError("测试连接需要 Base URL 和 API Key")
    return resolved_url, resolved_key, min(resolved_timeout, 120)


async def _provider_read(
    session: AsyncSession,
    provider: AIProviderConfig,
) -> AIProviderRead:
    bindings = list(
        (
            await session.scalars(
                select(AIModelBinding)
                .where(AIModelBinding.provider_config_id == provider.id)
                .order_by(AIModelBinding.model_alias)
            )
        ).all()
    )
    stats = (
        await session.execute(
            select(
                func.count(AIInvocation.id),
                func.count(AIInvocation.id).filter(AIInvocation.success.is_(True)),
                func.count(AIInvocation.id).filter(AIInvocation.success.is_(False)),
                func.coalesce(func.sum(AIInvocation.total_tokens), 0),
                func.avg(AIInvocation.latency_ms),
                func.max(AIInvocation.started_at),
            ).where(AIInvocation.provider_config_id == provider.id)
        )
    ).one()
    return AIProviderRead(
        id=provider.id,
        name=provider.name,
        adapter_type=provider.adapter_type,
        base_url=provider.base_url,
        secret_configured=bool(provider.secret_ciphertext),
        secret_hint=provider.secret_hint,
        capability_types=list(provider.capability_types or []),
        default_model=provider.default_model,
        timeout_seconds=provider.timeout_seconds,
        enabled=provider.enabled,
        status=provider.status,
        config_version=provider.config_version,
        last_tested_at=provider.last_tested_at,
        last_error_code=provider.last_error_code,
        last_error_message=provider.last_error_message,
        bindings=[AIModelBindingRead.model_validate(item) for item in bindings],
        request_count=int(stats[0] or 0),
        success_count=int(stats[1] or 0),
        failure_count=int(stats[2] or 0),
        total_tokens=int(stats[3] or 0),
        average_latency_ms=round(float(stats[4])) if stats[4] is not None else None,
        last_invoked_at=stats[5],
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


async def list_ai_providers(
    session: AsyncSession,
    *,
    tenant_id: str,
) -> list[AIProviderRead]:
    providers = list(
        (
            await session.scalars(
                select(AIProviderConfig)
                .where(AIProviderConfig.tenant_id == tenant_id)
                .order_by(AIProviderConfig.created_at)
            )
        ).all()
    )
    return [await _provider_read(session, provider) for provider in providers]


async def get_ai_provider_read(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider_id: str,
) -> AIProviderRead:
    return await _provider_read(
        session,
        await _provider_or_error(
            session, tenant_id=tenant_id, provider_id=provider_id
        ),
    )


async def list_ai_invocations(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int = 50,
) -> AIInvocationPage:
    rows = list(
        (
            await session.execute(
                select(AIInvocation, AIProviderConfig.name)
                .outerjoin(
                    AIProviderConfig,
                    AIProviderConfig.id == AIInvocation.provider_config_id,
                )
                .where(AIInvocation.tenant_id == tenant_id)
                .order_by(AIInvocation.started_at.desc())
                .limit(limit)
            )
        ).all()
    )
    stats = (
        await session.execute(
            select(
                func.count(AIInvocation.id),
                func.count(AIInvocation.id).filter(AIInvocation.success.is_(True)),
                func.count(AIInvocation.id).filter(AIInvocation.success.is_(False)),
                func.coalesce(func.sum(AIInvocation.input_tokens), 0),
                func.coalesce(func.sum(AIInvocation.output_tokens), 0),
                func.coalesce(func.sum(AIInvocation.total_tokens), 0),
                func.avg(AIInvocation.latency_ms),
                func.sum(AIInvocation.cost_amount),
            ).where(AIInvocation.tenant_id == tenant_id)
        )
    ).one()
    return AIInvocationPage(
        summary=AIInvocationSummary(
            request_count=int(stats[0] or 0),
            success_count=int(stats[1] or 0),
            failure_count=int(stats[2] or 0),
            input_tokens=int(stats[3] or 0),
            output_tokens=int(stats[4] or 0),
            total_tokens=int(stats[5] or 0),
            average_latency_ms=(
                round(float(stats[6])) if stats[6] is not None else None
            ),
            reported_cost=stats[7],
        ),
        items=[
            AIInvocationRead(
                id=invocation.id,
                provider_config_id=invocation.provider_config_id,
                provider_name=provider_name or "Bootstrap / 已移除 Provider",
                provider_source=invocation.provider_source,
                invocation_kind=invocation.invocation_kind,
                purpose=invocation.purpose,
                model_alias=invocation.model_alias,
                requested_model=invocation.requested_model,
                response_model=invocation.response_model,
                provider_request_id=invocation.provider_request_id,
                success=invocation.success,
                http_status=invocation.http_status,
                input_tokens=invocation.input_tokens,
                output_tokens=invocation.output_tokens,
                total_tokens=invocation.total_tokens,
                cost_amount=invocation.cost_amount,
                cost_currency=invocation.cost_currency,
                latency_ms=invocation.latency_ms,
                error_code=invocation.error_code,
                error_message=invocation.error_message,
                metadata_payload=dict(invocation.metadata_payload or {}),
                started_at=invocation.started_at,
                finished_at=invocation.finished_at,
                created_at=invocation.created_at,
            )
            for invocation, provider_name in rows
        ],
    )
