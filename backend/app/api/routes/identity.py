from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.principal import Principal
from app.schemas.identity import (
    MemberRead,
    MemberRoleUpdate,
    RoleRead,
    ServicePrincipalCreate,
    ServicePrincipalRead,
)
from app.services.authorization_service import require_permission
from app.services.identity_admin_service import (
    create_service_principal,
    list_members,
    list_roles,
    list_service_principals,
    revoke_service_principal,
    update_member_role,
)


router = APIRouter(prefix="/admin/identity", tags=["admin-identity"])


@router.get("/members", response_model=list[MemberRead])
async def get_members(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("tenant.manage_members")),
) -> list[MemberRead]:
    return await list_members(session, principal.tenant_id)


@router.patch("/members/{user_id}/role", response_model=MemberRead)
async def patch_member_role(
    user_id: str,
    payload: MemberRoleUpdate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("tenant.manage_members")),
) -> MemberRead:
    try:
        return await update_member_role(
            session,
            tenant_id=principal.tenant_id,
            user_id=user_id,
            role_key=payload.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/roles", response_model=list[RoleRead])
async def get_roles(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("tenant.manage_members")),
) -> list[RoleRead]:
    return await list_roles(session)


@router.get("/service-principals", response_model=list[ServicePrincipalRead])
async def get_service_principals(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("tenant.manage_members")),
) -> list[ServicePrincipalRead]:
    return await list_service_principals(session, principal.tenant_id)


@router.post(
    "/service-principals",
    response_model=ServicePrincipalRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_service_principal(
    payload: ServicePrincipalCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("tenant.manage_members")),
) -> ServicePrincipalRead:
    try:
        return await create_service_principal(session, principal=principal, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/service-principals/{service_principal_id}/revoke", response_model=ServicePrincipalRead)
async def post_revoke_service_principal(
    service_principal_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("tenant.manage_members")),
) -> ServicePrincipalRead:
    try:
        return await revoke_service_principal(
            session, principal.tenant_id, service_principal_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
