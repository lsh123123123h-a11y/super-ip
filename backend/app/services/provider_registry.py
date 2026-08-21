from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from app.core.config import Settings, get_settings
from app.core.extensions import load_registrar_modules
from app.providers.base import CapabilityProvider, ProviderDescriptor


class ProviderRoutingError(ValueError):
    pass


@dataclass(slots=True)
class ProviderRouteDecision:
    capability: str
    requested_provider: str
    requested_execution: str
    selected_provider: str
    selected_execution: str
    policy_version: str
    reason: str
    candidates: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ProviderRoutingPolicy:
    capability: str
    priority: tuple[str, ...]
    version: str


class ProviderRegistry:
    def __init__(self, settings: Settings, *, install_builtins: bool = True) -> None:
        self.settings = settings
        self._providers: dict[str, CapabilityProvider] = {}
        self._policies: dict[str, ProviderRoutingPolicy] = {}
        if install_builtins:
            from app.providers.builtin import register_builtin_providers

            register_builtin_providers(self, settings)

    def register(self, provider: CapabilityProvider) -> None:
        if provider.provider_id in self._providers:
            raise ValueError(f"Provider 重复注册：{provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def register_policy(
        self,
        *,
        capability: str,
        priority: list[str] | tuple[str, ...],
        version: str,
    ) -> None:
        if capability in self._policies:
            raise ValueError(f"Provider 路由策略重复注册：{capability}")
        self._policies[capability] = ProviderRoutingPolicy(
            capability=capability,
            priority=tuple(priority),
            version=version,
        )

    def descriptors(self, capability: str | None = None) -> list[ProviderDescriptor]:
        descriptors = [provider.descriptor() for provider in self._providers.values()]
        if capability is None:
            return descriptors
        return [item for item in descriptors if capability in item.capabilities]

    def get_provider(
        self,
        provider_id: str,
        *,
        capability: str | None = None,
    ) -> CapabilityProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderRoutingError(f"未知 Provider：{provider_id}")
        descriptor = provider.descriptor()
        if capability is not None and capability not in descriptor.capabilities:
            raise ProviderRoutingError(f"{provider_id} 不支持能力 {capability}")
        if not descriptor.render_ready:
            raise ProviderRoutingError(descriptor.reason or f"{provider_id} 尚未就绪")
        return provider

    def routing_policy(self, capability: str) -> tuple[list[str], str]:
        configured = self._policies.get(capability)
        if configured is not None:
            return list(configured.priority), configured.version
        providers = sorted(
            item.provider_id for item in self.descriptors(capability)
        )
        return providers, f"{capability}-route-v1"

    def decide(
        self,
        *,
        capability: str,
        requested_provider: str = "auto",
        requested_execution: str = "auto",
        availability: dict[str, bool] | None = None,
    ) -> ProviderRouteDecision:
        descriptors = {
            item.provider_id: item for item in self.descriptors(capability)
        }
        priority, policy_version = self.routing_policy(capability)
        candidates: list[dict[str, Any]] = []
        for provider_id in priority:
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
                raise ProviderRoutingError(
                    f"未知或不支持 {capability} 的 Provider：{requested_provider}"
                )
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
                raise ProviderRoutingError(f"能力 {capability} 没有可用 Provider")
            reason = "按策略优先级选择首个就绪引擎"

        selected_execution = (
            requested_execution
            if requested_execution != "auto"
            else selected.execution_modes[0]
        )
        return ProviderRouteDecision(
            capability=capability,
            requested_provider=requested_provider,
            requested_execution=requested_execution,
            selected_provider=selected.provider_id,
            selected_execution=selected_execution,
            policy_version=policy_version,
            reason=reason,
            candidates=candidates,
        )

    async def decide_live(
        self,
        *,
        capability: str,
        requested_provider: str = "auto",
        requested_execution: str = "auto",
    ) -> ProviderRouteDecision:
        catalog = await self.catalog(probe=True, capability=capability)
        availability = {item["provider_id"]: item["status"] == "ready" for item in catalog}
        return self.decide(
            capability=capability,
            requested_provider=requested_provider,
            requested_execution=requested_execution,
            availability=availability,
        )

    async def catalog(
        self,
        *,
        probe: bool = True,
        capability: str | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for provider in self._providers.values():
            descriptor = provider.descriptor()
            if capability is not None and capability not in descriptor.capabilities:
                continue
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
    settings = get_settings()
    registry = ProviderRegistry(settings)
    load_registrar_modules(
        settings.extension_modules("provider"),
        hook_name="register_providers",
        registry=registry,
    )
    return registry


# Kept as a source-compatible name for the first public avatar route API.
AvatarRouteDecision = ProviderRouteDecision
