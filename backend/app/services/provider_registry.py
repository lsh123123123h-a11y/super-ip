from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from app.core.config import Settings, get_settings
from app.providers.base import AvatarRenderProvider, ProviderDescriptor
from app.providers.duix import DuixProvider
from app.providers.opentalking import OpenTalkingProvider


class ProviderRoutingError(ValueError):
    pass


@dataclass(slots=True)
class AvatarRouteDecision:
    capability: str
    requested_provider: str
    requested_execution: str
    selected_provider: str
    selected_execution: str
    policy_version: str
    reason: str
    candidates: list[dict[str, Any]]


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[str, AvatarRenderProvider] = {
            "duix": DuixProvider(settings),
            "opentalking": OpenTalkingProvider(settings),
        }

    def descriptors(self) -> list[ProviderDescriptor]:
        return [provider.descriptor() for provider in self._providers.values()]

    def get_provider(self, provider_id: str) -> AvatarRenderProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderRoutingError(f"未知数字人引擎：{provider_id}")
        if not provider.descriptor().render_ready:
            raise ProviderRoutingError(provider.descriptor().reason or f"{provider_id} 尚未就绪")
        return provider

    def decide(
        self,
        *,
        requested_provider: str = "auto",
        requested_execution: str = "auto",
        availability: dict[str, bool] | None = None,
    ) -> AvatarRouteDecision:
        descriptors = {item.provider_id: item for item in self.descriptors()}
        candidates: list[dict[str, Any]] = []
        for provider_id in self.settings.avatar_provider_priority:
            descriptor = descriptors.get(provider_id)
            if descriptor is None:
                candidates.append({"provider": provider_id, "eligible": False, "reason": "未注册"})
                continue
            execution_ok = requested_execution == "auto" or requested_execution in descriptor.execution_modes
            health_ok = availability is None or availability.get(provider_id, False)
            eligible = descriptor.render_ready and execution_ok and health_ok
            reason = descriptor.reason
            if descriptor.render_ready and not execution_ok:
                reason = f"不支持执行方式 {requested_execution}"
            elif descriptor.render_ready and not health_ok:
                reason = "健康检查未通过"
            candidates.append(
                {
                    "provider": provider_id,
                    "eligible": eligible,
                    "execution_modes": descriptor.execution_modes,
                    "integration_state": descriptor.integration_state,
                    "reason": reason,
                }
            )

        if requested_provider != "auto":
            descriptor = descriptors.get(requested_provider)
            if descriptor is None:
                raise ProviderRoutingError(f"未知数字人引擎：{requested_provider}")
            if not descriptor.render_ready:
                raise ProviderRoutingError(descriptor.reason or f"{requested_provider} 尚未就绪")
            if availability is not None and not availability.get(requested_provider, False):
                raise ProviderRoutingError(f"{requested_provider} 健康检查未通过")
            if requested_execution != "auto" and requested_execution not in descriptor.execution_modes:
                raise ProviderRoutingError(f"{requested_provider} 不支持执行方式 {requested_execution}")
            selected = descriptor
            reason = "按用户/管理员显式指定路由"
        else:
            selected = next(
                (
                    descriptors[item["provider"]]
                    for item in candidates
                    if item["eligible"] and item["provider"] in descriptors
                ),
                None,
            )
            if selected is None:
                raise ProviderRoutingError("没有可用的数字人渲染引擎")
            reason = "按策略优先级选择首个就绪引擎"

        selected_execution = (
            requested_execution
            if requested_execution != "auto"
            else selected.execution_modes[0]
        )
        return AvatarRouteDecision(
            capability="avatar.render",
            requested_provider=requested_provider,
            requested_execution=requested_execution,
            selected_provider=selected.provider_id,
            selected_execution=selected_execution,
            policy_version=self.settings.avatar_route_policy_version,
            reason=reason,
            candidates=candidates,
        )

    async def decide_live(
        self,
        *,
        requested_provider: str = "auto",
        requested_execution: str = "auto",
    ) -> AvatarRouteDecision:
        catalog = await self.catalog(probe=True)
        availability = {item["provider_id"]: item["status"] == "ready" for item in catalog}
        return self.decide(
            requested_provider=requested_provider,
            requested_execution=requested_execution,
            availability=availability,
        )

    async def catalog(self, *, probe: bool = True) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for provider in self._providers.values():
            descriptor = provider.descriptor()
            probe_result: dict[str, Any] = {"reachable": None, "mode": "not_probed"}
            status = "ready" if descriptor.render_ready else "setup_required"
            if probe:
                try:
                    probe_result = await provider.probe()
                    if not probe_result.get("reachable"):
                        status = "unavailable" if descriptor.render_ready else "setup_required"
                except Exception as exc:  # noqa: BLE001
                    probe_result = {"reachable": False, "message": str(exc)}
                    status = "unavailable"
            rows.append({**asdict(descriptor), "status": status, "probe": probe_result})
        return rows


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry(get_settings())
