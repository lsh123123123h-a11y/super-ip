from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_system_session
from app.core.observability import metrics_payload
from app.services.operations_service import dependency_health


router = APIRouter(tags=["system"])


@router.get("/health")
@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready")
async def ready(
    response: Response,
    session: AsyncSession = Depends(get_system_session),
) -> dict[str, object]:
    components = await dependency_health(session)
    ready_state = all(item.get("status") == "ready" for item in components.values())
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready_state else "unavailable", "components": components}


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=metrics_payload(), media_type="text/plain; version=0.0.4")
