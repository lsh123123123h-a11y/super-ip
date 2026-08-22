import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import Principal
from app.models.identity import ExternalIdentity, Membership, Role, Tenant, User


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9-]+", "-", value).strip("-").lower()
    return normalized[:100] or "tenant"


async def ensure_principal_records(session: AsyncSession, principal: Principal) -> None:
    if principal.auth_type != "development":
        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == principal.tenant_id,
                Membership.user_id == principal.user_id,
                Membership.status == "active",
            )
        )
        if membership is None:
            raise PermissionError("生产身份不能自动创建租户成员关系")
        return
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        tenant = Tenant(
            id=principal.tenant_id,
            slug=_slug(principal.tenant_id),
            name="本地开发工作空间" if principal.tenant_id == "local-tenant" else principal.tenant_id,
        )
        session.add(tenant)

    user = await session.get(User, principal.user_id)
    if user is None:
        user = User(
            id=principal.user_id,
            external_subject=principal.user_id,
            display_name="本地用户" if principal.user_id == "local-user" else principal.user_id,
        )
        session.add(user)

    await session.flush()
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == principal.tenant_id,
            Membership.user_id == principal.user_id,
        )
    )
    if membership is None:
        role_id = await session.scalar(select(Role.id).where(Role.key == "owner"))
        session.add(
            Membership(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                role_id=role_id,
                role="owner",
            )
        )
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == "development",
            ExternalIdentity.subject == principal.user_id,
        )
    )
    if identity is None:
        session.add(
            ExternalIdentity(
                user_id=principal.user_id,
                issuer="development",
                subject=principal.user_id,
            )
        )
        await session.flush()
