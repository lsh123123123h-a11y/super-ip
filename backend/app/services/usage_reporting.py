from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestration import ProviderJob, WorkflowRun
from app.services.metering_service import UsageReport, UsageReporter


class ProviderUsageReporter:
    """Platform-owned normalization port for Provider and Workflow usage."""

    def __init__(self, reporter: UsageReporter | None = None) -> None:
        self.reporter = reporter or UsageReporter()

    async def record_success(
        self,
        session: AsyncSession,
        *,
        workflow: WorkflowRun,
        job: ProviderJob,
        raw_usage: Any,
        occurred_at: datetime | None = None,
    ) -> list[str]:
        if not workflow.tenant_id:
            return []
        moment = occurred_at or datetime.now(UTC)
        facts = [
            UsageReport(
                tenant_id=workflow.tenant_id,
                source_type="provider_job",
                source_id=job.id,
                metric="provider.request",
                quantity=Decimal("1"),
                unit="request",
                dedupe_key=f"provider_job:{job.id}:provider.request",
                occurred_at=moment,
                workflow_run_id=workflow.id,
                capability_key=job.capability,
                provider_id=job.provider,
            )
        ]
        if isinstance(raw_usage, dict):
            metrics = raw_usage.get("metrics")
            if isinstance(metrics, list):
                for index, item in enumerate(metrics):
                    if not isinstance(item, dict):
                        continue
                    metric = str(item.get("metric") or "")
                    unit = str(item.get("unit") or "")
                    try:
                        quantity = Decimal(str(item.get("quantity")))
                    except (InvalidOperation, TypeError):
                        continue
                    if metric and unit and quantity >= 0:
                        facts.append(
                            UsageReport(
                                tenant_id=workflow.tenant_id,
                                source_type="provider_job",
                                source_id=job.id,
                                metric=metric,
                                quantity=quantity,
                                unit=unit,
                                dedupe_key=f"provider_job:{job.id}:{metric}:{index}",
                                occurred_at=moment,
                                workflow_run_id=workflow.id,
                                capability_key=job.capability,
                                provider_id=job.provider,
                            )
                        )
        result: list[str] = []
        for fact in facts:
            recorded = await self.reporter.record(session, fact)
            result.append(recorded.id)
        return result
