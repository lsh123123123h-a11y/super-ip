import hashlib
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.requests import Request

from app.core.auth import AuthenticationError, DevelopmentAuthProvider, OidcJwtAuthProvider
from app.core.config import Settings
from app.core.principal import Principal
from app.core.redaction import redact, safe_error_summary
from app.services.authorization_service import AuthorizationService
from app.services.operations_service import dependency_health
from app.services.storage_service import (
    AssetLocator,
    LocalStorageBackend,
    ProviderAssetStager,
    S3StorageBackend,
    StorageLocatorError,
    StorageObject,
    StorageObjectNotFound,
    StorageRegistry,
    parse_asset_locator,
)


def request_with_headers(headers: dict[str, str] | None = None) -> Request:
    raw = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/v1/projects", "headers": raw})


def oidc_provider() -> tuple[OidcJwtAuthProvider, object, Settings]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(
        _env_file=None,
        auth_mode="oidc",
        oidc_issuer="https://identity.example",
        oidc_audience="xingliu-api",
        oidc_jwks_url="https://identity.example/.well-known/jwks.json",
        oidc_algorithms="RS256",
    )
    provider = OidcJwtAuthProvider(
        settings,
        signing_key_resolver=lambda _: private_key.public_key(),
    )
    return provider, private_key, settings


def signed_token(private_key, settings: Settings, **updates) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": "subject-1",
        "tenant_id": "tenant-1",
        "iat": now,
        "nbf": now - timedelta(seconds=1),
        "exp": now + timedelta(minutes=5),
        **updates,
    }
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})


@pytest.mark.asyncio
async def test_oidc_validates_signature_issuer_audience_expiry_and_nbf() -> None:
    provider, private_key, settings = oidc_provider()
    token = signed_token(private_key, settings)
    principal, _ = await provider.resolve(
        request_with_headers({"Authorization": f"Bearer {token}"})
    )
    assert principal.tenant_id == "tenant-1"
    assert principal.subject == "subject-1"

    cases = (
        ({"exp": datetime.now(UTC) - timedelta(seconds=1)}, "token_expired"),
        ({"iss": "https://wrong.example"}, "wrong_issuer"),
        ({"aud": "wrong-api"}, "wrong_audience"),
        ({"nbf": datetime.now(UTC) + timedelta(minutes=1)}, "token_not_active"),
    )
    for updates, code in cases:
        with pytest.raises(AuthenticationError) as caught:
            await provider.resolve(
                request_with_headers(
                    {"Authorization": f"Bearer {signed_token(private_key, settings, **updates)}"}
                )
            )
        assert caught.value.code == code


@pytest.mark.asyncio
async def test_production_auth_rejects_header_spoof_and_disallowed_algorithm() -> None:
    provider, private_key, settings = oidc_provider()
    token = signed_token(private_key, settings)
    with pytest.raises(AuthenticationError) as caught:
        await provider.resolve(
            request_with_headers(
                {"Authorization": f"Bearer {token}", "X-Tenant-Id": "spoofed"}
            )
        )
    assert caught.value.code == "header_impersonation_forbidden"

    bad = jwt.encode(
        {
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "sub": "subject-1",
            "tenant_id": "tenant-1",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "not-allowed-but-long-enough-for-hs256",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError) as caught:
        await provider.resolve(request_with_headers({"Authorization": f"Bearer {bad}"}))
    assert caught.value.code == "algorithm_not_allowed"


@pytest.mark.asyncio
async def test_development_adapter_is_explicit_and_authorization_is_centralized() -> None:
    principal, _ = await DevelopmentAuthProvider().resolve(
        request_with_headers({"X-Tenant-Id": "dev-tenant", "X-User-Id": "dev-user"})
    )
    assert principal.auth_type == "development"
    viewer = Principal(
        tenant_id="dev-tenant",
        user_id="viewer",
        roles=("viewer",),
        permissions=frozenset({"project.read"}),
    )
    assert AuthorizationService.require(viewer, "project.read") is viewer
    with pytest.raises(HTTPException) as caught:
        AuthorizationService.require(viewer, "billing.manage")
    assert caught.value.status_code == 403
    with pytest.raises(AuthenticationError) as caught:
        await DevelopmentAuthProvider(allow_trusted_headers=False).resolve(
            request_with_headers(
                {"X-Tenant-Id": "spoofed", "X-User-Id": "spoofed"}
            )
        )
    assert caught.value.code == "development_auth_forbidden"
    assert "AUTH_MODE=oidc" in Settings(
        _env_file=None,
        environment="production",
        auth_mode="development",
    ).production_configuration_errors()


def test_local_storage_port_checksum_copy_missing_and_traversal(tmp_path: Path) -> None:
    backend = LocalStorageBackend(Settings(_env_file=None, asset_storage_root=tmp_path))
    source = tmp_path / "source.bin"
    source.write_bytes(b"production-platform")
    stored = backend.put_file("tenant/t1/assets/source.bin", source, media_type="application/octet-stream")
    assert stored.checksum == hashlib.sha256(b"production-platform").hexdigest()
    assert backend.get_bytes(stored.key) == b"production-platform"
    copied = backend.copy(stored.key, "tenant/t1/assets/copy.bin")
    assert copied.checksum == stored.checksum
    backend.delete(copied.key)
    with pytest.raises(StorageObjectNotFound):
        backend.stat(copied.key)
    with pytest.raises(StorageLocatorError):
        backend.resolve_path("../../escape")


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict, str | None]] = {}

    def upload_file(self, source, bucket, key, ExtraArgs):
        self.objects[(bucket, key)] = (
            Path(source).read_bytes(),
            ExtraArgs.get("Metadata", {}),
            ExtraArgs.get("ContentType"),
        )

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )
        body, metadata, content_type = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata, "ContentType": content_type, "ETag": '"etag"'}

    def get_object(self, *, Bucket, Key):
        body, _, _ = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(body)}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def copy_object(self, *, Bucket, Key, CopySource):
        self.objects[(Bucket, Key)] = self.objects[(CopySource["Bucket"], CopySource["Key"])]

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://objects.example/{operation}/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


def test_s3_compatible_port_and_presigned_urls(tmp_path: Path) -> None:
    source = tmp_path / "object.bin"
    source.write_bytes(b"s3-compatible")
    client = FakeS3Client()
    backend = S3StorageBackend(
        Settings(_env_file=None, s3_bucket="assets", s3_force_path_style=True),
        client=client,
    )
    stored = backend.put_file("tenant/t1/object.bin", source, media_type="application/octet-stream")
    assert backend.get_bytes(stored.key) == b"s3-compatible"
    assert stored.checksum == hashlib.sha256(b"s3-compatible").hexdigest()
    assert "get_object" in (backend.generate_download_url(stored.key, expires_seconds=60) or "")
    assert "put_object" in (
        backend.generate_upload_url(stored.key, expires_seconds=60, media_type="application/octet-stream") or ""
    )
    assert backend.copy(stored.key, "tenant/t1/copy.bin").size_bytes == len(b"s3-compatible")


@pytest.mark.skipif(
    not __import__("os").getenv("TEST_S3_ENDPOINT_URL"),
    reason="需要 MinIO/S3-compatible 集成服务",
)
def test_minio_s3_put_get_stat_and_presign(tmp_path: Path) -> None:
    import os

    source = tmp_path / "minio.bin"
    source.write_bytes(b"minio-integration")
    backend = S3StorageBackend(
        Settings(
            _env_file=None,
            s3_endpoint_url=os.environ["TEST_S3_ENDPOINT_URL"],
            s3_region="us-east-1",
            s3_bucket=os.getenv("TEST_S3_BUCKET", "xingliu-assets"),
            s3_access_key_id=os.getenv("TEST_S3_ACCESS_KEY_ID", "xingliu-minio"),
            s3_secret_access_key=os.getenv(
                "TEST_S3_SECRET_ACCESS_KEY", "xingliu-minio-secret"
            ),
            s3_force_path_style=True,
        )
    )
    key = f"integration/{datetime.now(UTC).timestamp()}.bin"
    try:
        stored = backend.put_file(key, source, media_type="application/octet-stream")
        assert stored.size_bytes == len(b"minio-integration")
        assert backend.get_bytes(key) == b"minio-integration"
        assert backend.exists(key)
        assert backend.generate_download_url(key, expires_seconds=60)
    finally:
        backend.delete(key)


class MemoryBackend:
    backend_id = "memory"

    def __init__(self, content: bytes) -> None:
        self.content = content

    def get_bytes(self, key: str) -> bytes:
        return self.content


def test_provider_staging_downloads_and_verifies_checksum(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        asset_storage_root=tmp_path / "assets",
        duix_shared_data_root=tmp_path / "provider",
        duix_container_data_root="/provider/data",
    )
    registry = StorageRegistry(settings)
    registry.register(MemoryBackend(b"remote-asset"))  # type: ignore[arg-type]
    stager = ProviderAssetStager(settings, registry)
    digest = hashlib.sha256(b"remote-asset").hexdigest()
    staged = stager.stage(
        "duix", AssetLocator("memory", "tenant/t1/input.wav").as_uri(), checksum=digest
    )
    assert staged == "/provider/data/tenant/t1/input.wav"
    assert (tmp_path / "provider" / "tenant/t1/input.wav").read_bytes() == b"remote-asset"
    with pytest.raises(StorageLocatorError, match="checksum"):
        stager.stage(
            "duix", AssetLocator("memory", "tenant/t1/input.wav").as_uri(), checksum="0" * 64
        )
    assert parse_asset_locator("asset://memory/tenant/t1/input.wav") == AssetLocator(
        "memory", "tenant/t1/input.wav"
    )


def test_secret_redaction_covers_headers_credentials_and_nested_payloads() -> None:
    payload = {
        "Authorization": "Bearer visible-token",
        "api_key": "sk-visible",
        "nested": {
            "password": "visible",
            "provider_credential": "visible",
            "message": "request used Service client.secret",
        },
        "cookie": "session=visible",
    }
    rendered = str(redact(payload))
    assert "visible" not in rendered
    assert "client.secret" not in rendered
    assert "[REDACTED]" in rendered
    assert "Bearer [REDACTED]" in safe_error_summary(
        RuntimeError("Authorization Bearer raw-token")
    )


@pytest.mark.asyncio
async def test_readiness_reports_dependency_and_configuration_failures(monkeypatch) -> None:
    class BrokenSession:
        async def execute(self, statement):
            raise RuntimeError("database unavailable")

    class BrokenRedis:
        async def ping(self):
            raise RuntimeError("redis unavailable")

        async def aclose(self):
            return None

    monkeypatch.setattr("app.services.operations_service.Redis.from_url", lambda *args, **kwargs: BrokenRedis())
    settings = Settings(
        _env_file=None,
        auth_mode="oidc",
        asset_storage_backend="s3",
        s3_bucket="",
    )
    result = await dependency_health(BrokenSession(), settings)  # type: ignore[arg-type]
    assert result["postgresql"]["status"] == "unavailable"
    assert result["redis"]["status"] == "unavailable"
    assert result["configuration"]["status"] == "setup_required"
    assert result["storage"]["status"] == "setup_required"
