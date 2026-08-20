from fastapi import APIRouter

from app.core.config import get_settings
from app.providers.duix import DuixProvider

router = APIRouter(prefix="/providers", tags=["providers"])
settings = get_settings()


@router.get("")
async def list_providers() -> dict[str, list[dict[str, object]]]:
    provider = DuixProvider(settings)
    try:
        probe = await provider.probe()
        status = "available"
    except Exception as exc:
        probe = {"reachable": False, "message": str(exc)}
        status = "unavailable"

    return {
        "providers": [
            {
                "id": "duix",
                "category": "digital_human.offline_render",
                "status": status,
                "capabilities": ["audio_driven_video", "offline_render", "progress_polling"],
                "probe": probe,
            }
        ]
    }
