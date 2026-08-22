from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

from app.core.config import Settings, get_settings
from app.models.assets import Asset


class StorageLocatorError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AssetLocator:
    backend: str
    key: str

    def as_uri(self) -> str:
        return f"asset://{self.backend}/{quote(self.key, safe='/')}"


class LocalAssetStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = (
            self.settings.asset_storage_root or self.settings.duix_shared_data_root
        ).resolve()

    def resolve_path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root):
            raise StorageLocatorError("素材定位符越出存储根目录")
        return target

    def locator_for(self, asset: Asset) -> AssetLocator:
        if asset.storage_backend != "local":
            raise StorageLocatorError(f"尚未安装存储后端：{asset.storage_backend}")
        return AssetLocator(backend=asset.storage_backend, key=asset.storage_key)


def parse_asset_locator(value: str) -> AssetLocator | None:
    if not value.startswith("asset://"):
        return None
    remainder = value[len("asset://") :]
    backend, separator, encoded_key = remainder.partition("/")
    if not separator or not backend or not encoded_key:
        raise StorageLocatorError("素材定位符格式无效")
    return AssetLocator(backend=backend, key=unquote(encoded_key))


class ProviderAssetStager:
    """Translate stable storage locators at the provider boundary."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.local = LocalAssetStorage(self.settings)

    def stage(self, provider_id: str, value: str) -> str:
        locator = parse_asset_locator(value)
        if locator is None:
            return value  # external URL or an explicitly supplied provider input
        if locator.backend != "local":
            raise StorageLocatorError(f"Provider staging 不支持：{locator.backend}")
        local_path = self.local.resolve_path(locator.key)
        if not local_path.is_file():
            raise StorageLocatorError("素材文件不存在")
        if provider_id == "duix":
            return f"{self.settings.duix_container_data_root.rstrip('/')}/{locator.key}"
        if provider_id == "opentalking":
            return str(local_path)
        raise StorageLocatorError(f"未安装 Provider 素材 staging 适配器：{provider_id}")


def asset_runtime_locator(asset: Asset) -> str:
    return LocalAssetStorage().locator_for(asset).as_uri()
