from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.principal import Principal
from app.models.metering import LedgerEntry, PriceBook, PricingRule, TenantQuota, UsageFact
from app.schemas.metering import (
    LedgerEntryRead,
    ManualAdjustmentWrite,
    PriceBookRead,
    PriceBookWrite,
    PricingRuleRead,
    QuotaRead,
    QuotaWrite,
    RefundWrite,
    UsageFactRead,
)
from app.services.authorization_service import require_permission
from app.services.metering_service import MeteringService


router = APIRouter(prefix="/admin", tags=["admin-metering"])


@router.get("/usage", response_model=list[UsageFactRead])
async def get_usage(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("usage.read")),
) -> list[UsageFactRead]:
    rows = list(
        (
            await session.scalars(
                select(UsageFact)
                .where(UsageFact.tenant_id == principal.tenant_id)
                .order_by(UsageFact.occurred_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [UsageFactRead.model_validate(row) for row in rows]


@router.get("/ledger", response_model=list[LedgerEntryRead])
async def get_ledger(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("billing.read")),
) -> list[LedgerEntryRead]:
    rows = list(
        (
            await session.scalars(
                select(LedgerEntry)
                .where(LedgerEntry.tenant_id == principal.tenant_id)
                .order_by(LedgerEntry.occurred_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [LedgerEntryRead.model_validate(row) for row in rows]


@router.get("/pricing", response_model=list[PriceBookRead])
async def get_pricing(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("billing.read")),
) -> list[PriceBookRead]:
    books = list(
        (
            await session.scalars(
                select(PriceBook)
                .where(PriceBook.tenant_id == principal.tenant_id)
                .order_by(PriceBook.version.desc())
            )
        ).all()
    )
    result: list[PriceBookRead] = []
    for book in books:
        rules = list(
            (
                await session.scalars(
                    select(PricingRule).where(PricingRule.price_book_id == book.id)
                )
            ).all()
        )
        result.append(
            PriceBookRead(
                id=book.id,
                version=book.version,
                name=book.name,
                currency=book.currency,
                effective_from=book.effective_from,
                status=book.status,
                created_at=book.created_at,
                rules=[PricingRuleRead.model_validate(rule) for rule in rules],
            )
        )
    return result


@router.post("/pricing", response_model=PriceBookRead, status_code=status.HTTP_201_CREATED)
async def post_pricing(
    payload: PriceBookWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("billing.manage")),
) -> PriceBookRead:
    book = await MeteringService().create_price_book(
        session,
        tenant_id=principal.tenant_id,
        name=payload.name,
        currency=payload.currency,
        effective_from=payload.effective_from,
        created_by_user_id=principal.user_id,
        rules=[item.model_dump() for item in payload.rules],
    )
    rules = list(
        (await session.scalars(select(PricingRule).where(PricingRule.price_book_id == book.id))).all()
    )
    return PriceBookRead(
        id=book.id,
        version=book.version,
        name=book.name,
        currency=book.currency,
        effective_from=book.effective_from,
        status=book.status,
        created_at=book.created_at,
        rules=[PricingRuleRead.model_validate(rule) for rule in rules],
    )


@router.get("/quotas", response_model=list[QuotaRead])
async def get_quotas(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("usage.read")),
) -> list[QuotaRead]:
    rows = list(
        (
            await session.scalars(
                select(TenantQuota)
                .where(TenantQuota.tenant_id == principal.tenant_id)
                .order_by(TenantQuota.metric, TenantQuota.period_start.desc())
            )
        ).all()
    )
    return [QuotaRead.model_validate(row) for row in rows]


@router.put("/quotas/{metric}", response_model=QuotaRead)
async def put_quota(
    metric: str,
    payload: QuotaWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("billing.manage")),
) -> QuotaRead:
    quota = await MeteringService().set_quota(
        session,
        tenant_id=principal.tenant_id,
        metric=metric,
        period=payload.period,
        hard_limit=payload.hard_limit,
        soft_limit=payload.soft_limit,
    )
    return QuotaRead.model_validate(quota)


@router.post("/ledger/adjustments", response_model=LedgerEntryRead)
async def post_adjustment(
    payload: ManualAdjustmentWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("billing.manage")),
) -> LedgerEntryRead:
    entry = await MeteringService().adjustment(
        session,
        tenant_id=principal.tenant_id,
        amount=payload.amount,
        currency=payload.currency,
        idempotency_key=payload.idempotency_key,
        user_id=principal.user_id,
        note=payload.note,
    )
    return LedgerEntryRead.model_validate(entry)


@router.post("/ledger/{ledger_entry_id}/refund", response_model=LedgerEntryRead)
async def post_refund(
    ledger_entry_id: str,
    payload: RefundWrite,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_permission("billing.manage")),
) -> LedgerEntryRead:
    try:
        entry = await MeteringService().refund(
            session,
            tenant_id=principal.tenant_id,
            ledger_entry_id=ledger_entry_id,
            idempotency_key=payload.idempotency_key,
            user_id=principal.user_id,
            note=payload.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return LedgerEntryRead.model_validate(entry)
