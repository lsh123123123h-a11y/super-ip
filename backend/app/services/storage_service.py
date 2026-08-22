import asyncio
import hashlib
import hmac
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.parse import quote, unquote

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, get_settings
from app.models.assets import Asset


class StorageError(RuntimeError):
    pass


class StorageUnavailableError(StorageError):
    pass


class StorageObjectNotFound(StorageError):
    pass


class StorageLocatorError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AssetLocator:
    backend: str
    key: str

    def as_uri(self) -> str:
        return f"asset://{self.backend}/{quote(self.key, safe='/')}"


@dataclass(frozen=True, slots=True)
class StorageObject:
    backend: str
    key: str
    size_bytes: int
    media_type: str | None = None
    checksum: str | None = None
    etag: str | None = None

    @property
    def locator(self) -> AssetLocator:
        return AssetLocator(self.backend, self.key)


class StorageBackend(Protocol):
    backend_id: str

    def put_file(self, key: str, source: Path, *, media_type: str | None = None) -> StorageObject: ...
    def open(self, key: str) -> BinaryIO: ...
    def get_bytes(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def stat(self, key: str) -> StorageObject: ...
    def generate_download_url(self, key: str, *, expires_seconds: int) -> str | None: ...
    def generate_upload_url(
        self, key: str, *, expires_seconds: int, media_type: str | None = None
    ) -> str | None: ...
    def copy(self, source_key: str, destination_key: str) -> StorageObject: ...


def _validated_key(key: str) -> str:
    normalized = key.replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise StorageLocatorError("存储 key 格式无效")
    return "/".join(parts)


class LocalStorageBackend:
    backend_id = "local"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = (self.settings.asset_storage_root or Path("./data/assets")).resolve()

    def resolve_path(self, key: str) -> Path:
        target = (self.root / _validated_key(key)).resolve()
        if not target.is_relative_to(self.root):
            raise StorageLocatorError("素材定位符越出存储根目录")
        return target

    def put_file(self, key: str, source: Path, *, media_type: str | None = None) -> StorageObject:
        target = self.resolve_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        result = self.stat(key)
        return StorageObject(
            backend=result.backend,
            key=result.key,
            size_bytes=result.size_bytes,
            media_type=media_type,
            checksum=result.checksum,
            etag=result.etag,
        )

    def open(self, key: str) -> BinaryIO:
        target = self.resolve_path(key)
        if not target.is_file():
            raise StorageObjectNotFound(key)
        return target.open("rb")

    def get_bytes(self, key: str) -> bytes:
        with self.open(key) as source:
            return source.read()

    def delete(self, key: str) -> None:
        self.resolve_path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self.resolve_path(key).is_file()

    def stat(self, key: str) -> StorageObject:
        target = self.resolve_path(key)
        if not target.is_file():
            raise StorageObjectNotFound(key)
        digest = hashlib.sha256()
        with target.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return StorageObject(
            backend=self.backend_id,
            key=_validated_key(key),
            size_bytes=target.stat().st_size,
            checksum=digest.hexdigest(),
        )

    def generate_download_url(self, key: str, *, expires_seconds: int) -> str | None:
        return None

    def generate_upload_url(
        self, key: str, *, expires_seconds: int, media_type: str | None = None
    ) -> str | None:
        return None

    def copy(self, source_key: str, destination_key: str) -> StorageObject:
        source = self.resolve_path(source_key)
        if not source.is_file():
            raise StorageObjectNotFound(source_key)
        return self.put_file(destination_key, source)


LocalAssetStorage = LocalStorageBackend


class S3StorageBackend:
    backend_id = "s3"

    def __init__(self, settings: Settings | None = None, *, client=None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.s3_bucket:
            raise StorageUnavailableError("S3_BUCKET 尚未配置")
        self.bucket = self.settings.s3_bucket
        self.client = client or boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url or None,
            region_name=self.settings.s3_region,
            aws_access_key_id=self.settings.s3_access_key_id or None,
            aws_secret_access_key=self.settings.s3_secret_access_key or None,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if self.settings.s3_force_path_style else "auto"},
            ),
        )

    def put_file(self, key: str, source: Path, *, media_type: str | None = None) -> StorageObject:
        key = _validated_key(key)
        digest = hashlib.sha256()
        with source.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                digest.update(chunk)
        extra = {"Metadata": {"sha256": digest.hexdigest()}}
        if media_type:
            extra["ContentType"] = media_type
        try:
            self.client.upload_file(str(source), self.bucket, key, ExtraArgs=extra)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise StorageUnavailableError("S3 上传失败") from exc
        return self.stat(key)

    def open(self, key: str) -> BinaryIO:
        raise StorageError("S3 对象不提供进程内文件句柄，请使用 get_bytes 或预签名 URL")

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=_validated_key(key))
            return response["Body"].read()
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)
            if status == 404:
                raise StorageObjectNotFound(key) from exc
            raise StorageUnavailableError("S3 下载失败") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError("S3 下载失败") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=_validated_key(key))
        except (BotoCoreError, ClientError) as exc:
            raise StorageUnavailableError("S3 删除失败") from exc

    def exists(self, key: str) -> bool:
        try:
            self.stat(key)
            return True
        except StorageObjectNotFound:
            return False

    def stat(self, key: str) -> StorageObject:
        key = _validated_key(key)
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)
            if status == 404:
                raise StorageObjectNotFound(key) from exc
            raise StorageUnavailableError("S3 stat 失败") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError("S3 stat 失败") from exc
        metadata = response.get("Metadata") or {}
        return StorageObject(
            backend=self.backend_id,
            key=key,
            size_bytes=int(response.get("ContentLength") or 0),
            media_type=response.get("ContentType"),
            checksum=metadata.get("sha256"),
            etag=str(response.get("ETag") or "").strip('"') or None,
        )

    def generate_download_url(self, key: str, *, expires_seconds: int) -> str | None:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": _validated_key(key)},
            ExpiresIn=expires_seconds,
        )

    def generate_upload_url(
        self, key: str, *, expires_seconds: int, media_type: str | None = None
    ) -> str | None:
        params = {"Bucket": self.bucket, "Key": _validated_key(key)}
        if media_type:
            params["ContentType"] = media_type
        return self.client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_seconds
        )

    def copy(self, source_key: str, destination_key: str) -> StorageObject:
        try:
            self.client.copy_object(
                Bucket=self.bucket,
                Key=_validated_key(destination_key),
                CopySource={"Bucket": self.bucket, "Key": _validated_key(source_key)},
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageUnavailableError("S3 copy 失败") from exc
        return self.stat(destination_key)


class StorageRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._backends: dict[str, StorageBackend] = {"local": LocalStorageBackend(self.settings)}

    def register(self, backend: StorageBackend) -> None:
        self._backends[backend.backend_id] = backend

    def get(self, backend_id: str) -> StorageBackend:
        if backend_id == "s3" and backend_id not in self._backends:
            self._backends[backend_id] = S3StorageBackend(self.settings)
        backend = self._backends.get(backend_id)
        if backend is None:
            raise StorageUnavailableError(f"尚未安装存储后端：{backend_id}")
        return backend

    @property
    def active(self) -> StorageBackend:
        return self.get(self.settings.asset_storage_backend)


class StorageService:
    def __init__(self, settings: Settings | None = None, registry: StorageRegistry | None = None) -> None:
        self.settings = settings or get_settings()
        self.registry = registry or StorageRegistry(self.settings)

    async def put_file(
        self, key: str, source: Path, *, media_type: str | None = None
    ) -> StorageObject:
        return await asyncio.to_thread(
            self.registry.active.put_file, key, source, media_type=media_type
        )

    async def get_bytes(self, locator: AssetLocator) -> bytes:
        return await asyncio.to_thread(self.registry.get(locator.backend).get_bytes, locator.key)

    async def stat(self, locator: AssetLocator) -> StorageObject:
        return await asyncio.to_thread(self.registry.get(locator.backend).stat, locator.key)

    async def delete(self, locator: AssetLocator) -> None:
        await asyncio.to_thread(self.registry.get(locator.backend).delete, locator.key)

    def download_url(self, locator: AssetLocator) -> str | None:
        return self.registry.get(locator.backend).generate_download_url(
            locator.key, expires_seconds=self.settings.s3_presign_expiry_seconds
        )

    async def promote(
        self,
        source: AssetLocator,
        destination_key: str,
        *,
        media_type: str | None = None,
    ) -> StorageObject:
        active = self.registry.active
        if source.backend == active.backend_id:
            return await asyncio.to_thread(active.copy, source.key, destination_key)
        data = await self.get_bytes(source)
        staging_root = self.registry.get("local").root  # type: ignore[attr-defined]
        temp = staging_root / ".storage-staging" / hashlib.sha256(
            destination_key.encode("utf-8")
        ).hexdigest()
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(data)
        try:
            return await self.put_file(destination_key, temp, media_type=media_type)
        finally:
            temp.unlink(missing_ok=True)


def parse_asset_locator(value: str) -> AssetLocator | None:
    if not value.startswith("asset://"):
        return None
    remainder = value[len("asset://") :]
    backend, separator, encoded_key = remainder.partition("/")
    if not separator or not backend or not encoded_key:
        raise StorageLocatorError("素材定位符格式无效")
    return AssetLocator(backend=backend, key=_validated_key(unquote(encoded_key)))


class ProviderAssetStager:
    """Translate stable storage locators only at the Provider boundary."""

    def __init__(self, settings: Settings | None = None, registry: StorageRegistry | None = None) -> None:
        self.settings = settings or get_settings()
        self.registry = registry or StorageRegistry(self.settings)
        self.local = self.registry.get("local")

    def stage(self, provider_id: str, value: str, *, checksum: str | None = None) -> str:
        locator = parse_asset_locator(value)
        if locator is None:
            return value
        if locator.backend == "local":
            local_path = self.local.resolve_path(locator.key)  # type: ignore[attr-defined]
        else:
            data = self.registry.get(locator.backend).get_bytes(locator.key)
            digest = hashlib.sha256(data).hexdigest()
            if checksum and not hmac.compare_digest(digest, checksum):
                raise StorageLocatorError("Provider staging checksum 不匹配")
            cache_key = f".provider-staging/{locator.backend}/{digest}/{Path(locator.key).name}"
            local_path = self.local.resolve_path(cache_key)  # type: ignore[attr-defined]
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if not local_path.exists():
                local_path.write_bytes(data)
        if not local_path.is_file():
            raise StorageLocatorError("素材文件不存在")
        if checksum:
            digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
            if not hmac.compare_digest(digest, checksum):
                raise StorageLocatorError("Provider staging checksum 不匹配")
        if provider_id == "duix":
            relative = Path(locator.key)
            provider_target = (self.settings.duix_shared_data_root / relative).resolve()
            provider_root = self.settings.duix_shared_data_root.resolve()
            if not provider_target.is_relative_to(provider_root):
                raise StorageLocatorError("Duix staging 路径无效")
            provider_target.parent.mkdir(parents=True, exist_ok=True)
            if provider_target != local_path and (
                not provider_target.exists()
                or provider_target.stat().st_size != local_path.stat().st_size
            ):
                shutil.copyfile(local_path, provider_target)
            return f"{self.settings.duix_container_data_root.rstrip('/')}/{relative.as_posix()}"
        if provider_id == "opentalking":
            return str(local_path)
        raise StorageLocatorError(f"未安装 Provider 素材 staging 适配器：{provider_id}")

    async def promote_result(
        self,
        provider_id: str,
        value: str,
        destination_key: str,
        *,
        storage: StorageService,
        media_type: str | None = None,
    ) -> StorageObject:
        """Promote a provider-owned result into stable platform storage.

        Provider filesystem paths are interpreted only inside this adapter. The
        workflow and artifact layers receive a backend-neutral locator.
        """

        locator = parse_asset_locator(value)
        if locator is not None:
            return await storage.promote(
                locator, destination_key, media_type=media_type
            )
        candidate = Path(value)
        if provider_id == "duix":
            provider_root = self.settings.duix_shared_data_root.resolve()
            source = (
                candidate.resolve()
                if candidate.is_absolute()
                else (provider_root / candidate).resolve()
            )
            if not source.is_relative_to(provider_root):
                raise StorageLocatorError("Duix result 路径无效")
        elif provider_id == "opentalking":
            source = candidate.resolve()
        else:
            raise StorageLocatorError(
                f"未安装 Provider 结果 promotion 适配器：{provider_id}"
            )
        if not source.is_file():
            raise StorageLocatorError("Provider 结果文件不存在")
        return await storage.put_file(
            destination_key, source, media_type=media_type
        )


def asset_runtime_locator(asset: Asset) -> str:
    return AssetLocator(asset.storage_backend, asset.storage_key).as_uri()
