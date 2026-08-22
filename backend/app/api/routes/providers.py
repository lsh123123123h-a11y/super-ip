from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.providers import (
    ProviderRoutePreviewRequest,
    ProviderRoutePreviewResponse,
)
from app.core.principal import Principal
from app.services.authorization_service import require_permission
from app.services.provider_registry import ProviderRoutingError, get_provider_registry

router = APIRouter(prefix="/providers", tags=["providers"])
registry = get_provider_registry()


@router.get("")
async def list_providers(
    probe: bool = True,
    capability: str = "avatar.render",
    principal: Principal = Depends(require_permission("provider.read")),
) -> dict[str, object]:
    providers = await registry.catalog(probe=probe, capability=capability)
    priority, policy_version = registry.routing_policy(capability)
    try:
        availability = (
            {item["provider_id"]: item["status"] == "ready" for item in providers}
            if probe
            else None
        )
        preview = asdict(
            registry.decide(capability=capability, availability=availability)
        )
    except ProviderRoutingError as exc:
        preview = {"error": str(exc)}
    return {
        "capability": capability,
        "policy_version": policy_version,
        "priority": priority,
        "default_route": preview,
        "providers": providers,
    }


@router.post("/route-preview", response_model=ProviderRoutePreviewResponse)
async def preview_provider_route(
    payload: ProviderRoutePreviewRequest,
    principal: Principal = Depends(require_permission("provider.read")),
) -> ProviderRoutePreviewResponse:
    try:
        decision = await registry.decide_live(
            capability=payload.capability,
            requested_provider=payload.provider,
            requested_execution=payload.execution_mode,
        )
    except ProviderRoutingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProviderRoutePreviewResponse.model_validate(asdict(decision))
