import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.agent import (
    ConsumedEvent,
    OutboxEvent,
    ProductionOrder,
    ProductionOrderStatus,
)
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.services.agent_operation_service import (
    list_due_agent_operation_ids,
    run_agent_operation_once,
)
from app.services.agent_runtime import run_agent_once
from app.services.outbox_service import publish_outbox_batch
from app.services.workflow_runtime import run_workflow_once, worker_id


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("xingliu.worker")
settings = get_settings()
CONSUMER_NAME = "runtime-worker-v1"
SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_RUNTIME_TOPICS = {
    "workflow.run.requested",
    "agent.operation.requested",
    "agent.run.requested",
    "agent.cancel.requested",
}


class UnsupportedRuntimeEventError(ValueError):
    pass


async def recover_due_work() -> tuple[list[str], list[tuple[str, ProductionOrderStatus]]]:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        workflow_result = await session.execute(
            select(WorkflowRun.id)
            .where(
                WorkflowRun.status.in_(
                    [
                        WorkflowStatus.queued,
                        WorkflowStatus.running,
                        WorkflowStatus.waiting_provider,
                        WorkflowStatus.retry_wait,
                        WorkflowStatus.canceling,
                    ]
                ),
                or_(
                    WorkflowRun.next_wakeup_at.is_(None),
                    WorkflowRun.next_wakeup_at <= now,
                ),
                or_(
                    WorkflowRun.lease_expires_at.is_(None),
                    WorkflowRun.lease_expires_at <= now,
                ),
            )
            .order_by(WorkflowRun.updated_at)
            .limit(20)
        )
        order_result = await session.execute(
            select(ProductionOrder.id, ProductionOrder.status)
            .where(
                ProductionOrder.status.in_(
                    [
                        ProductionOrderStatus.queued,
                        ProductionOrderStatus.running,
                        ProductionOrderStatus.canceling,
                        ProductionOrderStatus.retry_wait,
                        ProductionOrderStatus.evaluating,
                    ]
                )
            )
            .order_by(ProductionOrder.updated_at)
            .limit(20)
        )
        return list(workflow_result.scalars()), list(order_result.all())


def parse_envelope(raw: str, default_topic: str) -> dict[str, Any]:
    try:
        envelope = json.loads(raw)
        if isinstance(envelope, dict) and envelope.get("topic"):
            return envelope
    except json.JSONDecodeError:
        pass
    return {
        "topic": default_topic,
        "aggregate_id": raw,
        "payload": {"workflow_id": raw},
    }


async def dispatch_envelope(envelope: dict[str, Any]) -> None:
    topic = str(envelope.get("topic") or "")
    try:
        schema_version = int(envelope.get("schema_version") or 1)
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise UnsupportedRuntimeEventError(
            f"不支持的运行时事件 schema_version：{schema_version}"
        )
    if topic not in SUPPORTED_RUNTIME_TOPICS:
        raise UnsupportedRuntimeEventError(f"不支持的运行时事件 topic：{topic or '<empty>'}")
    payload = envelope.get("payload") or {}
    if topic == "workflow.run.requested":
        workflow_id = str(
            payload.get("workflow_id") or envelope.get("aggregate_id")
        )
        await run_workflow_once(workflow_id)
    elif topic == "agent.operation.requested":
        operation_id = str(
            payload.get("agent_operation_id") or envelope.get("aggregate_id")
        )
        await run_agent_operation_once(operation_id, worker_id)
    elif topic in {"agent.run.requested", "agent.cancel.requested"}:
        order_id = str(
            payload.get("production_order_id") or envelope.get("aggregate_id")
        )
        await run_agent_once(order_id, payload.get("agent_run_id"))


async def _claim_envelope(envelope: dict[str, Any]) -> int | None:
    event_id = str(envelope.get("event_id") or "")
    if not event_id:
        return 0  # compatibility for legacy queue entries
    try:
        schema_version = int(envelope.get("schema_version") or 1)
    except (TypeError, ValueError):
        schema_version = -1
    now = datetime.now(UTC)
    consumer_name = CONSUMER_NAME
    async with SessionLocal() as session:
        row = await session.scalar(
            select(ConsumedEvent)
            .where(
                ConsumedEvent.consumer_name == consumer_name,
                ConsumedEvent.event_id == event_id,
            )
            .with_for_update()
        )
        if row is None:
            row = ConsumedEvent(
                consumer_name=consumer_name,
                event_id=event_id,
                topic=str(envelope.get("topic") or ""),
                schema_version=schema_version,
                status="processing",
                attempts=1,
                fence_token=1,
                lease_expires_at=now
                + timedelta(seconds=settings.runtime_consumer_lease_seconds),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await _claim_envelope(envelope)
            return row.fence_token
        lease_expires_at = row.lease_expires_at
        if lease_expires_at and lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        if row.status == "succeeded":
            return None
        if row.status == "dead_lettered" or row.dead_lettered_at is not None:
            return None
        if row.status == "processing" and lease_expires_at and lease_expires_at > now:
            return None
        next_attempt_at = row.next_attempt_at
        if next_attempt_at and next_attempt_at.tzinfo is None:
            next_attempt_at = next_attempt_at.replace(tzinfo=UTC)
        if row.status == "failed" and next_attempt_at and next_attempt_at > now:
            return None
        row.status = "processing"
        row.attempts += 1
        row.fence_token += 1
        row.lease_expires_at = now + timedelta(
            seconds=settings.runtime_consumer_lease_seconds
        )
        row.next_attempt_at = None
        row.last_error = None
        await session.commit()
        return row.fence_token


async def _finish_envelope(
    envelope: dict[str, Any],
    fence_token: int,
    error: Exception | None,
) -> None:
    event_id = str(envelope.get("event_id") or "")
    if not event_id or fence_token == 0:
        return
    async with SessionLocal() as session:
        row = await session.scalar(
            select(ConsumedEvent)
            .where(
                ConsumedEvent.consumer_name == CONSUMER_NAME,
                ConsumedEvent.event_id == event_id,
                ConsumedEvent.fence_token == fence_token,
            )
            .with_for_update()
        )
        if row is None:
            return
        now = datetime.now(UTC)
        row.lease_expires_at = None
        if error is None:
            row.status = "succeeded"
            row.processed_at = now
            row.next_attempt_at = None
            row.dead_lettered_at = None
            row.last_error = None
        else:
            row.last_error = str(error)[:2000]
            if row.attempts >= settings.runtime_consumer_max_attempts:
                row.status = "dead_lettered"
                row.dead_lettered_at = now
                row.next_attempt_at = None
            else:
                row.status = "failed"
                delay = settings.runtime_consumer_retry_base_seconds * (
                    2 ** max(0, row.attempts - 1)
                )
                row.next_attempt_at = now + timedelta(seconds=delay)
        await session.commit()


async def dispatch_envelope_once(envelope: dict[str, Any]) -> None:
    fence_token = await _claim_envelope(envelope)
    if fence_token is None:
        return
    try:
        await dispatch_envelope(envelope)
    except Exception as exc:
        await _finish_envelope(envelope, fence_token, exc)
        raise
    await _finish_envelope(envelope, fence_token, None)


def _outbox_envelope(event: OutboxEvent) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "schema_version": event.schema_version,
        "topic": event.topic,
        "tenant_id": event.tenant_id,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "payload": event.payload,
    }


async def recover_consumed_envelopes(limit: int = 20) -> list[dict[str, Any]]:
    """Rebuild due/abandoned deliveries from the PostgreSQL outbox."""

    now = datetime.now(UTC)
    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(OutboxEvent)
                    .join(ConsumedEvent, ConsumedEvent.event_id == OutboxEvent.id)
                    .where(
                        ConsumedEvent.consumer_name == CONSUMER_NAME,
                        ConsumedEvent.dead_lettered_at.is_(None),
                        or_(
                            and_(
                                ConsumedEvent.status == "failed",
                                or_(
                                    ConsumedEvent.next_attempt_at.is_(None),
                                    ConsumedEvent.next_attempt_at <= now,
                                ),
                            ),
                            and_(
                                ConsumedEvent.status == "processing",
                                ConsumedEvent.lease_expires_at <= now,
                            ),
                        ),
                    )
                    .order_by(ConsumedEvent.updated_at)
                    .limit(limit)
                )
            ).scalars()
        )
    return [_outbox_envelope(event) for event in rows]


async def main() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("runtime worker %s listening", worker_id)
    last_recovery = 0.0
    try:
        while True:
            async with SessionLocal() as session:
                await publish_outbox_batch(session, redis, settings)
            item = await redis.blpop(
                [settings.agent_queue, settings.workflow_queue],
                timeout=2,
            )
            if item:
                default_topic = (
                    "agent.run.requested"
                    if item[0] == settings.agent_queue
                    else "workflow.run.requested"
                )
                try:
                    await dispatch_envelope_once(
                        parse_envelope(item[1], default_topic)
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("runtime envelope failed")

            clock = asyncio.get_running_loop().time()
            if clock - last_recovery >= settings.runtime_recovery_interval_seconds:
                workflow_ids, orders = await recover_due_work()
                operation_ids = await list_due_agent_operation_ids()
                recovery_envelopes = await recover_consumed_envelopes()
                for envelope in recovery_envelopes:
                    try:
                        await dispatch_envelope_once(envelope)
                    except Exception:  # noqa: BLE001
                        logger.exception("recovered runtime envelope failed")
                for workflow_id in workflow_ids:
                    await run_workflow_once(workflow_id)
                for operation_id in operation_ids:
                    await run_agent_operation_once(operation_id, worker_id)
                for order_id, _ in orders:
                    await run_agent_once(order_id)
                last_recovery = clock
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
