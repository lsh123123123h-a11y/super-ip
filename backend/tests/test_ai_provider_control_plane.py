import os
import uuid
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.agent.brain import StructuredBrainRequest, StructuredBrainResponse
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.principal import Principal
from app.integrations import managed_brain as managed_brain_module
from app.integrations.managed_brain import create_managed_brain
from app.models.ai_provider import AIInvocation, AIProviderConfig
from app.schemas.ai_providers import AIModelBindingWrite, AIProviderWrite
from app.services.ai_provider_service import (
    create_ai_provider,
    get_ai_provider_read,
    list_ai_invocations,
    update_ai_provider,
)
from app.services.identity_service import ensure_principal_records


pytestmark = [
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="需要迁移后的隔离 PostgreSQL 测试库",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


class ObservedNewApiAdapter:
    requested_models: list[str] = []

    def __init__(self, **kwargs):
        self.default_model = kwargs["default_model"]

    async def complete_structured(self, request):
        self.requested_models.append(self.default_model)
        return StructuredBrainResponse(
            output={"ok": True},
            model_ref=self.default_model,
            gateway_ref="new-api",
            usage={"input_tokens": 9, "output_tokens": 3, "total_tokens": 12},
            raw_response_id=f"request-{len(self.requested_models)}",
            reported_cost=Decimal("0.0012"),
            cost_currency="USD",
        )

    async def probe(self):
        return {"ok": True}


async def test_provider_secret_alias_updates_and_invocation_facts(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "ai_provider_secret_key",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setattr(
        managed_brain_module,
        "NewApiBrainAdapter",
        ObservedNewApiAdapter,
    )
    ObservedNewApiAdapter.requested_models = []

    suffix = uuid.uuid4().hex[:10]
    principal = Principal(
        tenant_id=f"ai-provider-{suffix}",
        user_id=f"ai-admin-{suffix}",
    )
    secret = f"sk-secret-{suffix}"
    async with SessionLocal() as session:
        await ensure_principal_records(session, principal)
        await session.commit()
        provider = await create_ai_provider(
            session,
            principal=principal,
            payload=AIProviderWrite(
                name="New API 测试网关",
                base_url="https://gateway.example",
                api_key=secret,
                default_model="model-v1",
                bindings=[
                    AIModelBindingWrite(
                        model_alias="reasoning.default",
                        upstream_model="model-v1",
                    ),
                    AIModelBindingWrite(
                        model_alias="writing.default",
                        upstream_model="model-v1",
                    ),
                ],
            ),
        )
        persisted = await session.get(AIProviderConfig, provider.id)
        assert persisted is not None
        assert persisted.secret_ciphertext != secret
        assert secret not in persisted.secret_ciphertext
        read = await get_ai_provider_read(
            session, tenant_id=principal.tenant_id, provider_id=provider.id
        )
        assert read.secret_hint.endswith(suffix[-4:])
        assert "api_key" not in read.model_dump(mode="json")

    brain = create_managed_brain(principal.tenant_id)
    request = StructuredBrainRequest(
        purpose="production_plan",
        system_instruction="return json",
        user_input={"goal": "test"},
        output_schema={"type": "object"},
        model_alias="reasoning.default",
        metadata={"production_order_id": "order-1", "private": "not-recorded"},
    )
    await brain.complete_structured(request)

    async with SessionLocal() as session:
        await update_ai_provider(
            session,
            principal=principal,
            provider_id=provider.id,
            payload=AIProviderWrite(
                name="New API 测试网关",
                base_url="https://gateway.example",
                default_model="model-v2",
                bindings=[
                    AIModelBindingWrite(
                        model_alias="reasoning.default",
                        upstream_model="model-v2",
                    ),
                    AIModelBindingWrite(
                        model_alias="writing.default",
                        upstream_model="model-v2",
                    ),
                ],
            ),
        )

    await brain.complete_structured(request)
    assert ObservedNewApiAdapter.requested_models == ["model-v1", "model-v2"]

    async with SessionLocal() as session:
        rows = list(
            (
                await session.scalars(
                    select(AIInvocation)
                    .where(AIInvocation.tenant_id == principal.tenant_id)
                    .order_by(AIInvocation.started_at)
                )
            ).all()
        )
        assert len(rows) == 2
        assert all(item.success is True for item in rows)
        assert [item.requested_model for item in rows] == ["model-v1", "model-v2"]
        assert rows[0].total_tokens == 12
        assert rows[0].cost_amount == Decimal("0.00120000")
        assert rows[0].metadata_payload == {"production_order_id": "order-1"}
        page = await list_ai_invocations(session, tenant_id=principal.tenant_id)
        assert page.summary.request_count == 2
        assert page.summary.total_tokens == 24
        assert page.summary.reported_cost == Decimal("0.00240000")
