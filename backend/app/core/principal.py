from dataclasses import dataclass
import re

from fastapi import Header, HTTPException


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: str
    user_id: str


async def get_principal(
    tenant_id: str = Header(default="local-tenant", alias="X-Tenant-Id", max_length=36),
    user_id: str | None = Header(default=None, alias="X-User-Id", max_length=36),
    legacy_owner_id: str = Header(default="local-user", alias="X-Owner-Id", max_length=36),
) -> Principal:
    resolved_user_id = user_id or legacy_owner_id
    if not tenant_id.strip() or not resolved_user_id.strip():
        raise HTTPException(status_code=401, detail="缺少租户或用户身份上下文")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", tenant_id) or not re.fullmatch(
        r"[A-Za-z0-9_.@-]+", resolved_user_id
    ):
        raise HTTPException(status_code=400, detail="身份上下文格式无效")
    return Principal(tenant_id=tenant_id.strip(), user_id=resolved_user_id.strip())
