from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.schemas.providers import AvatarRoutePreviewRequest, AvatarRoutePreviewResponse
from app.services.provider_registry import ProviderRoutingError, get_provider_registry

router = APIRouter(prefix="/providers", tags=["providers"])
registry = get_provider_registry()


@router.get("")
async def list_providers(probe: bool = True) -> dict[str, object]:
    providers = await registry.catalog(probe=probe)
    try:
        availability = (
            {item["provider_id"]: item["status"] == "ready" for item in providers}
            if probe
            else None
        )
        preview = asdict(registry.decide(availability=availability))
    except ProviderRoutingError as exc:
        preview = {"error": str(exc)}
    return {
        "capability": "avatar.render",
        "policy_version": registry.settings.avatar_route_policy_version,
        "priority": registry.settings.avatar_provider_priority,
        "default_route": preview,
        "providers": providers,
    }


@router.post("/route-preview", response_model=AvatarRoutePreviewResponse)
async def preview_avatar_route(payload: AvatarRoutePreviewRequest) -> AvatarRoutePreviewResponse:
    try:
        decision = await registry.decide_live(
            requested_provider=payload.provider,
            requested_execution=payload.execution_mode,
        )
    except ProviderRoutingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AvatarRoutePreviewResponse.model_validate(asdict(decision))
