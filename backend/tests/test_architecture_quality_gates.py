import ast
from pathlib import Path

from app.capabilities.registry import get_capability_registry
from app.core.config import Settings


APP_ROOT = Path(__file__).parents[1] / "app"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return modules


def test_agent_kernel_does_not_depend_on_provider_or_workflow_implementations() -> None:
    forbidden = ("app.providers", "app.workflows", "app.product", "app.schemas.workflows")
    for path in (APP_ROOT / "agent").glob("*.py"):
        assert not any(
            module.startswith(prefix)
            for module in imported_modules(path)
            for prefix in forbidden
        ), path


def test_provider_adapters_do_not_own_production_order_state() -> None:
    for path in (APP_ROOT / "providers").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "ProductionOrder" not in source, path
        assert "agent_service" not in source, path


def test_redis_is_transport_not_runtime_state_truth() -> None:
    worker = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    assert "SessionLocal" in worker
    assert "OutboxEvent" in worker
    assert "redis.hset" not in worker.lower()
    assert "redis.set(" not in worker.lower()


def test_capability_keys_are_business_semantics_not_executor_names() -> None:
    forbidden = ("codex", "hermes", "claude", "cli", "harness")
    for capability in get_capability_registry().catalog():
        assert not any(name in capability.key.lower() for name in forbidden)


def test_production_auth_and_storage_boundaries_are_explicit() -> None:
    oidc = Settings(
        _env_file=None,
        auth_mode="oidc",
        oidc_issuer="https://identity.example",
        oidc_audience="api",
        oidc_jwks_url="https://identity.example/jwks",
    )
    assert oidc.production_configuration_errors() == []
    assets_route = (APP_ROOT / "api" / "routes" / "assets.py").read_text(encoding="utf-8")
    assert "duix_shared_data_root" not in assets_route
    assert "StorageService" in assets_route
