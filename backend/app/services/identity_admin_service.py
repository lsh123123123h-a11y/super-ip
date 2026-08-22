import secrets
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import service_secret_digest
from app.core.config import get_settings
from app.core.principal import Principal
from app.models.identity import Membership, Permission, Role, RolePermission, ServicePrincipal, User
from app.schemas.identity import MemberRead, RoleRead, ServicePrincipalCreate, ServicePrincipalRead
from app.services.authorization_service import PERMISSIONS


async def list_members(session: AsyncSession, tenant_id: str) -> list[MemberRead]:
    rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.tenant_id == tenant_id)
            .order_by(Membership.created_at)
        )
    ).all()
    return [
        MemberRead(
            user_id=user.id,
            display_name=user.display_name,
            external_subject=user.external_subject,
            role=membership.role,
            status=membership.status,
            created_at=membership.created_at,
        )
        for membership, user in rows
    ]


async def list_roles(session: AsyncSession) -> list[RoleRead]:
    roles = list((await session.scalars(select(Role).order_by(Role.key))).all())
    result: list[RoleRead] = []
    for role in roles:
        permissions = list(
            (
                await session.scalars(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == role.id)
                    .order_by(Permission.code)
                )
            ).all()
        )
        result.append(RoleRead(key=role.key, name=role.name, permissions=permissions))
    return result


async def update_member_role(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    role_key: str,
) -> MemberRead:
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user_id,
        )
    )
    role = await session.scalar(select(Role).where(Role.key == role_key))
    user = await session.get(User, user_id)
    if membership is None or role is None or user is None:
        raise LookupError("成员或角色不存在")
    membership.role_id = role.id
    membership.role = role.key
    await session.commit()
    return MemberRead(
        user_id=user.id,
        display_name=user.display_name,
        external_subject=user.external_subject,
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
    )


async def create_service_principal(
    session: AsyncSession,
    *,
    principal: Principal,
    payload: ServicePrincipalCreate,
) -> ServicePrincipalRead:
    unknown = sorted(set(payload.permissions) - set(PERMISSIONS))
    if unknown:
        raise ValueError(f"未知权限：{', '.join(unknown)}")
    secret = secrets.token_urlsafe(32)
    client_id = f"sp_{secrets.token_hex(12)}"
    row = ServicePrincipal(
        tenant_id=principal.tenant_id,
        client_id=client_id,
        name=payload.name.strip(),
        secret_digest=service_secret_digest(
            secret, get_settings().service_principal_pepper
        ),
        permissions=sorted(set(payload.permissions)),
        created_by_user_id=principal.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ServicePrincipalRead.model_validate(row).model_copy(
        update={"initial_secret": secret}
    )


async def list_service_principals(
    session: AsyncSession, tenant_id: str
) -> list[ServicePrincipalRead]:
    rows = list(
        (
            await session.scalars(
                select(ServicePrincipal)
                .where(ServicePrincipal.tenant_id == tenant_id)
                .order_by(ServicePrincipal.created_at.desc())
            )
        ).all()
    )
    return [ServicePrincipalRead.model_validate(row) for row in rows]


async def revoke_service_principal(
    session: AsyncSession, tenant_id: str, service_principal_id: str
) -> ServicePrincipalRead:
    from datetime import UTC, datetime

    row = await session.scalar(
        select(ServicePrincipal).where(
            ServicePrincipal.id == service_principal_id,
            ServicePrincipal.tenant_id == tenant_id,
        )
    )
    if row is None:
        raise LookupError("Service Principal 不存在")
    row.status = "revoked"
    row.revoked_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return ServicePrincipalRead.model_validate(row)
