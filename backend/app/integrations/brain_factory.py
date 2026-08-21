from app.agent.brain import BrainPort
from app.core.config import Settings, get_settings
from app.integrations.new_api_brain import NewApiBrainAdapter


def create_configured_brain(settings: Settings | None = None) -> BrainPort | None:
    """Build the product Brain adapter only when the model gateway is ready."""

    resolved = settings or get_settings()
    if not resolved.model_gateway_configured:
        return None
    return NewApiBrainAdapter(
        base_url=resolved.model_gateway_base_url,
        api_key=resolved.model_gateway_api_key,
        default_model=resolved.model_gateway_default_model,
        timeout_seconds=resolved.model_gateway_timeout_seconds,
    )
