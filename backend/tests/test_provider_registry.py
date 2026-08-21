import pytest

from app.core.config import Settings
from app.services.provider_registry import ProviderRegistry, ProviderRoutingError


def test_auto_route_keeps_duix_as_first_ready_provider() -> None:
    registry = ProviderRegistry(
        Settings(
            duix_mock=True,
            avatar_provider_order="duix,opentalking",
            opentalking_base_url="http://opentalking.local",
            opentalking_render_enabled=True,
        )
    )

    decision = registry.decide()

    assert decision.selected_provider == "duix"
    assert decision.selected_execution == "self_hosted"
    assert decision.policy_version == "avatar-route-v1"


def test_explicit_opentalking_route_is_available_when_bridge_is_enabled() -> None:
    registry = ProviderRegistry(
        Settings(
            opentalking_base_url="http://opentalking.local",
            opentalking_render_enabled=True,
        )
    )

    decision = registry.decide(requested_provider="opentalking", requested_execution="self_hosted")

    assert decision.selected_provider == "opentalking"
    assert decision.selected_execution == "self_hosted"


def test_explicit_opentalking_route_fails_honestly_when_only_probe_is_configured() -> None:
    registry = ProviderRegistry(
        Settings(
            opentalking_base_url="http://opentalking.local",
            opentalking_render_enabled=False,
        )
    )

    with pytest.raises(ProviderRoutingError, match="桥接器尚未启用"):
        registry.decide(requested_provider="opentalking")


def test_execution_mode_filters_auto_route() -> None:
    registry = ProviderRegistry(
        Settings(
            avatar_provider_order="duix,opentalking",
            opentalking_base_url="http://opentalking.local",
            opentalking_render_enabled=True,
        )
    )

    decision = registry.decide(requested_execution="cloud_api")

    assert decision.selected_provider == "opentalking"
    assert decision.selected_execution == "cloud_api"


def test_unhealthy_primary_provider_falls_back_without_changing_business_contract() -> None:
    registry = ProviderRegistry(
        Settings(
            avatar_provider_order="duix,opentalking",
            opentalking_base_url="http://opentalking.local",
            opentalking_render_enabled=True,
        )
    )

    decision = registry.decide(availability={"duix": False, "opentalking": True})

    assert decision.selected_provider == "opentalking"
    assert decision.candidates[0]["reason"] == "健康检查未通过"
