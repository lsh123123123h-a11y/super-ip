from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestration import WorkflowRun
from app.schemas.workflows import DigitalHumanRenderRequest
from app.services.provider_registry import ProviderRegistry
from app.services.workflow_service import create_capability_workflow


async def create_avatar_workflow(
    session: AsyncSession,
    *,
    owner_id: str,
    tenant_id: str = "local-tenant",
    idempotency_key: str,
    payload: DigitalHumanRenderRequest,
    production_order_id: str | None = None,
    plan_version_id: str | None = None,
    provider_registry: ProviderRegistry | None = None,
    commit: bool = True,
) -> tuple[WorkflowRun, bool]:
    return await create_capability_workflow(
        session,
        owner_id=owner_id,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        task_type="digital_human.render",
        capability="avatar.render",
        input_payload=payload.model_dump(mode="json"),
        requested_provider=payload.provider,
        requested_execution=payload.execution_mode,
        production_order_id=production_order_id,
        plan_version_id=plan_version_id,
        provider_registry=provider_registry,
        commit=commit,
    )
