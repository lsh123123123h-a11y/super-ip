from types import SimpleNamespace

import pytest

from app.agent.brain import StructuredBrainResponse
from app.agent.contracts import OutcomeStatus, PlanStepSpec
from app.capabilities.base import CapabilityContext
from app.capabilities.avatar_render import AvatarRenderCapability
from app.capabilities.content import (
    ContentGenerateCapability,
    ContentStrategyCapability,
)
from app.product.registry import get_product_registry
from app.schemas.agent import ProductionOrderCreate


class FakeBrain:
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = list(outputs)
        self.requests = []

    async def complete_structured(self, request):
        self.requests.append(request)
        return StructuredBrainResponse(
            output=self.outputs.pop(0),
            model_ref="content-model",
            gateway_ref="new-api",
            usage={"total_tokens": 42},
        )

    async def probe(self):
        return {"ok": True}


class EmptySession:
    async def scalar(self, statement):
        return None


def _context(
    capability: str,
    expected_artifact: str,
    *,
    artifacts: dict | None = None,
) -> CapabilityContext:
    return CapabilityContext(
        session=None,
        order=SimpleNamespace(
            id="order-1",
            intent_spec={"goal": "写一篇面向创业者的 AI 文章"},
        ),
        run=SimpleNamespace(id="run-1"),
        plan=SimpleNamespace(id="plan-1", version=1, goal="完成内容文章"),
        step=PlanStepSpec(
            key=capability,
            capability=capability,
            expected_artifact=expected_artifact,
            evaluator="content_test_v1",
        ),
        inputs={"target_platforms": ["公众号"], "_product_key": "content.article"},
        artifacts=artifacts or {},
    )


@pytest.mark.asyncio
async def test_brain_content_capabilities_pass_artifacts_between_business_steps() -> None:
    brain = FakeBrain(
        [
            {
                "audience": "AI 创业者",
                "angle": "从可执行工作流而非模型参数切入",
                "core_message": "Agent 价值来自闭环执行",
                "hook": "为什么换更大的模型仍然做不完任务？",
                "key_points": ["明确目标", "调用能力", "评价返工"],
                "structure": [{"section": "开头", "purpose": "提出问题"}],
                "tone": "专业直接",
                "risks": ["避免未经核验的数据"],
            },
            {
                "title": "Agent 真正的分水岭不是模型大小",
                "summary": "从运行闭环解释 Agent 产品的核心价值。",
                "body_markdown": "正文" * 80,
                "platform": "公众号",
                "calls_to_action": ["分享你的 Agent 实践"],
                "factual_claims": [],
            },
        ]
    )
    strategy = await ContentStrategyCapability(brain).execute(
        _context("content.strategy", "strategy_proposal")
    )
    assert strategy.status == OutcomeStatus.succeeded
    assert strategy.artifact is not None

    artifacts = {
        "strategy_proposal": {
            "artifact_type": strategy.artifact.artifact_type,
            "version": 1,
            "status": "candidate",
            "content": strategy.artifact.content_payload,
        }
    }
    generated = await ContentGenerateCapability(brain).execute(
        _context("content.generate", "content_draft", artifacts=artifacts)
    )

    assert generated.status == OutcomeStatus.succeeded
    assert generated.artifact is not None
    assert generated.artifact.content_payload["platform"] == "公众号"
    assert brain.requests[1].user_input["artifacts"] == artifacts
    assert "_product_key" not in brain.requests[1].user_input["inputs"]
    assert generated.artifact.lineage_payload["source"] == "brain"


@pytest.mark.asyncio
async def test_content_generate_uses_script_contract_for_digital_human_artifact() -> None:
    brain = FakeBrain(
        [
            {
                "title": "口播脚本",
                "hook": "为什么 Agent 不是一个聊天框？",
                "text": "Agent 的核心是持续推进生产目标，并在执行后评价和返工。",
                "sections": [{"section": "正文", "purpose": "解释运行闭环"}],
                "calls_to_action": [],
                "factual_claims": [],
            }
        ]
    )

    generated = await ContentGenerateCapability(brain).execute(
        _context("content.generate", "script")
    )

    assert generated.status == OutcomeStatus.succeeded
    assert generated.artifact is not None
    assert generated.artifact.artifact_type == "script"
    assert generated.artifact.content_payload["text"].startswith("Agent 的核心")
    assert "text" in brain.requests[0].output_schema["properties"]
    assert "body_markdown" not in brain.requests[0].output_schema["properties"]


@pytest.mark.asyncio
async def test_avatar_capability_accepts_generated_script_artifact() -> None:
    context = _context(
        "avatar.render",
        "avatar_video",
        artifacts={
            "script": {
                "artifact_type": "script",
                "version": 1,
                "status": "candidate",
                "content": {"text": "由 Brain 生成的口播脚本"},
            }
        },
    )
    context.session = EmptySession()

    outcome = await AvatarRenderCapability().execute(context)

    assert outcome.status == OutcomeStatus.awaiting_decision
    assert outcome.decision is not None
    assert "口播脚本" not in outcome.decision.summary
    assert "配音音频" in outcome.decision.summary


def test_content_article_product_is_not_coupled_to_avatar_or_external_executor() -> None:
    product = get_product_registry().require("content.article")
    request = ProductionOrderCreate(
        project_id="project-1",
        product_key="content.article",
        intent_text="为创业者生成一篇 Agent 产品方法论文章",
        automation_mode="automatic",
        inputs={"target_platforms": ["公众号"]},
    )
    plan = product.build_fallback_plan(
        request,
        product.build_intent(request),
        available_capabilities={
            "agent.intent.normalize",
            "content.strategy",
            "content.generate",
        },
    )

    assert [step.capability for step in plan.steps] == [
        "agent.intent.normalize",
        "content.strategy",
        "content.generate",
    ]
    assert all("avatar" not in step.capability for step in plan.steps)
    assert plan.planner["version"] == "content-article-v1"
