import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models.orchestration import WorkflowStatus
from app.schemas.workflows import DigitalHumanRenderRequest, WorkflowRead
from app.services.workflow_service import create_workflow, get_workflow, list_workflows, retry_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])
settings = get_settings()


async def enqueue_workflow(workflow_id: str) -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.rpush(settings.workflow_queue, workflow_id)
    finally:
        await redis.aclose()


@router.post("/digital-human", response_model=WorkflowRead, status_code=status.HTTP_202_ACCEPTED)
async def submit_digital_human_workflow(
    payload: DigitalHumanRenderRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    owner_id: str = Header(default="local-user", alias="X-Owner-Id"),
) -> WorkflowRead:
    workflow, created = await create_workflow(
        session,
        owner_id=owner_id,
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        payload=payload,
    )
    if workflow.status in {WorkflowStatus.queued, WorkflowStatus.failed_retryable}:
        try:
            await enqueue_workflow(workflow.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="任务已保存，但队列暂不可用，请稍后重试") from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return WorkflowRead.model_validate(workflow)


@router.get("", response_model=list[WorkflowRead])
async def get_workflows(
    session: AsyncSession = Depends(get_session),
    owner_id: str = Header(default="local-user", alias="X-Owner-Id"),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[WorkflowRead]:
    return [WorkflowRead.model_validate(item) for item in await list_workflows(session, owner_id, limit)]


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow_by_id(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    owner_id: str = Header(default="local-user", alias="X-Owner-Id"),
) -> WorkflowRead:
    try:
        workflow = await get_workflow(session, workflow_id, owner_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return WorkflowRead.model_validate(workflow)


@router.post("/{workflow_id}/retry", response_model=WorkflowRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_workflow_by_id(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    owner_id: str = Header(default="local-user", alias="X-Owner-Id"),
) -> WorkflowRead:
    try:
        workflow = await retry_workflow(session, workflow_id, owner_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        await enqueue_workflow(workflow.id)
    except Exception as exc:
        workflow.status = WorkflowStatus.failed_retryable
        workflow.error_code = "QueueUnavailable"
        workflow.error_message = "任务已保存，但队列暂不可用，请稍后重试"
        await session.commit()
        raise HTTPException(status_code=503, detail=workflow.error_message) from exc
    return WorkflowRead.model_validate(workflow)
