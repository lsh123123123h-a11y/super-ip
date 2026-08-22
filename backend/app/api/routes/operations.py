from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.observability import DEAD_LETTERS, OUTBOX_BACKLOG
from app.core.principal import Principal
from app.services.authorization_service import require_permission
from app.services.operations_service import platform_snapshot


router = APIRouter(prefix="/admin/operations", tags=["admin-operations"])


@router.get("/platform")
async def get_platform_snapshot(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("tenant.manage_settings")),
) -> dict[str, object]:
    snapshot = await platform_snapshot(session)
    outbox = snapshot["outbox"]
    OUTBOX_BACKLOG.set(outbox["backlog"])
    DEAD_LETTERS.set(outbox["dead_letters"] + outbox["consumer_dead_letters"])
    return snapshot
