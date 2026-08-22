import asyncio
import hashlib
import hmac
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Callable, Protocol

import jwt
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.principal import Principal
from app.models.identity import (
    AuthenticationAuditEvent,
    ExternalIdentity,
    Membership,
    ServicePrincipal,
    Tenant,
    User,
)
from app.services.authorization_service import permissions_for_role
from app.services.identity_service import ensure_principal_records


IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9_.@:-]+$")
IMPERSONATION_HEADERS = ("x-tenant-id", "x-user-id", "x-owner-id")


class AuthenticationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "authentication_failed") -> None:
        super().__init__(message)
        self.code = code


class AuthProvider(Protocol):
    async def resolve(self, request: Request) -> tuple[Principal, dict[str, Any]]: ...


class DevelopmentAuthProvider:
    def __init__(self, *, allow_trusted_headers: bool = True) -> None:
        self.allow_trusted_headers = allow_trusted_headers

    async def resolve(self, request: Request) -> tuple[Principal, dict[str, Any]]:
        if not self.allow_trusted_headers:
            raise AuthenticationError(
                "production environment 禁止 development identity headers",
                code="development_auth_forbidden",
            )
        tenant_id = (request.headers.get("X-Tenant-Id") or "local-tenant").strip()
        user_id = (
            request.headers.get("X-User-Id")
            or request.headers.get("X-Owner-Id")
            or "local-user"
        ).strip()
        if not tenant_id or not user_id:
            raise AuthenticationError("缺少租户或用户身份上下文", code="missing_identity")
        if not IDENTITY_PATTERN.fullmatch(tenant_id) or not IDENTITY_PATTERN.fullmatch(user_id):
            raise AuthenticationError("身份上下文格式无效", code="invalid_identity")
        return (
            Principal(
                tenant_id=tenant_id,
                user_id=user_id,
                subject=user_id,
                auth_type="development",
                issuer="development",
            ),
            {"sub": user_id, "tenant_id": tenant_id},
        )


class OidcJwtAuthProvider:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        signing_key_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._signing_key_resolver = signing_key_resolver
        self._jwks_client = (
            jwt.PyJWKClient(self.settings.oidc_jwks_url, cache_keys=True, lifespan=300)
            if self.settings.oidc_jwks_url
            else None
        )

    async def resolve(self, request: Request) -> tuple[Principal, dict[str, Any]]:
        if any(request.headers.get(name) for name in IMPERSONATION_HEADERS):
            raise AuthenticationError(
                "生产身份模式禁止 Header impersonation",
                code="header_impersonation_forbidden",
            )
        authorization = request.headers.get("Authorization") or ""
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError("缺少 Bearer Token", code="missing_bearer_token")
        token = token.strip()
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthenticationError("JWT 格式无效", code="invalid_token") from exc
        algorithm = str(header.get("alg") or "")
        if algorithm not in self.settings.oidc_algorithm_list:
            raise AuthenticationError("JWT 签名算法不被允许", code="algorithm_not_allowed")
        try:
            if self._signing_key_resolver is not None:
                key = self._signing_key_resolver(token)
            elif self._jwks_client is not None:
                jwk = await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)
                key = jwk.key
            else:
                raise AuthenticationError("OIDC JWKS 尚未配置", code="oidc_not_configured")
            claims = jwt.decode(
                token,
                key=key,
                algorithms=self.settings.oidc_algorithm_list,
                issuer=self.settings.oidc_issuer,
                audience=self.settings.oidc_audience,
                options={"require": ["exp", "sub"]},
            )
        except AuthenticationError:
            raise
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("JWT 已过期", code="token_expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthenticationError("JWT issuer 无效", code="wrong_issuer") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthenticationError("JWT audience 无效", code="wrong_audience") from exc
        except jwt.ImmatureSignatureError as exc:
            raise AuthenticationError("JWT 尚未生效", code="token_not_active") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationError("JWT 验证失败", code="invalid_token") from exc
        tenant_id = str(claims.get(self.settings.oidc_tenant_claim) or "").strip()
        subject = str(claims.get("sub") or "").strip()
        if not tenant_id or not subject:
            raise AuthenticationError("JWT 缺少 tenant/sub claim", code="missing_claim")
        return (
            Principal(
                tenant_id=tenant_id,
                user_id=subject,
                subject=subject,
                auth_type="oidc",
                issuer=self.settings.oidc_issuer,
            ),
            claims,
        )


class PrincipalResolver:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._development = DevelopmentAuthProvider(
            allow_trusted_headers=self.settings.environment.lower() != "production"
        )
        self._oidc = OidcJwtAuthProvider(self.settings)

    async def resolve(self, request: Request, session: AsyncSession) -> Principal:
        authorization = request.headers.get("Authorization") or ""
        if authorization.lower().startswith("service "):
            return await self._resolve_service(request, session, authorization[8:].strip())
        provider: AuthProvider
        if self.settings.auth_mode == "development":
            provider = self._development
        elif self.settings.auth_mode == "oidc":
            provider = self._oidc
        else:
            raise AuthenticationError("AUTH_MODE 无效", code="auth_mode_invalid")
        principal, claims = await provider.resolve(request)
        try:
            principal = await self._map_user_principal(session, principal)
        except AuthenticationError as exc:
            await self._audit(
                session,
                principal=principal,
                outcome="rejected",
                request=request,
                claims=claims,
                detail=exc.code,
            )
            await session.commit()
            raise
        await self._audit(
            session,
            principal=principal,
            outcome="authenticated",
            request=request,
            claims=claims,
        )
        await session.commit()
        return principal

    async def _map_user_principal(
        self, session: AsyncSession, principal: Principal
    ) -> Principal:
        if principal.auth_type == "development":
            await ensure_principal_records(session, principal)
            membership = await _active_membership(session, principal.tenant_id, principal.user_id)
        else:
            identity = await session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.issuer == principal.issuer,
                    ExternalIdentity.subject == principal.subject,
                )
            )
            user = await session.get(User, identity.user_id) if identity else None
            if user is None:
                user = await session.scalar(
                    select(User).where(User.external_subject == principal.subject)
                )
            if user is None and self.settings.oidc_auto_provision_users:
                user = User(
                    external_subject=principal.subject,
                    display_name=principal.subject,
                    status="active",
                )
                session.add(user)
                await session.flush()
            if user is None or user.status != "active":
                raise AuthenticationError("OIDC 用户未映射到内部身份", code="identity_not_mapped")
            if identity is None:
                identity = ExternalIdentity(
                    user_id=user.id,
                    issuer=principal.issuer or "",
                    subject=principal.subject,
                )
                session.add(identity)
            identity.last_authenticated_at = datetime.now(UTC)
            membership = await _active_membership(session, principal.tenant_id, user.id)
            principal = replace(principal, user_id=user.id)
        if membership is None:
            raise AuthenticationError("用户不属于该租户", code="membership_required")
        permissions = await permissions_for_role(session, membership.role_id, membership.role)
        return replace(
            principal,
            roles=(membership.role,),
            permissions=frozenset(permissions),
        )

    async def _resolve_service(
        self,
        request: Request,
        session: AsyncSession,
        credential: str,
    ) -> Principal:
        client_id, separator, secret = credential.partition(".")
        if not separator or not client_id or not secret:
            raise AuthenticationError("Service credential 格式无效", code="service_credential_invalid")
        service = await session.scalar(
            select(ServicePrincipal).where(
                ServicePrincipal.client_id == client_id,
                ServicePrincipal.status == "active",
            )
        )
        if service is None:
            raise AuthenticationError("Service Principal 不存在", code="service_principal_unknown")
        digest = service_secret_digest(secret, self.settings.service_principal_pepper)
        if not hmac.compare_digest(digest, service.secret_digest):
            raise AuthenticationError("Service credential 无效", code="service_credential_invalid")
        service.last_authenticated_at = datetime.now(UTC)
        principal = Principal(
            tenant_id=service.tenant_id,
            user_id=f"service:{service.id}",
            subject=service.client_id,
            roles=("service",),
            permissions=frozenset(service.permissions or []),
            auth_type="service",
            service_principal_id=service.id,
            issuer="xingliu-internal",
        )
        await self._audit(
            session,
            principal=principal,
            outcome="authenticated",
            request=request,
            claims={"client_id": client_id},
        )
        await session.commit()
        return principal

    async def _audit(
        self,
        session: AsyncSession,
        *,
        principal: Principal,
        outcome: str,
        request: Request,
        claims: dict[str, Any],
        detail: str | None = None,
    ) -> None:
        digest_payload = json.dumps(claims, sort_keys=True, default=str, separators=(",", ":"))
        session.add(
            AuthenticationAuditEvent(
                tenant_id=(
                    principal.tenant_id
                    if outcome == "authenticated"
                    or principal.auth_type == "development"
                    else None
                ),
                user_id=(
                    principal.user_id
                    if principal.auth_type == "development"
                    or (principal.auth_type == "oidc" and outcome == "authenticated")
                    else None
                ),
                service_principal_id=principal.service_principal_id,
                issuer=principal.issuer,
                subject=principal.subject,
                auth_type=principal.auth_type,
                outcome=outcome,
                request_id=getattr(request.state, "request_id", None),
                claim_digest=hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
                detail=detail,
                metadata_payload={"path": request.url.path},
            )
        )


async def _active_membership(
    session: AsyncSession, tenant_id: str, user_id: str
) -> Membership | None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        return None
    return await session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user_id,
            Membership.status == "active",
        )
    )


def service_secret_digest(secret: str, pepper: str) -> str:
    return hashlib.sha256(f"{pepper}:{secret}".encode("utf-8")).hexdigest()
