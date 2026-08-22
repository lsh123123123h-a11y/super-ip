from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.principal import Principal, get_principal
from app.core.secrets import SecretEncryptionError
from app.integrations.new_api_brain import BrainGatewayError
from app.models.identity import Membership
from app.schemas.ai_providers import (
    AIInvocationPage,
    AIProviderConnectionResult,
    AIProviderConnectionTest,
    AIProviderEnabledUpdate,
    AIProviderRead,
    AIProviderWrite,
)
from app.services.ai_provider_service import (
    AIProviderConflictError,
    AIProviderNotFoundError,
    create_ai_provider,
    get_ai_provider_read,
    list_ai_invocations,
    list_ai_providers,
    resolve_connection_test_inputs,
    set_ai_provider_enabled,
    test_ai_provider_connection,
    test_saved_ai_provider,
    update_ai_provider,
)
from app.services.identity_service import ensure_principal_records


router = APIRouter(prefix="/admin/ai-providers", tags=["admin-ai-providers"])


async def require_ai_provider_admin(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> Principal:
    await ensure_principal_records(session, principal)
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == principal.tenant_id,
            Membership.user_id == principal.user_id,
            Membership.status == "active",
        )
    )
    if membership is None or membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="只有租户管理员可以管理 AI Provider")
    await session.commit()
    return principal


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AIProviderNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (AIProviderConflictError, SecretEncryptionError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, BrainGatewayError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="AI Provider 管理操作失败")


@router.get("", response_model=list[AIProviderRead])
async def get_ai_providers(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_ai_provider_admin),
) -> list[AIProviderRead]:
    return await list_ai_providers(session, tenant_id=principal.tenant_id)


@router.post("", response_model=AIProviderRead, status_code=status.HTTP_201_CREATED)
async def post_ai_provider(
    payload: AIProviderWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_ai_provider_admin),
) -> AIProviderRead:
    try:
        provider = await create_ai_provider(session, principal=principal, payload=payload)
        return await get_ai_provider_read(
            session, tenant_id=principal.tenant_id, provider_id=provider.id
        )
    except (AIProviderConflictError, SecretEncryptionError) as exc:
        raise _http_error(exc) from exc


@router.put("/{provider_id}", response_model=AIProviderRead)
async def put_ai_provider(
    provider_id: str,
    payload: AIProviderWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_ai_provider_admin),
) -> AIProviderRead:
    try:
        provider = await update_ai_provider(
            session,
            principal=principal,
            provider_id=provider_id,
            payload=payload,
        )
        return await get_ai_provider_read(
            session, tenant_id=principal.tenant_id, provider_id=provider.id
        )
    except (AIProviderConflictError, AIProviderNotFoundError, SecretEncryptionError) as exc:
        raise _http_error(exc) from exc


@router.patch("/{provider_id}/enabled", response_model=AIProviderRead)
async def patch_ai_provider_enabled(
    provider_id: str,
    payload: AIProviderEnabledUpdate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_ai_provider_admin),
) -> AIProviderRead:
    try:
        provider = await set_ai_provider_enabled(
            session,
            principal=principal,
            provider_id=provider_id,
            enabled=payload.enabled,
        )
        return await get_ai_provider_read(
            session, tenant_id=principal.tenant_id, provider_id=provider.id
        )
    except AIProviderNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post("/test-connection", response_model=AIProviderConnectionResult)
async def post_ai_provider_connection_test(
    payload: AIProviderConnectionTest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_ai_provider_admin),
) -> AIProviderConnectionResult:
    try:
        base_url, api_key, timeout_seconds = await resolve_connection_test_inputs(
            session,
            tenant_id=principal.tenant_id,
            provider_id=payload.provider_id,
            base_url=payload.base_url,
            api_key=(payload.api_key.get_secret_value() if payload.api_key else None),
            timeout_seconds=payload.timeout_seconds,
        )
        return await test_ai_provider_connection(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    except (
        AIProviderConflictError,
        AIProviderNotFoundError,
        BrainGatewayError,
        SecretEncryptionError,
    ) as exc:
        raise _http_error(exc) from exc


@router.post("/{provider_id}/test", response_model=AIProviderConnectionResult)
async def post_saved_ai_provider_test(
    provider_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_ai_provider_admin),
) -> AIProviderConnectionResult:
    try:
        return await test_saved_ai_provider(
            session,
            tenant_id=principal.tenant_id,
            provider_id=provider_id,
        )
    except (AIProviderNotFoundError, BrainGatewayError, SecretEncryptionError) as exc:
        raise _http_error(exc) from exc


@router.get("/invocations", response_model=AIInvocationPage)
async def get_ai_invocations(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_ai_provider_admin),
) -> AIInvocationPage:
    return await list_ai_invocations(
        session, tenant_id=principal.tenant_id, limit=limit
    )
