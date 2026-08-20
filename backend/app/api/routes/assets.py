import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.schemas.workflows import AssetUploadResponse

router = APIRouter(prefix="/assets", tags=["assets"])
settings = get_settings()
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".wav", ".mp3", ".m4a", ".aac"}


@router.post("/upload", response_model=AssetUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_asset(request: Request, file: UploadFile = File(...)) -> AssetUploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="仅支持常见视频和音频文件")

    asset_id = str(uuid.uuid4())
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(file.filename or "asset").stem).strip("-") or "asset"
    stored_name = f"{asset_id}_{safe_stem}{suffix}"
    upload_dir = settings.duix_shared_data_root.resolve() / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / stored_name

    size = 0
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                output.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="文件超过上传限制")
            output.write(chunk)

    provider_path = f"{settings.duix_container_data_root.rstrip('/')}/uploads/{stored_name}"
    return AssetUploadResponse(
        asset_id=asset_id,
        file_name=file.filename or stored_name,
        provider_path=provider_path,
        download_url=str(request.url_for("download_asset", stored_name=stored_name)),
        content_type=file.content_type,
    )


@router.get("/file/{stored_name}", name="download_asset")
async def download_asset(stored_name: str) -> FileResponse:
    if Path(stored_name).name != stored_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    target = settings.duix_shared_data_root.resolve() / "uploads" / stored_name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target)


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
