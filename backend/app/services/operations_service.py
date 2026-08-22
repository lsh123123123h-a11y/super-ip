from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.agent import ConsumedEvent, OutboxEvent
from app.services.storage_service import StorageRegistry, StorageUnavailableError


async def dependency_health(
    session: AsyncSession, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    result: dict[str, Any] = {}
    try:
        await session.execute(text("SELECT 1"))
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        result["postgresql"] = {
            "status": "ready" if revision == settings.readiness_schema_revision else "unavailable",
            "schema_revision": revision,
            "expected_revision": settings.readiness_schema_revision,
        }
    except Exception as exc:  # noqa: BLE001
        result["postgresql"] = {"status": "unavailable", "error": type(exc).__name__}
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        result["redis"] = {"status": "ready" if await redis.ping() else "unavailable"}
    except Exception as exc:  # noqa: BLE001
        result["redis"] = {"status": "unavailable", "error": type(exc).__name__}
    finally:
        await redis.aclose()
    configuration_errors = settings.production_configuration_errors()
    result["configuration"] = {
        "status": "ready" if not configuration_errors else "setup_required",
        "missing": configuration_errors,
        "auth_mode": settings.auth_mode,
    }
    try:
        backend = StorageRegistry(settings).active
        result["storage"] = {
            "status": "ready",
            "backend": backend.backend_id,
        }
    except StorageUnavailableError as exc:
        result["storage"] = {
            "status": "setup_required",
            "backend": settings.asset_storage_backend,
            "error": str(exc),
        }
    return result


async def platform_snapshot(
    session: AsyncSession, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    dependencies = await dependency_health(session, settings)
    outbox_backlog = int(
        await session.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
            )
        )
        or 0
    )
    outbox_dead = int(
        await session.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.dead_lettered_at.is_not(None)
            )
        )
        or 0
    )
    consumer_dead = int(
        await session.scalar(
            select(func.count(ConsumedEvent.id))
            .join(OutboxEvent, OutboxEvent.id == ConsumedEvent.event_id)
            .where(ConsumedEvent.dead_lettered_at.is_not(None))
        )
        or 0
    )
    return {
        "status": (
            "ready"
            if all(
                item.get("status") == "ready"
                for item in dependencies.values()
            )
            else "degraded"
        ),
        "components": dependencies,
        "outbox": {
            "backlog": outbox_backlog,
            "dead_letters": outbox_dead,
            "consumer_dead_letters": consumer_dead,
        },
    }
