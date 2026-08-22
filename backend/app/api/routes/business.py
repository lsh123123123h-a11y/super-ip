from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.principal import Principal
from app.models.business import Campaign, ContentProject, IPProfile
from app.schemas.business import (
    CampaignPatch,
    CampaignRead,
    CampaignWrite,
    ContentProjectPatch,
    ContentProjectRead,
    ContentProjectWrite,
    IPProfilePatch,
    IPProfileRead,
    IPProfileWrite,
)
from app.services.authorization_service import require_permission

router = APIRouter(prefix="/business", tags=["business"])


async def owned_or_404(session: AsyncSession, model: type, item_id: str, principal: Principal):
    result = await session.execute(
        select(model).where(
            model.id == item_id,
            model.tenant_id == principal.tenant_id,
            model.owner_id == principal.user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="业务对象不存在")
    return item


@router.get("/ip-profiles", response_model=list[IPProfileRead])
async def list_ip_profiles(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.read")),
) -> list[IPProfileRead]:
    result = await session.execute(
        select(IPProfile).where(
            IPProfile.tenant_id == principal.tenant_id,
            IPProfile.owner_id == principal.user_id,
        ).order_by(IPProfile.is_primary.desc(), IPProfile.updated_at.desc())
    )
    return [IPProfileRead.model_validate(item) for item in result.scalars()]


@router.post("/ip-profiles", response_model=IPProfileRead, status_code=status.HTTP_201_CREATED)
async def create_ip_profile(
    payload: IPProfileWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.write")),
) -> IPProfileRead:
    if payload.is_primary:
        await session.execute(
            update(IPProfile).where(
                IPProfile.tenant_id == principal.tenant_id,
                IPProfile.owner_id == principal.user_id,
            ).values(is_primary=False)
        )
    item = IPProfile(
        tenant_id=principal.tenant_id,
        owner_id=principal.user_id,
        **payload.model_dump(),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return IPProfileRead.model_validate(item)


@router.patch("/ip-profiles/{profile_id}", response_model=IPProfileRead)
async def patch_ip_profile(
    profile_id: str,
    payload: IPProfilePatch,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.write")),
) -> IPProfileRead:
    item: IPProfile = await owned_or_404(session, IPProfile, profile_id, principal)
    values = payload.model_dump(exclude_unset=True)
    if values.get("is_primary"):
        await session.execute(
            update(IPProfile).where(
                IPProfile.tenant_id == principal.tenant_id,
                IPProfile.owner_id == principal.user_id,
                IPProfile.id != profile_id,
            ).values(is_primary=False)
        )
    for key, value in values.items():
        setattr(item, key, value)
    item.version += 1
    await session.commit()
    await session.refresh(item)
    return IPProfileRead.model_validate(item)


@router.get("/campaigns", response_model=list[CampaignRead])
async def list_campaigns(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.read")),
) -> list[CampaignRead]:
    result = await session.execute(
        select(Campaign).where(
            Campaign.tenant_id == principal.tenant_id,
            Campaign.owner_id == principal.user_id,
        ).order_by(Campaign.updated_at.desc())
    )
    return [CampaignRead.model_validate(item) for item in result.scalars()]


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.write")),
) -> CampaignRead:
    item = Campaign(
        tenant_id=principal.tenant_id,
        owner_id=principal.user_id,
        **payload.model_dump(),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return CampaignRead.model_validate(item)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignRead)
async def patch_campaign(
    campaign_id: str,
    payload: CampaignPatch,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.write")),
) -> CampaignRead:
    item: Campaign = await owned_or_404(session, Campaign, campaign_id, principal)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return CampaignRead.model_validate(item)


@router.get("/content-projects", response_model=list[ContentProjectRead])
async def list_content_projects(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.read")),
) -> list[ContentProjectRead]:
    result = await session.execute(
        select(ContentProject).where(
            ContentProject.tenant_id == principal.tenant_id,
            ContentProject.owner_id == principal.user_id,
        ).order_by(ContentProject.updated_at.desc())
    )
    return [ContentProjectRead.model_validate(item) for item in result.scalars()]


async def validate_project_references(
    session: AsyncSession,
    principal: Principal,
    campaign_id: str | None,
    ip_profile_id: str | None,
) -> None:
    if campaign_id:
        await owned_or_404(session, Campaign, campaign_id, principal)
    if ip_profile_id:
        await owned_or_404(session, IPProfile, ip_profile_id, principal)


@router.post("/content-projects", response_model=ContentProjectRead, status_code=status.HTTP_201_CREATED)
async def create_content_project(
    payload: ContentProjectWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.write")),
) -> ContentProjectRead:
    await validate_project_references(
        session, principal, payload.campaign_id, payload.ip_profile_id
    )
    item = ContentProject(
        tenant_id=principal.tenant_id,
        owner_id=principal.user_id,
        **payload.model_dump(),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return ContentProjectRead.model_validate(item)


@router.patch("/content-projects/{project_id}", response_model=ContentProjectRead)
async def patch_content_project(
    project_id: str,
    payload: ContentProjectPatch,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("project.write")),
) -> ContentProjectRead:
    item: ContentProject = await owned_or_404(
        session, ContentProject, project_id, principal
    )
    values = payload.model_dump(exclude_unset=True)
    await validate_project_references(
        session,
        principal,
        values.get("campaign_id", item.campaign_id),
        values.get("ip_profile_id", item.ip_profile_id),
    )
    for key, value in values.items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return ContentProjectRead.model_validate(item)
