from dataclasses import dataclass, field

from fastapi import HTTPException, Request


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: str
    user_id: str
    subject: str = ""
    roles: tuple[str, ...] = ()
    permissions: frozenset[str] = field(default_factory=frozenset)
    auth_type: str = "development"
    service_principal_id: str | None = None
    issuer: str | None = None


async def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401, detail="缺少已验证的身份上下文")
    return principal
