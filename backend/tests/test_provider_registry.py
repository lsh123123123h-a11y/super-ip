import pytest

from app.core.config import Settings
from app.providers.base import (
    ProviderDescriptor,
    ProviderExecutionRequest,
    ProviderJobState,
    ProviderStatus,
    ProviderSubmission,
)
from app.services.provider_registry import ProviderRegistry, ProviderRoutingError


class ImageProvider:
    provider_id = "image-local"
    timeout_seconds = 30.0

    def descriptor(self):
        return ProviderDescriptor(
            provider_id=self.provider_id,
            adapter_version="1.0.0",
            label="Image Local",
            category="image",
            capabilities=["image.generate"],
            execution_modes=["local"],
            ready=True,
            integration_state="production",
        )

    async def submit(
        self,
        *,
        external_job_id: str,
        request: ProviderExecutionRequest,
    ):
        return ProviderSubmission(external_job_id=external_job_id, raw={})

    async def query(self, external_job_id: str, *, capability: str):
        return ProviderStatus(ProviderJobState.succeeded, 100, "image.png", None, {})

    async def probe(self):
        return {"reachable": True}


class ImageProviderV2(ImageProvider):
    def descriptor(self):
        descriptor = super().descriptor()
        descriptor.adapter_version = "2.0.0"
        return descriptor


def test_auto_route_keeps_duix_as_first_ready_provider() -> None:
    registry = ProviderRegistry(
        Settings(
            duix_mock=True,
            avatar_provider_order="duix,opentalking",
            opentalking_base_url="http://opentalking.local",
            opentalking_render_enabled=True,
        )
    )

    decision = registry.decide(capability="avatar.render")

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

    decision = registry.decide(
        capability="avatar.render",
        requested_provider="opentalking",
        requested_execution="self_hosted",
    )

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
        registry.decide(
            capability="avatar.render",
            requested_provider="opentalking",
        )


def test_execution_mode_filters_auto_route() -> None:
    registry = ProviderRegistry(
        Settings(
            avatar_provider_order="duix,opentalking",
            opentalking_base_url="http://opentalking.local",
            opentalking_render_enabled=True,
        )
    )

    decision = registry.decide(
        capability="avatar.render",
        requested_execution="cloud_api",
    )

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

    decision = registry.decide(
        capability="avatar.render",
        availability={"duix": False, "opentalking": True},
    )

    assert decision.selected_provider == "opentalking"
    assert decision.candidates[0]["reason"] == "健康检查未通过"


def test_registry_routes_a_new_capability_without_avatar_specific_branch() -> None:
    registry = ProviderRegistry(Settings(), install_builtins=False)
    registry.register(ImageProvider())

    decision = registry.decide(
        capability="image.generate",
        requested_execution="local",
    )

    assert decision.capability == "image.generate"
    assert decision.selected_provider == "image-local"
    assert decision.policy_version == "image.generate-route-v1"


@pytest.mark.asyncio
async def test_provider_catalog_uses_generic_ready_and_keeps_avatar_alias() -> None:
    registry = ProviderRegistry(Settings(), install_builtins=False)
    registry.register(ImageProvider())

    catalog = await registry.catalog(probe=False, capability="image.generate")

    assert catalog[0]["ready"] is True
    assert catalog[0]["render_ready"] is True


def test_provider_registry_pins_adapter_versions() -> None:
    registry = ProviderRegistry(Settings(), install_builtins=False)
    registry.register(ImageProvider())
    registry.register(ImageProviderV2())

    assert registry.get_provider("image-local").descriptor().adapter_version == "2.0.0"
    assert (
        registry.get_provider("image-local", adapter_version="1.0.0")
        .descriptor()
        .adapter_version
        == "1.0.0"
    )
