from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class UsageFactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    source_id: str
    metric: str
    quantity: Decimal
    unit: str
    provider_id: str | None
    model: str | None
    occurred_at: datetime
    dedupe_key: str


class PricingRuleWrite(BaseModel):
    metric: str = Field(min_length=1, max_length=100)
    provider_id: str | None = None
    model: str | None = None
    capability_key: str | None = None
    unit: str = Field(min_length=1, max_length=32)
    unit_size: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal = Field(ge=0)


class PriceBookWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(default="internal_credit", min_length=1, max_length=16)
    effective_from: datetime
    rules: list[PricingRuleWrite] = Field(min_length=1)


class PricingRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    metric: str
    provider_id: str | None
    model: str | None
    capability_key: str | None
    unit: str
    unit_size: Decimal
    unit_price: Decimal


class PriceBookRead(BaseModel):
    id: str
    version: int
    name: str
    currency: str
    effective_from: datetime
    status: str
    created_at: datetime
    rules: list[PricingRuleRead]


class QuotaWrite(BaseModel):
    period: str = Field(pattern="^(day|month|lifetime)$")
    hard_limit: Decimal | None = Field(default=None, ge=0)
    soft_limit: Decimal | None = Field(default=None, ge=0)


class QuotaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    metric: str
    period: str
    period_start: datetime
    period_end: datetime
    hard_limit: Decimal | None
    soft_limit: Decimal | None
    used_quantity: Decimal
    reserved_quantity: Decimal


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entry_type: str
    amount: Decimal
    currency: str
    metric: str | None
    quantity: Decimal | None
    source_type: str
    source_id: str
    price_book_version: int | None
    reverses_entry_id: str | None
    note: str | None
    occurred_at: datetime
    created_at: datetime


class ManualAdjustmentWrite(BaseModel):
    amount: Decimal
    currency: str = Field(default="internal_credit", min_length=1, max_length=16)
    idempotency_key: str = Field(min_length=1, max_length=220)
    note: str = Field(min_length=1, max_length=1000)


class RefundWrite(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=220)
    note: str = Field(min_length=1, max_length=1000)
