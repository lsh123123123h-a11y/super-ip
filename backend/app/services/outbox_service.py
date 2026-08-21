import json
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.agent import OutboxEvent


def queue_for_topic(settings: Settings, topic: str) -> str:
    return settings.agent_queue if topic.startswith("agent.") else settings.workflow_queue


async def publish_outbox_batch(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> int:
    now = datetime.now(UTC)
    result = await session.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.available_at <= now,
        )
        .order_by(OutboxEvent.created_at)
        .limit(settings.outbox_batch_size)
        .with_for_update(skip_locked=True)
    )
    events = list(result.scalars())
    published = 0
    for event in events:
        envelope = json.dumps(
            {
                "event_id": event.id,
                "topic": event.topic,
                "tenant_id": event.tenant_id,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "payload": event.payload,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            await redis.rpush(queue_for_topic(settings, event.topic), envelope)
        except Exception as exc:
            event.attempts += 1
            event.last_error = str(exc)
            continue
        event.attempts += 1
        event.last_error = None
        event.published_at = now
        published += 1
    await session.commit()
    return published
