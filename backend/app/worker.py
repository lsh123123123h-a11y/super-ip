import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.agent import ProductionOrder, ProductionOrderStatus
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
    payload = envelope.get("payload") or {}
    if topic.startswith("workflow."):
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
                    await dispatch_envelope(parse_envelope(item[1], default_topic))
                except Exception:  # noqa: BLE001
                    logger.exception("runtime envelope failed")

            clock = asyncio.get_running_loop().time()
            if clock - last_recovery >= settings.runtime_recovery_interval_seconds:
                workflow_ids, orders = await recover_due_work()
                operation_ids = await list_due_agent_operation_ids()
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
