from collections.abc import Callable
from dataclasses import replace

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import Principal, get_principal
from app.models.identity import Permission, Role, RolePermission


PERMISSIONS = (
    "project.read",
    "project.write",
    "production_order.read",
    "production_order.write",
    "production_order.control",
    "asset.read",
    "asset.write",
    "provider.read",
    "provider.manage",
    "ai_provider.read",
    "ai_provider.manage",
    "usage.read",
    "billing.read",
    "billing.manage",
    "tenant.manage_members",
    "tenant.manage_settings",
)

BUILTIN_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(PERMISSIONS),
    "admin": frozenset(PERMISSIONS),
    "member": frozenset(
        {
            "project.read",
            "project.write",
            "production_order.read",
            "production_order.write",
            "production_order.control",
            "asset.read",
            "asset.write",
            "provider.read",
            "ai_provider.read",
            "usage.read",
        }
    ),
    "viewer": frozenset(
        {
            "project.read",
            "production_order.read",
            "asset.read",
            "provider.read",
            "ai_provider.read",
            "usage.read",
            "billing.read",
        }
    ),
}


async def permissions_for_role(
    session: AsyncSession,
    role_id: str | None,
    role_key: str,
) -> frozenset[str]:
    resolved_role_id = role_id
    if resolved_role_id is None:
        resolved_role_id = await session.scalar(select(Role.id).where(Role.key == role_key))
    if resolved_role_id is None:
        return BUILTIN_ROLE_PERMISSIONS.get(role_key, frozenset())
    result = await session.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == resolved_role_id)
    )
    values = frozenset(result.all())
    return values or BUILTIN_ROLE_PERMISSIONS.get(role_key, frozenset())


class AuthorizationService:
    @staticmethod
    def require(principal: Principal, permission: str) -> Principal:
        if permission not in principal.permissions:
            raise HTTPException(status_code=403, detail=f"缺少权限：{permission}")
        return principal


def require_permission(permission: str) -> Callable[..., Principal]:
    if permission not in PERMISSIONS:
        raise ValueError(f"未知权限：{permission}")

    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        return AuthorizationService.require(principal, permission)

    return dependency


def with_permissions(principal: Principal, permissions: set[str]) -> Principal:
    return replace(principal, permissions=frozenset(permissions))
