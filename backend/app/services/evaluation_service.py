from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import CapabilityOutcome, PlanStepSpec
from app.agent.evaluation import EvaluationResult
from app.evaluators.base import EvaluationContext
from app.evaluators.registry import get_evaluator_registry
from app.models.agent import (
    AgentRun,
    Artifact,
    ArtifactVersion,
    PlanVersion,
    ProductionOrder,
    QualityEvaluation,
)


class EvaluatorUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class EvaluationExecution:
    record: QualityEvaluation | None
    result: EvaluationResult
    artifact_version: ArtifactVersion | None


async def _latest_artifact_version(
    session: AsyncSession,
    *,
    order: ProductionOrder,
    plan: PlanVersion,
    artifact_key: str,
) -> ArtifactVersion | None:
    return await session.scalar(
        select(ArtifactVersion)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(
            Artifact.production_order_id == order.id,
            Artifact.artifact_key == artifact_key,
            ArtifactVersion.plan_version_id == plan.id,
        )
        .order_by(ArtifactVersion.version.desc())
        .limit(1)
    )


async def evaluate_step(
    session: AsyncSession,
    *,
    order: ProductionOrder,
    run: AgentRun,
    plan: PlanVersion,
    step: PlanStepSpec,
    outcome: CapabilityOutcome,
    artifact_version: ArtifactVersion | None = None,
) -> EvaluationExecution:
    registration = get_evaluator_registry().resolve(step.evaluator)
    if registration is None:
        raise EvaluatorUnavailableError(f"评价器尚未安装：{step.evaluator}")
    artifact_version = artifact_version or await _latest_artifact_version(
        session,
        order=order,
        plan=plan,
        artifact_key=step.expected_artifact,
    )
    result = await registration.evaluator.evaluate(
        EvaluationContext(
            order=order,
            run=run,
            plan=plan,
            step=step,
            outcome=outcome,
            artifact_version=artifact_version,
        )
    )
    if artifact_version is None:
        return EvaluationExecution(
            record=None,
            result=result,
            artifact_version=None,
        )
    record = QualityEvaluation(
        tenant_id=order.tenant_id,
        artifact_version_id=artifact_version.id,
        evaluator_key=registration.definition.key,
        evaluator_version=registration.definition.version,
        passed=result.passed,
        score_payload=result.score_payload,
        issue_payload=result.issues,
    )
    session.add(record)
    await session.flush()
    return EvaluationExecution(
        record=record,
        result=result,
        artifact_version=artifact_version,
    )
