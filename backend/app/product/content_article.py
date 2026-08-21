from typing import Any

from app.agent.contracts import AgentIntentSpec, AgentPlanSpec, PlanStepSpec
from app.product.base import AssetInputDefinition
from app.product.registry import ProductRegistry
from app.schemas.agent import ProductionOrderCreate


class ContentArticleProduct:
    key = "content.article"
    label = "内容文章"
    asset_inputs: tuple[AssetInputDefinition, ...] = ()

    def build_intent(self, payload: ProductionOrderCreate) -> AgentIntentSpec:
        inputs = payload.inputs
        supplied = [
            key
            for key in ("topic", "source_material", "reference_content")
            if inputs.get(key)
        ]
        return AgentIntentSpec(
            goal=payload.intent_text.strip(),
            deliverable=str(inputs.get("deliverable") or "可发布的内容文章"),
            target_platforms=list(inputs.get("target_platforms") or ["公众号"]),
            supplied_inputs=supplied,
            constraints=dict(inputs.get("constraints") or {}),
            assumptions=["外部发布属于高风险副作用，默认不自动执行"],
            confidence=0.82 if supplied else 0.72,
        )

    def build_fallback_plan(
        self,
        payload: ProductionOrderCreate,
        intent: AgentIntentSpec,
        *,
        available_capabilities: set[str],
    ) -> AgentPlanSpec:
        required = {
            "agent.intent.normalize",
            "content.strategy",
            "content.generate",
        }
        missing = sorted(required - available_capabilities)
        if missing:
            raise ValueError(
                "内容文章产品缺少可执行能力："
                + "、".join(missing)
                + "；请先配置 Brain 模型网关或安装对应能力实现"
            )
        return AgentPlanSpec(
            goal=f"完成：{intent.deliverable}",
            steps=[
                PlanStepSpec(
                    key="intent.normalize",
                    capability="agent.intent.normalize",
                    expected_artifact="intent_spec",
                    evaluator="intent_completeness_v1",
                ),
                PlanStepSpec(
                    key="strategy.generate",
                    capability="content.strategy",
                    depends_on=["intent.normalize"],
                    expected_artifact="strategy_proposal",
                    evaluator="content_strategy_quality_v1",
                    checkpoint="policy",
                ),
                PlanStepSpec(
                    key="article.generate",
                    capability="content.generate",
                    depends_on=["strategy.generate"],
                    expected_artifact="content_draft",
                    evaluator="content_draft_quality_v1",
                    checkpoint="final",
                ),
            ],
            max_auto_rework=payload.max_auto_rework,
            planner={"kind": "template", "version": "content-article-v1"},
        )

    def planner_context(self, payload: ProductionOrderCreate) -> dict[str, Any]:
        return {
            "product": self.key,
            "automation_mode": payload.automation_mode,
            "checkpoint_policy": payload.checkpoint_policy,
            "max_auto_rework": payload.max_auto_rework,
        }

    def validate_resume_inputs(self, inputs: dict[str, Any]) -> None:
        return None


def register_content_article_product(registry: ProductRegistry) -> None:
    registry.register(ContentArticleProduct())
