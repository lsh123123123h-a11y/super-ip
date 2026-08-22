import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.principal import Principal, get_principal
from app.models.agent import ArtifactVersion
from app.schemas.agent import (
    ArtifactReviewRequest,
    ArtifactVersionRead,
    ProductionOrderCreate,
    ProductionOrderInputsUpdate,
    ProductionOrderOverview,
    ProductionOrderRead,
    ProjectCreate,
    ProjectRead,
    ResolveDecisionRequest,
)
from app.services.agent_service import (
    command_production_order,
    create_production_order,
    create_project,
    get_production_order_overview,
    list_artifact_versions,
    list_production_orders,
    list_projects,
    resolve_decision,
    review_artifact_version,
    update_production_order_inputs,
)
from app.services.authorization_service import require_permission
from app.services.storage_service import (
    AssetLocator,
    LocalStorageBackend,
    StorageObjectNotFound,
    StorageService,
    StorageUnavailableError,
)


router = APIRouter(tags=["agent"])


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def post_project(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.write")),
) -> ProjectRead:
    project = await create_project(
        session,
        principal=principal,
        name=payload.name,
        goal=payload.goal,
        settings_payload=payload.settings_payload,
    )
    return ProjectRead.model_validate(project)


@router.get("/projects", response_model=list[ProjectRead])
async def get_projects(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.read")),
) -> list[ProjectRead]:
    return [ProjectRead.model_validate(item) for item in await list_projects(session, principal)]


@router.post(
    "/production-orders",
    response_model=ProductionOrderOverview,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_production_order(
    payload: ProductionOrderCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.write")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> ProductionOrderOverview:
    try:
        overview, created = await create_production_order(
            session,
            principal=principal,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="项目、内容或 IP 对象不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return overview


@router.get("/production-orders", response_model=list[ProductionOrderRead])
async def get_production_orders(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.read")),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ProductionOrderRead]:
    return [
        ProductionOrderRead.model_validate(item)
        for item in await list_production_orders(session, principal, limit)
    ]


@router.get("/production-orders/{order_id}", response_model=ProductionOrderOverview)
async def get_production_order_by_id(
    order_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.read")),
) -> ProductionOrderOverview:
    try:
        return await get_production_order_overview(session, principal, order_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="生产单不存在") from exc


@router.post("/production-orders/{order_id}/{command}", response_model=ProductionOrderOverview)
async def post_production_order_command(
    order_id: str,
    command: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.control")),
) -> ProductionOrderOverview:
    if command not in {"pause", "resume", "cancel"}:
        raise HTTPException(status_code=404, detail="生产单命令不存在")
    try:
        return await command_production_order(
            session,
            principal=principal,
            order_id=order_id,
            command=command,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="生产单不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/production-orders/{order_id}/inputs", response_model=ProductionOrderOverview)
async def patch_production_order_inputs(
    order_id: str,
    payload: ProductionOrderInputsUpdate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.write")),
) -> ProductionOrderOverview:
    try:
        return await update_production_order_inputs(
            session,
            principal=principal,
            order_id=order_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="生产单或素材不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/decisions/{decision_id}/resolve", response_model=ProductionOrderOverview)
async def post_decision_resolution(
    decision_id: str,
    payload: ResolveDecisionRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.control")),
) -> ProductionOrderOverview:
    try:
        return await resolve_decision(
            session,
            principal=principal,
            decision_id=decision_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="决策请求不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/artifacts/{artifact_id}/versions", response_model=list[ArtifactVersionRead])
async def get_artifact_versions(
    artifact_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.read")),
) -> list[ArtifactVersionRead]:
    try:
        versions = await list_artifact_versions(
            session,
            principal=principal,
            artifact_id=artifact_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="产物不存在") from exc
    return [ArtifactVersionRead.model_validate(item) for item in versions]


@router.post("/artifact-versions/{version_id}/{action}", response_model=ArtifactVersionRead)
async def post_artifact_review(
    version_id: str,
    action: str,
    payload: ArtifactReviewRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.control")),
) -> ArtifactVersionRead:
    if action not in {"approve", "return"}:
        raise HTTPException(status_code=404, detail="产物审核动作不存在")
    try:
        version = await review_artifact_version(
            session,
            principal=principal,
            version_id=version_id,
            action=action,
            note=payload.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="产物版本不存在") from exc
    return ArtifactVersionRead.model_validate(version)


@router.get("/artifact-versions/{version_id}/download")
async def download_artifact_version(
    version_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("production_order.read")),
) -> Response:
    version = await session.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.id == version_id,
            ArtifactVersion.tenant_id == principal.tenant_id,
        )
    )
    if version is None or not version.storage_backend or not version.storage_key:
        raise HTTPException(status_code=404, detail="产物文件不存在")
    storage = StorageService()
    locator = AssetLocator(version.storage_backend, version.storage_key)
    try:
        url = storage.download_url(locator)
        if url:
            return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        backend = storage.registry.get(locator.backend)
        if isinstance(backend, LocalStorageBackend):
            target = backend.resolve_path(locator.key)
            if not target.is_file():
                raise StorageObjectNotFound(locator.key)
            return FileResponse(target, media_type=version.media_type)
        return Response(content=await storage.get_bytes(locator), media_type=version.media_type)
    except StorageObjectNotFound as exc:
        raise HTTPException(status_code=404, detail="产物文件不存在") from exc
    except StorageUnavailableError as exc:
        raise HTTPException(status_code=503, detail="对象存储暂不可用") from exc
