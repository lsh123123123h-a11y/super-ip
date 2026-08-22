from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentOperation, ProductionOrder
from app.models.metering import (
    LedgerEntry,
    PriceBook,
    PricingRule,
    TenantQuota,
    UsageFact,
    UsageReservation,
)
from app.core.observability import QUOTA_REJECTS


class QuotaExceededError(RuntimeError):
    pass


class BudgetExceededError(RuntimeError):
    pass


class MeteringConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UsageReport:
    tenant_id: str
    source_type: str
    source_id: str
    metric: str
    quantity: Decimal
    unit: str
    dedupe_key: str
    occurred_at: datetime
    operation_id: str | None = None
    workflow_run_id: str | None = None
    step_execution_id: str | None = None
    capability_key: str | None = None
    provider_id: str | None = None
    model: str | None = None
    metadata: dict[str, Any] | None = None


def period_bounds(period: str, moment: datetime) -> tuple[datetime, datetime]:
    value = moment.astimezone(UTC)
    if period == "day":
        start = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if period == "month":
        start = value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end
    if period == "lifetime":
        return datetime(1970, 1, 1, tzinfo=UTC), datetime(9999, 1, 1, tzinfo=UTC)
    raise ValueError("period 必须是 day、month 或 lifetime")


class UsageReporter:
    async def record(self, session: AsyncSession, report: UsageReport) -> UsageFact:
        existing = await session.scalar(
            select(UsageFact).where(
                UsageFact.tenant_id == report.tenant_id,
                UsageFact.dedupe_key == report.dedupe_key,
            )
        )
        if existing is not None:
            if (
                existing.metric != report.metric
                or Decimal(existing.quantity) != Decimal(report.quantity)
                or existing.unit != report.unit
            ):
                raise MeteringConflictError("dedupe_key 已绑定到不同 Usage Fact")
            return existing
        fact = UsageFact(
            tenant_id=report.tenant_id,
            source_type=report.source_type,
            source_id=report.source_id,
            operation_id=report.operation_id,
            workflow_run_id=report.workflow_run_id,
            step_execution_id=report.step_execution_id,
            capability_key=report.capability_key,
            provider_id=report.provider_id,
            model=report.model,
            metric=report.metric,
            quantity=report.quantity,
            unit=report.unit,
            occurred_at=report.occurred_at,
            metadata_payload=report.metadata or {},
            dedupe_key=report.dedupe_key,
        )
        try:
            async with session.begin_nested():
                session.add(fact)
                await session.flush()
        except IntegrityError:
            fact = await session.scalar(
                select(UsageFact).where(
                    UsageFact.tenant_id == report.tenant_id,
                    UsageFact.dedupe_key == report.dedupe_key,
                )
            )
            if fact is None:
                raise
        return fact


class MeteringService:
    def __init__(self, reporter: UsageReporter | None = None) -> None:
        self.reporter = reporter or UsageReporter()

    async def create_price_book(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        name: str,
        currency: str,
        effective_from: datetime,
        created_by_user_id: str,
        rules: list[dict[str, Any]],
    ) -> PriceBook:
        latest = await session.scalar(
            select(func.max(PriceBook.version)).where(PriceBook.tenant_id == tenant_id)
        )
        book = PriceBook(
            tenant_id=tenant_id,
            version=int(latest or 0) + 1,
            name=name,
            currency=currency,
            effective_from=effective_from,
            created_by_user_id=created_by_user_id,
        )
        session.add(book)
        await session.flush()
        for raw in rules:
            session.add(
                PricingRule(
                    tenant_id=tenant_id,
                    price_book_id=book.id,
                    metric=raw["metric"],
                    provider_id=raw.get("provider_id"),
                    model=raw.get("model"),
                    capability_key=raw.get("capability_key"),
                    unit=raw["unit"],
                    unit_size=Decimal(str(raw.get("unit_size", 1))),
                    unit_price=Decimal(str(raw["unit_price"])),
                )
            )
        await session.commit()
        await session.refresh(book)
        return book

    async def set_quota(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        metric: str,
        period: str,
        hard_limit: Decimal | None,
        soft_limit: Decimal | None,
        moment: datetime | None = None,
    ) -> TenantQuota:
        start, end = period_bounds(period, moment or datetime.now(UTC))
        quota = await session.scalar(
            select(TenantQuota).where(
                TenantQuota.tenant_id == tenant_id,
                TenantQuota.metric == metric,
                TenantQuota.period == period,
                TenantQuota.period_start == start,
            )
        )
        if quota is None:
            quota = TenantQuota(
                tenant_id=tenant_id,
                metric=metric,
                period=period,
                period_start=start,
                period_end=end,
                hard_limit=hard_limit,
                soft_limit=soft_limit,
            )
            session.add(quota)
        else:
            quota.hard_limit = hard_limit
            quota.soft_limit = soft_limit
        await session.commit()
        await session.refresh(quota)
        return quota

    async def reserve(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        metric: str,
        quantity: Decimal,
        unit: str,
        idempotency_key: str,
        production_order_id: str | None = None,
        operation_id: str | None = None,
        provider_id: str | None = None,
        model: str | None = None,
        capability_key: str | None = None,
        moment: datetime | None = None,
    ) -> UsageReservation:
        existing = await session.scalar(
            select(UsageReservation).where(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        now = moment or datetime.now(UTC)
        quota = await self._current_quota(session, tenant_id, metric, now, lock=True)
        if quota and quota.hard_limit is not None:
            projected = Decimal(quota.used_quantity) + Decimal(quota.reserved_quantity) + quantity
            if projected > Decimal(quota.hard_limit):
                QUOTA_REJECTS.labels(metric=metric).inc()
                raise QuotaExceededError(f"{metric} hard quota exceeded")
        rule, book = await self._pricing_rule(
            session,
            tenant_id=tenant_id,
            metric=metric,
            provider_id=provider_id,
            model=model,
            capability_key=capability_key,
            occurred_at=now,
        )
        amount = self._price(quantity, rule) if rule else Decimal("0")
        if production_order_id:
            await self._check_order_budget(session, production_order_id, amount)
        reservation = UsageReservation(
            tenant_id=tenant_id,
            quota_id=quota.id if quota else None,
            production_order_id=production_order_id,
            operation_id=operation_id,
            metric=metric,
            quantity=quantity,
            unit=unit,
            reserved_amount=amount,
            currency=book.currency if book else "internal_credit",
            pricing_rule_id=rule.id if rule else None,
            price_book_version=book.version if book else None,
            idempotency_key=idempotency_key,
        )
        session.add(reservation)
        if quota:
            quota.reserved_quantity = Decimal(quota.reserved_quantity) + quantity
        if operation_id:
            operation = await session.get(AgentOperation, operation_id)
            if operation:
                operation.budget_reserved = Decimal(operation.budget_reserved) + amount
        await session.flush()
        await self._append_ledger(
            session,
            tenant_id=tenant_id,
            entry_type="reservation",
            amount=amount,
            currency=reservation.currency,
            metric=metric,
            quantity=quantity,
            source_type="usage_reservation",
            source_id=reservation.id,
            pricing_rule_id=reservation.pricing_rule_id,
            price_book_version=reservation.price_book_version,
            production_order_id=production_order_id,
            operation_id=operation_id,
            idempotency_key=f"{idempotency_key}:reservation",
            occurred_at=now,
        )
        await session.commit()
        await session.refresh(reservation)
        return reservation

    async def settle(
        self,
        session: AsyncSession,
        *,
        reservation_id: str,
        report: UsageReport,
        idempotency_key: str,
    ) -> tuple[UsageFact, LedgerEntry | None]:
        existing_entry = await session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == report.tenant_id,
                LedgerEntry.idempotency_key == idempotency_key,
            )
        )
        fact = await self.reporter.record(session, report)
        if existing_entry is not None:
            return fact, existing_entry
        reservation = await session.scalar(
            select(UsageReservation)
            .where(
                UsageReservation.id == reservation_id,
                UsageReservation.tenant_id == report.tenant_id,
            )
            .with_for_update()
        )
        if reservation is None:
            raise LookupError("Usage reservation 不存在")
        if reservation.status == "released":
            raise MeteringConflictError("已释放 reservation 不能结算")
        if reservation.status == "settled":
            return fact, await session.scalar(
                select(LedgerEntry).where(
                    LedgerEntry.tenant_id == report.tenant_id,
                    LedgerEntry.idempotency_key == idempotency_key,
                )
            )
        quota = await session.get(TenantQuota, reservation.quota_id) if reservation.quota_id else None
        if quota and quota.hard_limit is not None:
            projected = (
                Decimal(quota.used_quantity)
                + Decimal(quota.reserved_quantity)
                - Decimal(reservation.quantity)
                + Decimal(report.quantity)
            )
            if projected > Decimal(quota.hard_limit):
                QUOTA_REJECTS.labels(metric=report.metric).inc()
                raise QuotaExceededError(f"{report.metric} hard quota exceeded")
        rule = await session.get(PricingRule, reservation.pricing_rule_id) if reservation.pricing_rule_id else None
        amount = self._price(report.quantity, rule) if rule else Decimal("0")
        if reservation.production_order_id:
            additional = max(Decimal("0"), amount - Decimal(reservation.reserved_amount))
            await self._check_order_budget(session, reservation.production_order_id, additional)
        await self._append_ledger(
            session,
            tenant_id=report.tenant_id,
            entry_type="release",
            amount=-Decimal(reservation.reserved_amount),
            currency=reservation.currency,
            metric=reservation.metric,
            quantity=-Decimal(reservation.quantity),
            source_type="usage_reservation",
            source_id=reservation.id,
            pricing_rule_id=reservation.pricing_rule_id,
            price_book_version=reservation.price_book_version,
            production_order_id=reservation.production_order_id,
            operation_id=reservation.operation_id,
            idempotency_key=f"{idempotency_key}:release",
            occurred_at=report.occurred_at,
        )
        debit = await self._append_ledger(
            session,
            tenant_id=report.tenant_id,
            entry_type="debit",
            amount=amount,
            currency=reservation.currency,
            metric=report.metric,
            quantity=report.quantity,
            source_type=report.source_type,
            source_id=report.source_id,
            usage_fact_id=fact.id,
            pricing_rule_id=reservation.pricing_rule_id,
            price_book_version=reservation.price_book_version,
            production_order_id=reservation.production_order_id,
            operation_id=reservation.operation_id,
            workflow_run_id=report.workflow_run_id,
            idempotency_key=idempotency_key,
            occurred_at=report.occurred_at,
        )
        if quota:
            quota.reserved_quantity = max(
                Decimal("0"), Decimal(quota.reserved_quantity) - Decimal(reservation.quantity)
            )
            quota.used_quantity = Decimal(quota.used_quantity) + Decimal(report.quantity)
        if reservation.operation_id:
            operation = await session.get(AgentOperation, reservation.operation_id)
            if operation:
                operation.budget_reserved = max(
                    Decimal("0"),
                    Decimal(operation.budget_reserved) - Decimal(reservation.reserved_amount),
                )
                operation.budget_spent = Decimal(operation.budget_spent) + amount
        reservation.status = "settled"
        reservation.settled_at = datetime.now(UTC)
        await session.commit()
        return fact, debit

    async def release(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        reservation_id: str,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> LedgerEntry | None:
        reservation = await session.scalar(
            select(UsageReservation)
            .where(
                UsageReservation.id == reservation_id,
                UsageReservation.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if reservation is None:
            raise LookupError("Usage reservation 不存在")
        if reservation.status == "settled":
            raise MeteringConflictError("已结算 reservation 不能释放")
        existing = await session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == tenant_id,
                LedgerEntry.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        if reservation.status == "released":
            return None
        entry = await self._append_ledger(
            session,
            tenant_id=tenant_id,
            entry_type="release",
            amount=-Decimal(reservation.reserved_amount),
            currency=reservation.currency,
            metric=reservation.metric,
            quantity=-Decimal(reservation.quantity),
            source_type="usage_reservation",
            source_id=reservation.id,
            pricing_rule_id=reservation.pricing_rule_id,
            price_book_version=reservation.price_book_version,
            production_order_id=reservation.production_order_id,
            operation_id=reservation.operation_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at or datetime.now(UTC),
        )
        if reservation.quota_id:
            quota = await session.get(TenantQuota, reservation.quota_id)
            if quota:
                quota.reserved_quantity = max(
                    Decimal("0"), Decimal(quota.reserved_quantity) - Decimal(reservation.quantity)
                )
        if reservation.operation_id:
            operation = await session.get(AgentOperation, reservation.operation_id)
            if operation:
                operation.budget_reserved = max(
                    Decimal("0"),
                    Decimal(operation.budget_reserved) - Decimal(reservation.reserved_amount),
                )
        reservation.status = "released"
        reservation.released_at = datetime.now(UTC)
        await session.commit()
        return entry

    async def record_and_price(
        self, session: AsyncSession, report: UsageReport
    ) -> tuple[UsageFact, LedgerEntry | None]:
        fact = await self.reporter.record(session, report)
        key = f"usage:{fact.id}:debit"
        existing = await session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == report.tenant_id,
                LedgerEntry.idempotency_key == key,
            )
        )
        if existing is not None:
            return fact, existing
        rule, book = await self._pricing_rule(
            session,
            tenant_id=report.tenant_id,
            metric=report.metric,
            provider_id=report.provider_id,
            model=report.model,
            capability_key=report.capability_key,
            occurred_at=report.occurred_at,
        )
        if rule is None or book is None:
            await session.commit()
            return fact, None
        entry = await self._append_ledger(
            session,
            tenant_id=report.tenant_id,
            entry_type="debit",
            amount=self._price(report.quantity, rule),
            currency=book.currency,
            metric=report.metric,
            quantity=report.quantity,
            source_type=report.source_type,
            source_id=report.source_id,
            usage_fact_id=fact.id,
            pricing_rule_id=rule.id,
            price_book_version=book.version,
            operation_id=report.operation_id,
            workflow_run_id=report.workflow_run_id,
            idempotency_key=key,
            occurred_at=report.occurred_at,
        )
        quota = await self._current_quota(
            session, report.tenant_id, report.metric, report.occurred_at, lock=True
        )
        if quota:
            quota.used_quantity = Decimal(quota.used_quantity) + report.quantity
        await session.commit()
        return fact, entry

    async def refund(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        ledger_entry_id: str,
        idempotency_key: str,
        user_id: str,
        note: str,
    ) -> LedgerEntry:
        source = await session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.id == ledger_entry_id,
                LedgerEntry.tenant_id == tenant_id,
                LedgerEntry.entry_type == "debit",
            )
        )
        if source is None:
            raise LookupError("可退款 Ledger debit 不存在")
        existing = await session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == tenant_id,
                LedgerEntry.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing
        entry = await self._append_ledger(
            session,
            tenant_id=tenant_id,
            entry_type="refund",
            amount=-Decimal(source.amount),
            currency=source.currency,
            metric=source.metric,
            quantity=-Decimal(source.quantity or 0),
            source_type="ledger_entry",
            source_id=source.id,
            usage_fact_id=source.usage_fact_id,
            pricing_rule_id=source.pricing_rule_id,
            price_book_version=source.price_book_version,
            production_order_id=source.production_order_id,
            operation_id=source.operation_id,
            workflow_run_id=source.workflow_run_id,
            reverses_entry_id=source.id,
            idempotency_key=idempotency_key,
            note=note,
            created_by_user_id=user_id,
            occurred_at=datetime.now(UTC),
        )
        await session.commit()
        return entry

    async def adjustment(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        user_id: str,
        note: str,
    ) -> LedgerEntry:
        existing = await session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == tenant_id,
                LedgerEntry.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing
        entry = await self._append_ledger(
            session,
            tenant_id=tenant_id,
            entry_type="adjustment",
            amount=amount,
            currency=currency,
            source_type="manual_adjustment",
            source_id=idempotency_key,
            idempotency_key=idempotency_key,
            note=note,
            created_by_user_id=user_id,
            occurred_at=datetime.now(UTC),
        )
        await session.commit()
        return entry

    async def _pricing_rule(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        metric: str,
        provider_id: str | None,
        model: str | None,
        capability_key: str | None,
        occurred_at: datetime,
    ) -> tuple[PricingRule | None, PriceBook | None]:
        rows = (
            await session.execute(
                select(PricingRule, PriceBook)
                .join(PriceBook, PriceBook.id == PricingRule.price_book_id)
                .where(
                    PricingRule.tenant_id == tenant_id,
                    PricingRule.metric == metric,
                    PriceBook.effective_from <= occurred_at,
                    PriceBook.status == "active",
                )
                .order_by(PriceBook.version.desc())
            )
        ).all()
        candidates = [
            (rule, book)
            for rule, book in rows
            if (rule.provider_id is None or rule.provider_id == provider_id)
            and (rule.model is None or rule.model == model)
            and (rule.capability_key is None or rule.capability_key == capability_key)
        ]
        if not candidates:
            return None, None
        return max(
            candidates,
            key=lambda item: (
                item[1].version,
                sum(
                    value is not None
                    for value in (
                        item[0].provider_id,
                        item[0].model,
                        item[0].capability_key,
                    )
                ),
            ),
        )

    async def _current_quota(
        self,
        session: AsyncSession,
        tenant_id: str,
        metric: str,
        moment: datetime,
        *,
        lock: bool,
    ) -> TenantQuota | None:
        query = select(TenantQuota).where(
            TenantQuota.tenant_id == tenant_id,
            TenantQuota.metric == metric,
            TenantQuota.period_start <= moment,
            TenantQuota.period_end > moment,
        )
        if lock:
            query = query.with_for_update()
        return await session.scalar(query.order_by(TenantQuota.period_end).limit(1))

    async def _check_order_budget(
        self, session: AsyncSession, production_order_id: str, additional: Decimal
    ) -> None:
        order = await session.get(ProductionOrder, production_order_id)
        if order is None or order.budget_limit is None:
            return
        net = Decimal(
            await session.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                    LedgerEntry.production_order_id == production_order_id
                )
            )
            or 0
        )
        if net + additional > Decimal(order.budget_limit):
            raise BudgetExceededError("ProductionOrder budget_limit exceeded")

    @staticmethod
    def _price(quantity: Decimal, rule: PricingRule) -> Decimal:
        size = Decimal(rule.unit_size)
        if size <= 0:
            raise MeteringConflictError("PricingRule unit_size 必须大于 0")
        return (quantity / size * Decimal(rule.unit_price)).quantize(Decimal("0.00000001"))

    async def _append_ledger(self, session: AsyncSession, **values: Any) -> LedgerEntry:
        existing = await session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.tenant_id == values["tenant_id"],
                LedgerEntry.idempotency_key == values["idempotency_key"],
            )
        )
        if existing:
            return existing
        entry = LedgerEntry(**values)
        session.add(entry)
        await session.flush()
        return entry
