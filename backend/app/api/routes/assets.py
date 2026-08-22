import hashlib
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.core.principal import Principal, get_principal
from app.models.assets import Asset
from app.models.agent import Project
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.schemas.workflows import AssetRead, AssetUploadResponse
from app.services.identity_service import ensure_principal_records
from app.services.storage_service import AssetLocator, LocalAssetStorage

router = APIRouter(prefix="/assets", tags=["assets"])
settings = get_settings()
ALLOWED_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".wav", ".mp3", ".m4a", ".aac",
    ".png", ".jpg", ".jpeg", ".webp",
}


@router.post("/upload", response_model=AssetUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    project_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> AssetUploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="仅支持常见视频和音频文件")

    asset_id = str(uuid.uuid4())
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(file.filename or "asset").stem).strip("-") or "asset"
    stored_name = f"{asset_id}_{safe_stem}{suffix}"
    await ensure_principal_records(session, principal)
    if project_id:
        project = await session.scalar(
            select(Project).where(Project.id == project_id, Project.tenant_id == principal.tenant_id)
        )
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在")
    storage = LocalAssetStorage(settings)
    storage_key = f"tenant/{principal.tenant_id}/assets/{stored_name}"
    upload_dir = storage.resolve_path(f"tenant/{principal.tenant_id}/assets")
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / stored_name

    size = 0
    digest = hashlib.sha256()
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                output.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="文件超过上传限制")
            digest.update(chunk)
            output.write(chunk)

    locator = AssetLocator(backend="local", key=storage_key).as_uri()
    asset = Asset(
        id=asset_id,
        tenant_id=principal.tenant_id,
        project_id=project_id,
        created_by_user_id=principal.user_id,
        file_name=file.filename or stored_name,
        media_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        storage_key=storage_key,
        storage_backend="local",
        locator_payload={},
        provider_path=None,
        checksum=digest.hexdigest(),
        metadata_payload={"original_suffix": suffix},
    )
    session.add(asset)
    try:
        await session.commit()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return AssetUploadResponse(
        asset_id=asset_id,
        file_name=file.filename or stored_name,
        provider_path=locator,
        download_url=str(request.url_for("download_asset", asset_id=asset_id)),
        content_type=file.content_type,
    )


@router.get("/{asset_id}/download", name="download_asset")
async def download_asset(
    asset_id: str,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> FileResponse:
    asset = await session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.tenant_id == principal.tenant_id)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    storage = LocalAssetStorage(settings)
    try:
        target = storage.resolve_path(asset.storage_key)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, filename=asset.file_name, media_type=asset.media_type)


@router.get("", response_model=list[AssetRead])
async def list_assets(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
    project_id: str | None = None,
) -> list[AssetRead]:
    query = select(Asset).where(Asset.tenant_id == principal.tenant_id)
    if project_id:
        query = query.where(Asset.project_id == project_id)
    result = await session.execute(query.order_by(Asset.created_at.desc()).limit(100))
    return [AssetRead.model_validate(item) for item in result.scalars()]


@router.get("/provider-file/{asset_path:path}", name="download_provider_asset")
async def download_provider_asset(
    asset_path: str,
    session: AsyncSession = Depends(get_session),
    owner_id: str = Header(default="local-user", alias="X-Owner-Id"),
) -> FileResponse:
    result = await session.execute(
        select(WorkflowRun.output_payload).where(
            WorkflowRun.owner_id == owner_id,
            WorkflowRun.status == WorkflowStatus.succeeded,
        )
    )
    authorized = any(
        payload and payload.get("artifact_path") == asset_path
        for payload in result.scalars()
    )
    if not authorized:
        raise HTTPException(status_code=404, detail="成片文件不存在")

    root = settings.duix_shared_data_root.resolve()
    target = (root / asset_path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="成片文件不存在")
    return FileResponse(target, filename=target.name)
