import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.principal import Principal, get_principal
from app.models.orchestration import WorkflowStatus
from app.schemas.workflows import DigitalHumanRenderRequest, WorkflowRead
from app.services.avatar_workflow_service import create_avatar_workflow
from app.services.workflow_service import get_workflow, list_workflows, retry_workflow
from app.services.provider_registry import ProviderRoutingError
from app.services.identity_service import ensure_principal_records
from app.services.authorization_service import require_permission

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/digital-human", response_model=WorkflowRead, status_code=status.HTTP_202_ACCEPTED)
async def submit_digital_human_workflow(
    payload: DigitalHumanRenderRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("production_order.write")),
) -> WorkflowRead:
    await ensure_principal_records(session, principal)
    try:
        workflow, created = await create_avatar_workflow(
            session,
            owner_id=principal.user_id,
            tenant_id=principal.tenant_id,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            payload=payload,
        )
    except ProviderRoutingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return WorkflowRead.model_validate(workflow)


@router.get("", response_model=list[WorkflowRead])
async def get_workflows(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.read")),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[WorkflowRead]:
    return [
        WorkflowRead.model_validate(item)
        for item in await list_workflows(
            session, principal.user_id, limit, tenant_id=principal.tenant_id
        )
    ]


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow_by_id(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.read")),
) -> WorkflowRead:
    try:
        workflow = await get_workflow(
            session, workflow_id, principal.user_id, principal.tenant_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return WorkflowRead.model_validate(workflow)


@router.post("/{workflow_id}/retry", response_model=WorkflowRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_workflow_by_id(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.control")),
) -> WorkflowRead:
    try:
        workflow = await retry_workflow(
            session, workflow_id, principal.user_id, principal.tenant_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkflowRead.model_validate(workflow)
