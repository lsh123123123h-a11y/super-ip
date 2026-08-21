import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import Principal
from app.agent.operations import AgentOperationStatus
from app.models.agent import (
    AgentEvent,
    AgentOperation,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVersion,
    ArtifactVersionStatus,
    ContentItem,
    DecisionRequest,
    DecisionStatus,
    IPProfileSnapshot,
    OutboxEvent,
    PlanVersion,
    ProductionOrder,
    ProductionOrderStatus,
    Project,
)
from app.models.business import IPProfile
from app.models.assets import Asset, AssetRef
from app.schemas.agent import (
    ArtifactVersionRead,
    ProductionOrderCreate,
    ProductionOrderInputsUpdate,
    ProductionOrderOverview,
    ResolveDecisionRequest,
)
from app.product.registry import get_product_registry
from app.services.agent_operation_service import stage_planning_operation
from app.services.identity_service import ensure_principal_records


def _request_hash(payload: ProductionOrderCreate) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _production_order_request(
    order: ProductionOrder,
    inputs: dict[str, Any],
) -> ProductionOrderCreate:
    return ProductionOrderCreate(
        project_id=order.project_id,
        product_key=str(
            (inputs.get("_product_key") or "digital_human.video")
        ),
        title=order.title,
        intent_text=order.intent_text,
        automation_mode=order.automation_mode,
        checkpoint_policy=order.checkpoint_policy,
        external_side_effect_policy=order.external_side_effect_policy,
        budget_limit=order.budget_limit,
        max_auto_rework=order.max_auto_rework,
        content_item_id=order.content_item_id,
        inputs=inputs,
    )


async def create_project(
    session: AsyncSession,
    *,
    principal: Principal,
    name: str,
    goal: str,
    settings_payload: dict[str, Any],
) -> Project:
    await ensure_principal_records(session, principal)
    project = Project(
        tenant_id=principal.tenant_id,
        created_by_user_id=principal.user_id,
        name=name,
        goal=goal,
        settings_payload=settings_payload,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def list_projects(session: AsyncSession, principal: Principal) -> list[Project]:
    result = await session.execute(
        select(Project)
        .where(Project.tenant_id == principal.tenant_id)
        .order_by(Project.updated_at.desc())
    )
    return list(result.scalars())


async def get_project(session: AsyncSession, principal: Principal, project_id: str) -> Project:
    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == principal.tenant_id)
    )
    if project is None:
        raise LookupError(project_id)
    return project


async def _snapshot_ip_profile(
    session: AsyncSession,
    principal: Principal,
    ip_profile_id: str | None,
) -> IPProfileSnapshot | None:
    if not ip_profile_id:
        return None
    profile = await session.scalar(
        select(IPProfile).where(IPProfile.id == ip_profile_id, IPProfile.owner_id == principal.user_id)
    )
    if profile is None:
        raise LookupError(ip_profile_id)
    existing = await session.scalar(
        select(IPProfileSnapshot).where(
            IPProfileSnapshot.tenant_id == principal.tenant_id,
            IPProfileSnapshot.ip_profile_id == profile.id,
            IPProfileSnapshot.profile_version == profile.version,
        )
    )
    if existing:
        return existing
    snapshot = IPProfileSnapshot(
        tenant_id=principal.tenant_id,
        ip_profile_id=profile.id,
        profile_version=profile.version,
        snapshot_payload={
            "name": profile.name,
            "promise": profile.promise,
            "audience": profile.audience,
            "offer": profile.offer,
            "voice": profile.voice,
            "evidence": profile.evidence,
            "boundary": profile.boundary,
        },
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def create_production_order(
    session: AsyncSession,
    *,
    principal: Principal,
    idempotency_key: str,
    payload: ProductionOrderCreate,
) -> tuple[ProductionOrderOverview, bool]:
    await ensure_principal_records(session, principal)
    product = get_product_registry().require(payload.product_key)
    request_hash = _request_hash(payload)
    existing = await session.scalar(
        select(ProductionOrder).where(
            ProductionOrder.tenant_id == principal.tenant_id,
            ProductionOrder.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise ValueError("同一 Idempotency-Key 不能提交不同的生产请求")
        return await get_production_order_overview(session, principal, existing.id), False

    project = await get_project(session, principal, payload.project_id)
    snapshot = await _snapshot_ip_profile(session, principal, payload.ip_profile_id)
    content_item: ContentItem | None = None
    if payload.content_item_id:
        content_item = await session.scalar(
            select(ContentItem).where(
                ContentItem.id == payload.content_item_id,
                ContentItem.tenant_id == principal.tenant_id,
                ContentItem.project_id == project.id,
            )
        )
        if content_item is None:
            raise LookupError(payload.content_item_id)
    else:
        content_item = ContentItem(
            tenant_id=principal.tenant_id,
            project_id=project.id,
            title=payload.content_item_title or payload.title or payload.intent_text.strip()[:80],
            content_type=payload.product_key,
        )
        session.add(content_item)
        await session.flush()

    intent = product.build_intent(payload)
    intent_spec = intent.model_dump(mode="json")
    internal_inputs = dict(payload.inputs)
    resolved_assets: list[tuple[Asset, str]] = []
    for asset_input in product.asset_inputs:
        asset_id = payload.inputs.get(asset_input.input_key)
        if not asset_id:
            continue
        asset = await session.scalar(
            select(Asset).where(Asset.id == str(asset_id), Asset.tenant_id == principal.tenant_id)
        )
        if asset is None:
            raise LookupError(str(asset_id))
        if asset.project_id and asset.project_id != project.id:
            raise ValueError("生产单不能引用其他项目的素材")
        if not asset.media_type.startswith(asset_input.media_type_prefix):
            raise ValueError(
                f"{asset_input.input_key} 素材类型必须以"
                f" {asset_input.media_type_prefix} 开头"
            )
        resolved_assets.append((asset, asset_input.role))
        internal_inputs[asset_input.runtime_key] = asset.provider_path
    internal_inputs["_product_key"] = payload.product_key
    order = ProductionOrder(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        content_item_id=content_item.id,
        created_by_user_id=principal.user_id,
        ip_profile_snapshot_id=snapshot.id if snapshot else None,
        title=payload.title or payload.intent_text.strip()[:80],
        intent_text=payload.intent_text.strip(),
        intent_spec={
            **intent_spec,
            "input_asset_ids": [asset.id for asset, _ in resolved_assets],
        },
        request_hash=request_hash,
        idempotency_key=idempotency_key,
        automation_mode=payload.automation_mode,
        checkpoint_policy=payload.checkpoint_policy,
        external_side_effect_policy=payload.external_side_effect_policy,
        status=ProductionOrderStatus.planning,
        budget_limit=payload.budget_limit,
        max_auto_rework=payload.max_auto_rework,
    )
    session.add(order)
    await session.flush()
    for asset, role in resolved_assets:
        session.add(
            AssetRef(
                tenant_id=principal.tenant_id,
                production_order_id=order.id,
                asset_id=asset.id,
                role=role,
            )
        )

    run = AgentRun(
        tenant_id=principal.tenant_id,
        production_order_id=order.id,
        run_number=1,
        status=AgentRunStatus.planning,
        context_snapshot={
            "tenant_id": principal.tenant_id,
            "product_key": payload.product_key,
            "project": {"id": project.id, "name": project.name, "goal": project.goal},
            "ip_profile_snapshot_id": snapshot.id if snapshot else None,
            "intent_spec": intent_spec,
            "inputs": internal_inputs,
        },
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()

    for event_type, event_payload in (
        ("production_order.created", {"automation_mode": payload.automation_mode}),
        ("intent_spec.created", intent_spec),
        ("agent_run.started", {"run_number": 1}),
    ):
        session.add(
            AgentEvent(
                tenant_id=principal.tenant_id,
                production_order_id=order.id,
                agent_run_id=run.id,
                event_type=event_type,
                payload=event_payload,
            )
        )

    await stage_planning_operation(
        session,
        order=order,
        run=run,
        idempotency_key=f"plan:{run.id}:initial",
        reason="initial",
    )

    await session.commit()
    return await get_production_order_overview(session, principal, order.id), True


async def get_production_order(
    session: AsyncSession,
    principal: Principal,
    order_id: str,
) -> ProductionOrder:
    order = await session.scalar(
        select(ProductionOrder).where(
            ProductionOrder.id == order_id,
            ProductionOrder.tenant_id == principal.tenant_id,
        )
    )
    if order is None:
        raise LookupError(order_id)
    return order


async def list_production_orders(
    session: AsyncSession,
    principal: Principal,
    limit: int = 50,
) -> list[ProductionOrder]:
    result = await session.execute(
        select(ProductionOrder)
        .where(ProductionOrder.tenant_id == principal.tenant_id)
        .order_by(ProductionOrder.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def get_production_order_overview(
    session: AsyncSession,
    principal: Principal,
    order_id: str,
) -> ProductionOrderOverview:
    order = await get_production_order(session, principal, order_id)
    run = await session.scalar(
        select(AgentRun)
        .where(AgentRun.production_order_id == order.id, AgentRun.tenant_id == principal.tenant_id)
        .order_by(AgentRun.run_number.desc())
        .limit(1)
    )
    if run is None:
        raise RuntimeError("生产单缺少 AgentRun")
    plan = await session.scalar(
        select(PlanVersion)
        .where(PlanVersion.agent_run_id == run.id, PlanVersion.tenant_id == principal.tenant_id)
        .order_by(PlanVersion.version.desc())
        .limit(1)
    )
    decisions = list(
        (
            await session.execute(
                select(DecisionRequest)
                .where(
                    DecisionRequest.production_order_id == order.id,
                    DecisionRequest.tenant_id == principal.tenant_id,
                )
                .order_by(DecisionRequest.created_at)
            )
        ).scalars()
    )
    artifact_rows = list(
        (
            await session.execute(
                select(ArtifactVersion, Artifact.artifact_key, Artifact.artifact_type)
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(
                    Artifact.production_order_id == order.id,
                    Artifact.tenant_id == principal.tenant_id,
                )
                .order_by(Artifact.created_at, ArtifactVersion.version)
            )
        ).all()
    )
    artifact_versions = [
        ArtifactVersionRead.model_validate(version).model_copy(
            update={"artifact_key": artifact_key, "artifact_type": artifact_type}
        )
        for version, artifact_key, artifact_type in artifact_rows
    ]
    return ProductionOrderOverview(
        order=order,
        agent_run=run,
        plan=plan,
        decisions=decisions,
        artifact_versions=artifact_versions,
    )


async def resolve_decision(
    session: AsyncSession,
    *,
    principal: Principal,
    decision_id: str,
    payload: ResolveDecisionRequest,
) -> ProductionOrderOverview:
    decision = await session.scalar(
        select(DecisionRequest).where(
            DecisionRequest.id == decision_id,
            DecisionRequest.tenant_id == principal.tenant_id,
        )
    )
    if decision is None:
        raise LookupError(decision_id)
    if decision.status != DecisionStatus.pending:
        raise ValueError("该决策请求已经处理")
    valid_options = {str(item.get("key")) for item in decision.options}
    if payload.option_key not in valid_options:
        raise ValueError("决策选项无效")
    if payload.option_key == "open_assets":
        try:
            inputs = ProductionOrderInputsUpdate.model_validate(payload.payload)
        except ValueError as exc:
            raise ValueError("补充素材的决策数据无效") from exc
        return await update_production_order_inputs(
            session,
            principal=principal,
            order_id=decision.production_order_id,
            payload=inputs,
        )

    order = await get_production_order(session, principal, decision.production_order_id)
    run = await session.get(AgentRun, decision.agent_run_id)
    if run is None:
        raise RuntimeError("决策请求缺少 AgentRun")
    now = datetime.now(UTC)
    decision.status = DecisionStatus.resolved
    decision.resolved_option = payload.option_key
    decision.resolution_payload = payload.payload
    decision.resolved_at = now
    session.add(
        AgentEvent(
            tenant_id=principal.tenant_id,
            production_order_id=order.id,
            agent_run_id=run.id,
            event_type="decision.resolved",
            payload={"decision_id": decision.id, "option": payload.option_key, "payload": payload.payload},
        )
    )

    if payload.option_key == "approve_plan":
        order.status = ProductionOrderStatus.queued
        run.status = AgentRunStatus.running
        session.add(
            OutboxEvent(
                tenant_id=principal.tenant_id,
                aggregate_type="production_order",
                aggregate_id=order.id,
                topic="agent.run.requested",
                payload={"production_order_id": order.id, "agent_run_id": run.id},
                dedupe_key=f"agent-run:{run.id}:decision:{decision.id}",
            )
        )
    elif payload.option_key == "request_changes":
        order.status = ProductionOrderStatus.planning
        run.status = AgentRunStatus.planning
        await stage_planning_operation(
            session,
            order=order,
            run=run,
            idempotency_key=f"plan:{run.id}:decision:{decision.id}",
            reason="decision_revision",
            planning_context={
                "source_decision_id": decision.id,
                "change_request": payload.payload,
            },
        )
    elif payload.option_key == "cancel_order":
        order.status = ProductionOrderStatus.canceled
        run.status = AgentRunStatus.canceled
        run.stop_reason = "user_canceled"
        run.finished_at = now

    await session.commit()
    return await get_production_order_overview(session, principal, order.id)


async def update_production_order_inputs(
    session: AsyncSession,
    *,
    principal: Principal,
    order_id: str,
    payload: ProductionOrderInputsUpdate,
) -> ProductionOrderOverview:
    order = await get_production_order(session, principal, order_id)
    if order.status not in {
        ProductionOrderStatus.awaiting_decision,
        ProductionOrderStatus.manual_intervention,
        ProductionOrderStatus.failed_retryable,
    }:
        raise ValueError("当前生产单不能再补充输入")
    run = await session.scalar(
        select(AgentRun)
        .where(
            AgentRun.production_order_id == order.id,
            AgentRun.tenant_id == principal.tenant_id,
        )
        .order_by(AgentRun.run_number.desc())
        .limit(1)
    )
    if run is None:
        raise RuntimeError("生产单缺少 AgentRun")
    current_plan = await session.scalar(
        select(PlanVersion)
        .where(
            PlanVersion.agent_run_id == run.id,
            PlanVersion.tenant_id == principal.tenant_id,
        )
        .order_by(PlanVersion.version.desc())
        .limit(1)
    )
    if current_plan is None:
        raise RuntimeError("生产单缺少 PlanVersion")

    update_values = payload.model_dump(exclude_none=True)
    generic_values = update_values.pop("inputs", {})
    if isinstance(generic_values, dict):
        update_values = {**generic_values, **update_values}
    script = update_values.get("script")
    if isinstance(script, str):
        script = script.strip()
        if not script:
            update_values.pop("script", None)
        else:
            update_values["script"] = script

    context = dict(run.context_snapshot or {})
    inputs = dict(context.get("inputs") or {})
    product_key = str(
        context.get("product_key")
        or inputs.get("_product_key")
        or "digital_human.video"
    )
    product = get_product_registry().require(product_key)
    resolved_assets: list[tuple[Asset, str, str]] = []
    for asset_input in product.asset_inputs:
        asset_id = update_values.get(asset_input.input_key)
        if not asset_id:
            continue
        asset = await session.scalar(
            select(Asset).where(
                Asset.id == str(asset_id),
                Asset.tenant_id == principal.tenant_id,
                Asset.status == "active",
            )
        )
        if asset is None:
            raise LookupError(str(asset_id))
        if asset.project_id and asset.project_id != order.project_id:
            raise ValueError("生产单不能引用其他项目的素材")
        if not asset.media_type.startswith(asset_input.media_type_prefix):
            raise ValueError(
                f"{asset_input.input_key} 素材类型必须以"
                f" {asset_input.media_type_prefix} 开头"
            )
        if not asset.provider_path:
            raise ValueError("素材尚未准备好 Provider 内部引用")
        inputs[asset_input.runtime_key] = asset.provider_path
        resolved_assets.append(
            (asset, asset_input.role, asset_input.input_key)
        )

    inputs.update(update_values)
    inputs["_product_key"] = product_key
    product.validate_resume_inputs(inputs)

    for asset, role, _ in resolved_assets:
        existing_ref = await session.scalar(
            select(AssetRef).where(
                AssetRef.production_order_id == order.id,
                AssetRef.asset_id == asset.id,
                AssetRef.role == role,
            )
        )
        if existing_ref is None:
            session.add(
                AssetRef(
                    tenant_id=principal.tenant_id,
                    production_order_id=order.id,
                    asset_id=asset.id,
                    role=role,
                )
            )

    context["inputs"] = inputs
    context["product_key"] = product_key
    run.context_snapshot = context
    synthetic_request = _production_order_request(order, inputs)
    intent_spec = product.build_intent(synthetic_request).model_dump(mode="json")

    asset_ids = set(order.intent_spec.get("input_asset_ids") or [])
    asset_ids.update(asset.id for asset, _, _ in resolved_assets)
    order.intent_spec = {**intent_spec, "input_asset_ids": sorted(asset_ids)}
    pending_decisions = list(
        (
            await session.execute(
                select(DecisionRequest).where(
                    DecisionRequest.production_order_id == order.id,
                    DecisionRequest.status == DecisionStatus.pending,
                    DecisionRequest.reason_code.in_(
                        ["MISSING_REQUIRED_ASSET", "MISSING_REQUIRED_INPUT"]
                    ),
                )
            )
        ).scalars()
    )
    now = datetime.now(UTC)
    for decision in pending_decisions:
        decision.status = DecisionStatus.resolved
        decision.resolved_option = "open_assets"
        decision.resolution_payload = {
            key: value for key, value in update_values.items() if not key.endswith("_path")
        }
        decision.resolved_at = now

    order.status = ProductionOrderStatus.planning
    run.status = AgentRunStatus.planning
    run.stop_reason = None
    run.finished_at = None
    input_hash = hashlib.sha256(
        json.dumps(update_values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    await stage_planning_operation(
        session,
        order=order,
        run=run,
        idempotency_key=f"plan:{run.id}:inputs:{input_hash}",
        reason="inputs_updated",
        planning_context={"updated_fields": sorted(update_values)},
    )
    session.add(
        AgentEvent(
            tenant_id=principal.tenant_id,
            production_order_id=order.id,
            agent_run_id=run.id,
            event_type="production_order.inputs_supplied",
            payload={
                "fields": sorted(update_values),
                "previous_plan_version_id": current_plan.id,
                "expected_plan_version": current_plan.version + 1,
            },
        )
    )
    await session.commit()
    return await get_production_order_overview(session, principal, order.id)


async def next_artifact_version(session: AsyncSession, artifact_id: str) -> int:
    current = await session.scalar(
        select(func.max(ArtifactVersion.version)).where(ArtifactVersion.artifact_id == artifact_id)
    )
    return int(current or 0) + 1


async def command_production_order(
    session: AsyncSession,
    *,
    principal: Principal,
    order_id: str,
    command: str,
) -> ProductionOrderOverview:
    order = await get_production_order(session, principal, order_id)
    run = await session.scalar(
        select(AgentRun)
        .where(AgentRun.production_order_id == order.id)
        .order_by(AgentRun.run_number.desc())
        .limit(1)
    )
    if run is None:
        raise RuntimeError("生产单缺少 AgentRun")

    if command == "pause":
        if order.status in {
            ProductionOrderStatus.succeeded,
            ProductionOrderStatus.failed_final,
            ProductionOrderStatus.canceled,
        }:
            raise ValueError("当前生产单不能暂停")
        order.status = ProductionOrderStatus.paused
    elif command == "resume":
        if order.status != ProductionOrderStatus.paused:
            raise ValueError("只有已暂停的生产单才能继续")
        latest_plan = await session.scalar(
            select(PlanVersion)
            .where(PlanVersion.agent_run_id == run.id)
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        pending_plan_review = await session.scalar(
            select(DecisionRequest).where(
                DecisionRequest.agent_run_id == run.id,
                DecisionRequest.status == DecisionStatus.pending,
                DecisionRequest.reason_code == "PLAN_REVIEW",
            )
        )
        if latest_plan is None:
            order.status = ProductionOrderStatus.planning
            run.status = AgentRunStatus.planning
            operations = list(
                (
                    await session.execute(
                        select(AgentOperation).where(
                            AgentOperation.agent_run_id == run.id,
                            AgentOperation.status.in_(
                                [
                                    AgentOperationStatus.queued.value,
                                    AgentOperationStatus.waiting.value,
                                    AgentOperationStatus.failed_retryable.value,
                                ]
                            ),
                        )
                    )
                ).scalars()
            )
            for operation in operations:
                operation.next_wakeup_at = datetime.now(UTC)
        elif pending_plan_review is not None:
            order.status = ProductionOrderStatus.awaiting_plan_approval
            run.status = AgentRunStatus.awaiting_decision
        else:
            order.status = ProductionOrderStatus.queued
            run.status = AgentRunStatus.running
            session.add(
                OutboxEvent(
                    tenant_id=principal.tenant_id,
                    aggregate_type="production_order",
                    aggregate_id=order.id,
                    topic="agent.run.requested",
                    payload={"production_order_id": order.id, "agent_run_id": run.id},
                    dedupe_key=f"agent-run:{run.id}:resume:{order.updated_at.isoformat() if order.updated_at else order.id}",
                )
            )
    elif command == "cancel":
        if order.status in {ProductionOrderStatus.succeeded, ProductionOrderStatus.canceled}:
            raise ValueError("当前生产单不能取消")
        latest_plan = await session.scalar(
            select(PlanVersion)
            .where(PlanVersion.agent_run_id == run.id)
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        if latest_plan is None or order.status == ProductionOrderStatus.planning:
            operations = list(
                (
                    await session.execute(
                        select(AgentOperation).where(
                            AgentOperation.agent_run_id == run.id,
                            AgentOperation.status.not_in(
                                [
                                    AgentOperationStatus.succeeded.value,
                                    AgentOperationStatus.failed_final.value,
                                    AgentOperationStatus.canceled.value,
                                ]
                            ),
                        )
                    )
                ).scalars()
            )
            now = datetime.now(UTC)
            for operation in operations:
                operation.status = AgentOperationStatus.canceled.value
                operation.finished_at = now
                operation.lease_owner = None
                operation.lease_expires_at = None
            order.status = ProductionOrderStatus.canceled
            run.status = AgentRunStatus.canceled
            run.stop_reason = "user_canceled"
            run.finished_at = now
        else:
            order.status = ProductionOrderStatus.canceling
            session.add(
                OutboxEvent(
                    tenant_id=principal.tenant_id,
                    aggregate_type="production_order",
                    aggregate_id=order.id,
                    topic="agent.cancel.requested",
                    payload={"production_order_id": order.id, "agent_run_id": run.id},
                    dedupe_key=f"agent-cancel:{run.id}",
                )
            )
    else:
        raise ValueError(f"未知生产单命令：{command}")

    session.add(
        AgentEvent(
            tenant_id=principal.tenant_id,
            production_order_id=order.id,
            agent_run_id=run.id,
            event_type=f"production_order.{command}_requested",
            payload={},
        )
    )
    await session.commit()
    return await get_production_order_overview(session, principal, order.id)


async def list_artifact_versions(
    session: AsyncSession,
    *,
    principal: Principal,
    artifact_id: str,
) -> list[ArtifactVersion]:
    artifact = await session.scalar(
        select(Artifact).where(Artifact.id == artifact_id, Artifact.tenant_id == principal.tenant_id)
    )
    if artifact is None:
        raise LookupError(artifact_id)
    result = await session.execute(
        select(ArtifactVersion)
        .where(
            ArtifactVersion.artifact_id == artifact.id,
            ArtifactVersion.tenant_id == principal.tenant_id,
        )
        .order_by(ArtifactVersion.version)
    )
    return list(result.scalars())


async def review_artifact_version(
    session: AsyncSession,
    *,
    principal: Principal,
    version_id: str,
    action: str,
    note: str,
) -> ArtifactVersion:
    version = await session.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.id == version_id,
            ArtifactVersion.tenant_id == principal.tenant_id,
        )
    )
    if version is None:
        raise LookupError(version_id)
    artifact = await session.scalar(
        select(Artifact).where(
            Artifact.id == version.artifact_id,
            Artifact.tenant_id == principal.tenant_id,
        )
    )
    if artifact is None:
        raise LookupError(version.artifact_id)
    if action == "approve":
        await session.execute(
            ArtifactVersion.__table__.update()
            .where(
                ArtifactVersion.artifact_id == artifact.id,
                ArtifactVersion.id != version.id,
                ArtifactVersion.status == ArtifactVersionStatus.approved,
            )
            .values(status=ArtifactVersionStatus.superseded)
        )
        version.status = ArtifactVersionStatus.approved
        version.approved_at = datetime.now(UTC)
        event_type = "artifact.version.approved"
    elif action == "return":
        version.status = ArtifactVersionStatus.returned
        event_type = "artifact.version.returned"
    else:
        raise ValueError(f"未知审核动作：{action}")
    session.add(
        AgentEvent(
            tenant_id=principal.tenant_id,
            production_order_id=artifact.production_order_id,
            event_type=event_type,
            payload={"artifact_id": artifact.id, "version_id": version.id, "note": note},
        )
    )
    await session.commit()
    await session.refresh(version)
    return version
