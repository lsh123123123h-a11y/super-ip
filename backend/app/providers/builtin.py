from app.core.config import Settings
from app.providers.duix import DuixProvider
from app.providers.opentalking import OpenTalkingProvider


def register_builtin_providers(registry, settings: Settings) -> None:
    registry.register(DuixProvider(settings))
    registry.register(OpenTalkingProvider(settings))
    registry.register_policy(
        capability="avatar.render",
        priority=settings.avatar_provider_priority,
        version=settings.avatar_route_policy_version,
    )
