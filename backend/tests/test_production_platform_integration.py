import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.auth import PrincipalResolver, service_secret_digest
from app.core.config import Settings
from app.core.database import SessionLocal, tenant_session
from app.core.principal import Principal
from app.models.agent import ProductionOrder, Project
from app.models.assets import Asset
from app.models.ai_provider import AIProviderConfig
from app.models.identity import Membership, Role, ServicePrincipal
from app.models.metering import LedgerEntry, UsageFact
from app.services.authorization_service import AuthorizationService, permissions_for_role
from app.services.identity_service import ensure_principal_records
from app.services.metering_service import (
    BudgetExceededError,
    MeteringConflictError,
    MeteringService,
    QuotaExceededError,
    UsageReport,
)
from starlette.requests import Request


pytestmark = [
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="需要迁移后的隔离 PostgreSQL 测试库",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


def service_request(credential: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/projects",
            "headers": [(b"authorization", f"Service {credential}".encode())],
        }
    )


async def create_dev_principal(prefix: str) -> Principal:
    suffix = uuid.uuid4().hex[:10]
    principal = Principal(
        tenant_id=f"{prefix}-tenant-{suffix}",
        user_id=f"{prefix}-user-{suffix}",
    )
    async with SessionLocal() as session:
        await ensure_principal_records(session, principal)
        await session.commit()
    return principal


async def test_runtime_database_role_cannot_bypass_rls_and_claim_indexes_exist() -> None:
    async with SessionLocal() as session:
        role = (
            await session.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
        assert role.current_user != "xingliu"
        assert role.rolsuper is False
        assert role.rolbypassrls is False
        index_names = set(
            (
                await session.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public'"
                    )
                )
            ).all()
        )
    assert {
        "ix_agent_operations_claim",
        "ix_agent_step_executions_claim",
        "ix_workflow_runs_claim",
        "ix_outbox_events_publish_claim",
        "ix_consumed_events_recovery",
        "ix_tenant_quotas_lookup",
        "ix_price_books_effective",
    } <= index_names


async def test_rls_blocks_missing_where_and_system_worker_context_can_recover() -> None:
    tenant_a = await create_dev_principal("rls-a")
    tenant_b = await create_dev_principal("rls-b")
    async with SessionLocal() as session:
        project_a = Project(
            tenant_id=tenant_a.tenant_id,
            created_by_user_id=tenant_a.user_id,
            name="Tenant A",
            goal="A",
        )
        project_b = Project(
            tenant_id=tenant_b.tenant_id,
            created_by_user_id=tenant_b.user_id,
            name="Tenant B",
            goal="B",
        )
        session.add_all([project_a, project_b])
        await session.flush()
        order_a = ProductionOrder(
            tenant_id=tenant_a.tenant_id,
            project_id=project_a.id,
            created_by_user_id=tenant_a.user_id,
            title="A order",
            intent_text="A",
            request_hash=uuid.uuid4().hex,
            idempotency_key=f"order-{uuid.uuid4().hex}",
        )
        order_b = ProductionOrder(
            tenant_id=tenant_b.tenant_id,
            project_id=project_b.id,
            created_by_user_id=tenant_b.user_id,
            title="B order",
            intent_text="B",
            request_hash=uuid.uuid4().hex,
            idempotency_key=f"order-{uuid.uuid4().hex}",
        )
        asset_a = Asset(
            tenant_id=tenant_a.tenant_id,
            project_id=project_a.id,
            created_by_user_id=tenant_a.user_id,
            file_name="a.wav",
            media_type="audio/wav",
            size_bytes=1,
            storage_key=f"tenant/{tenant_a.tenant_id}/a.wav",
            storage_backend="local",
        )
        asset_b = Asset(
            tenant_id=tenant_b.tenant_id,
            project_id=project_b.id,
            created_by_user_id=tenant_b.user_id,
            file_name="b.wav",
            media_type="audio/wav",
            size_bytes=1,
            storage_key=f"tenant/{tenant_b.tenant_id}/b.wav",
            storage_backend="local",
        )
        ai_a = AIProviderConfig(
            tenant_id=tenant_a.tenant_id,
            name="A provider",
            base_url="https://a.example",
            secret_ciphertext="encrypted-a",
            default_model="a-model",
            created_by_user_id=tenant_a.user_id,
            updated_by_user_id=tenant_a.user_id,
        )
        ai_b = AIProviderConfig(
            tenant_id=tenant_b.tenant_id,
            name="B provider",
            base_url="https://b.example",
            secret_ciphertext="encrypted-b",
            default_model="b-model",
            created_by_user_id=tenant_b.user_id,
            updated_by_user_id=tenant_b.user_id,
        )
        session.add_all([order_a, order_b, asset_a, asset_b, ai_a, ai_b])
        await session.commit()
        project_a_id, project_b_id = project_a.id, project_b.id
        order_a_id, order_b_id = order_a.id, order_b.id
        asset_a_id, asset_b_id = asset_a.id, asset_b.id
        ai_a_id, ai_b_id = ai_a.id, ai_b.id

    async with tenant_session(tenant_a.tenant_id) as session:
        rows = list((await session.scalars(select(Project))).all())
        assert project_a_id in {row.id for row in rows}
        assert project_b_id not in {row.id for row in rows}
        assert await session.get(Project, project_b_id) is None
        assert await session.get(ProductionOrder, order_a_id) is not None
        assert await session.get(ProductionOrder, order_b_id) is None
        assert await session.get(Asset, asset_a_id) is not None
        assert await session.get(Asset, asset_b_id) is None
        assert await session.get(AIProviderConfig, ai_a_id) is not None
        assert await session.get(AIProviderConfig, ai_b_id) is None

    async with tenant_session(tenant_b.tenant_id) as session:
        assert await session.get(Project, project_a_id) is None
        assert await session.get(Project, project_b_id) is not None

    async with SessionLocal() as session:
        # Worker/system sessions explicitly set app.system_context=on and retain
        # access needed for lease recovery across tenants.
        assert await session.get(Project, project_a_id) is not None
        assert await session.get(Project, project_b_id) is not None


async def test_viewer_admin_and_service_principal_permissions_are_database_backed() -> None:
    principal = await create_dev_principal("authz")
    settings = Settings(_env_file=None, service_principal_pepper="test-pepper")
    secret = "service-secret-value"
    async with SessionLocal() as session:
        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == principal.tenant_id,
                Membership.user_id == principal.user_id,
            )
        )
        viewer = await session.scalar(select(Role).where(Role.key == "viewer"))
        assert membership is not None and viewer is not None
        membership.role = "viewer"
        membership.role_id = viewer.id
        service = ServicePrincipal(
            tenant_id=principal.tenant_id,
            client_id=f"sp_{uuid.uuid4().hex[:16]}",
            name="Limited worker",
            secret_digest=service_secret_digest(secret, settings.service_principal_pepper),
            permissions=["project.read"],
            created_by_user_id=principal.user_id,
        )
        session.add(service)
        await session.commit()
        permissions = await permissions_for_role(session, membership.role_id, membership.role)
        viewer_principal = Principal(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            roles=("viewer",),
            permissions=permissions,
        )
        assert AuthorizationService.require(viewer_principal, "project.read")
        with pytest.raises(Exception) as denied:
            AuthorizationService.require(viewer_principal, "ai_provider.manage")
        assert getattr(denied.value, "status_code", None) == 403
        client_id = service.client_id

    resolver = PrincipalResolver(settings)
    async with SessionLocal() as session:
        service_principal = await resolver.resolve(
            service_request(f"{client_id}.{secret}"), session
        )
    assert service_principal.auth_type == "service"
    assert service_principal.permissions == frozenset({"project.read"})
    with pytest.raises(Exception) as denied:
        AuthorizationService.require(service_principal, "production_order.control")
    assert getattr(denied.value, "status_code", None) == 403


async def test_metering_quota_budget_version_pinning_dedupe_release_and_refund() -> None:
    principal = await create_dev_principal("meter")
    service = MeteringService()
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        project = Project(
            tenant_id=principal.tenant_id,
            created_by_user_id=principal.user_id,
            name="Metering Project",
            goal="meter",
        )
        session.add(project)
        await session.flush()
        order = ProductionOrder(
            tenant_id=principal.tenant_id,
            project_id=project.id,
            created_by_user_id=principal.user_id,
            title="Budgeted order",
            intent_text="meter",
            request_hash=uuid.uuid4().hex,
            idempotency_key=f"order-{uuid.uuid4().hex}",
            budget_limit=Decimal("5"),
        )
        low_budget_order = ProductionOrder(
            tenant_id=principal.tenant_id,
            project_id=project.id,
            created_by_user_id=principal.user_id,
            title="Low budget order",
            intent_text="meter",
            request_hash=uuid.uuid4().hex,
            idempotency_key=f"order-{uuid.uuid4().hex}",
            budget_limit=Decimal("1"),
        )
        session.add_all([order, low_budget_order])
        await session.commit()
        order_id, low_budget_order_id = order.id, low_budget_order.id

    async with SessionLocal() as session:
        book_v1 = await service.create_price_book(
            session,
            tenant_id=principal.tenant_id,
            name="v1",
            currency="CREDIT",
            effective_from=now - timedelta(minutes=1),
            created_by_user_id=principal.user_id,
            rules=[
                {"metric": "llm.input_tokens", "unit": "token", "unit_price": "1"},
                {"metric": "llm.output_tokens", "unit": "token", "unit_price": "2"},
            ],
        )
        await service.set_quota(
            session,
            tenant_id=principal.tenant_id,
            metric="llm.input_tokens",
            period="month",
            hard_limit=Decimal("5"),
            soft_limit=Decimal("4"),
            moment=now,
        )
        reservation = await service.reserve(
            session,
            tenant_id=principal.tenant_id,
            metric="llm.input_tokens",
            quantity=Decimal("4"),
            unit="token",
            idempotency_key=f"reserve-{uuid.uuid4().hex}",
            production_order_id=order_id,
            moment=now,
        )
        assert reservation.price_book_version == book_v1.version
        await service.create_price_book(
            session,
            tenant_id=principal.tenant_id,
            name="v2-future-history",
            currency="CREDIT",
            effective_from=now,
            created_by_user_id=principal.user_id,
            rules=[
                {"metric": "llm.input_tokens", "unit": "token", "unit_price": "10"},
                {"metric": "llm.output_tokens", "unit": "token", "unit_price": "20"},
            ],
        )
        report = UsageReport(
            tenant_id=principal.tenant_id,
            source_type="test_execution",
            source_id=f"execution-{uuid.uuid4().hex}",
            metric="llm.input_tokens",
            quantity=Decimal("3"),
            unit="token",
            dedupe_key=f"usage-{uuid.uuid4().hex}",
            occurred_at=now,
        )
        fact, debit = await service.settle(
            session,
            reservation_id=reservation.id,
            report=report,
            idempotency_key=f"settle-{uuid.uuid4().hex}",
        )
        assert debit is not None
        assert debit.amount == Decimal("3.00000000")
        assert debit.price_book_version == book_v1.version
        duplicate_fact, duplicate_debit = await service.settle(
            session,
            reservation_id=reservation.id,
            report=report,
            idempotency_key=debit.idempotency_key,
        )
        assert duplicate_fact.id == fact.id
        assert duplicate_debit and duplicate_debit.id == debit.id

        with pytest.raises(MeteringConflictError):
            await service.reporter.record(
                session,
                replace(report, quantity=Decimal("4")),
            )

        refund = await service.refund(
            session,
            tenant_id=principal.tenant_id,
            ledger_entry_id=debit.id,
            idempotency_key=f"refund-{uuid.uuid4().hex}",
            user_id=principal.user_id,
            note="test refund",
        )
        assert refund.amount == -debit.amount
        assert refund.reverses_entry_id == debit.id

        with pytest.raises(QuotaExceededError):
            await service.reserve(
                session,
                tenant_id=principal.tenant_id,
                metric="llm.input_tokens",
                quantity=Decimal("3"),
                unit="token",
                idempotency_key=f"quota-reject-{uuid.uuid4().hex}",
                production_order_id=order_id,
                moment=now,
            )
        await session.rollback()

        with pytest.raises(BudgetExceededError):
            await service.reserve(
                session,
                tenant_id=principal.tenant_id,
                metric="llm.output_tokens",
                quantity=Decimal("1"),
                unit="token",
                idempotency_key=f"budget-reject-{uuid.uuid4().hex}",
                production_order_id=low_budget_order_id,
                moment=now - timedelta(seconds=1),
            )
        await session.rollback()

        failed_reservation = await service.reserve(
            session,
            tenant_id=principal.tenant_id,
            metric="llm.output_tokens",
            quantity=Decimal("1"),
            unit="token",
            idempotency_key=f"failed-task-{uuid.uuid4().hex}",
            production_order_id=order_id,
            moment=now - timedelta(seconds=1),
        )
        await service.release(
            session,
            tenant_id=principal.tenant_id,
            reservation_id=failed_reservation.id,
            idempotency_key=f"release-{failed_reservation.id}",
        )
        failed_debits = list(
            (
                await session.scalars(
                    select(LedgerEntry).where(
                        LedgerEntry.source_id == failed_reservation.id,
                        LedgerEntry.entry_type == "debit",
                    )
                )
            ).all()
        )
        assert failed_debits == []

        debit.note = "attempted mutation"
        with pytest.raises(DBAPIError):
            await session.commit()
        await session.rollback()


async def test_ledger_rls_hides_other_tenants() -> None:
    tenant_a = await create_dev_principal("ledger-a")
    tenant_b = await create_dev_principal("ledger-b")
    service = MeteringService()
    async with SessionLocal() as session:
        entry_a = await service.adjustment(
            session,
            tenant_id=tenant_a.tenant_id,
            amount=Decimal("1"),
            currency="CREDIT",
            idempotency_key=f"adjust-{uuid.uuid4().hex}",
            user_id=tenant_a.user_id,
            note="A",
        )
        entry_b = await service.adjustment(
            session,
            tenant_id=tenant_b.tenant_id,
            amount=Decimal("1"),
            currency="CREDIT",
            idempotency_key=f"adjust-{uuid.uuid4().hex}",
            user_id=tenant_b.user_id,
            note="B",
        )
        entry_a_id, entry_b_id = entry_a.id, entry_b.id

    async with tenant_session(tenant_a.tenant_id) as session:
        visible = {row.id for row in (await session.scalars(select(LedgerEntry))).all()}
        assert entry_a_id in visible
        assert entry_b_id not in visible

    async with tenant_session(tenant_b.tenant_id) as session:
        visible = {row.id for row in (await session.scalars(select(LedgerEntry))).all()}
        assert entry_b_id in visible
        assert entry_a_id not in visible
