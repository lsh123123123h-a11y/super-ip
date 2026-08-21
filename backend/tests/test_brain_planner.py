import pytest

from app.agent.brain import StructuredBrainRequest, StructuredBrainResponse
from app.agent.contracts import AgentIntentSpec, CapabilityDefinition, ExecutionKind
from app.agent.planner import BrainPlanner


class FakeBrain:
    def __init__(self, capability: str = "agent.intent.normalize") -> None:
        self.request: StructuredBrainRequest | None = None
        self.capability = capability

    async def complete_structured(
        self,
        request: StructuredBrainRequest,
    ) -> StructuredBrainResponse:
        self.request = request
        return StructuredBrainResponse(
            output={
                "goal": "完成测试交付",
                "steps": [
                    {
                        "key": "intent",
                        "capability": self.capability,
                        "expected_artifact": "intent_spec",
                        "evaluator": "intent_v1",
                    }
                ],
            },
            model_ref="internal-reasoner",
            gateway_ref="new-api",
        )

    async def probe(self) -> dict:
        return {"ok": True}


@pytest.mark.asyncio
async def test_brain_planner_validates_plan_and_hides_infrastructure() -> None:
    brain = FakeBrain()
    planner = BrainPlanner(brain)
    result = await planner.create_plan(
        intent=AgentIntentSpec(
            goal="测试",
            deliverable="视频",
            confidence=0.8,
        ),
        capabilities=[
            CapabilityDefinition(
                key="agent.intent.normalize",
                version="1.0.0",
                label="目标结构化",
                execution_kind=ExecutionKind.inline,
            )
        ],
    )

    assert result.plan.planner == {
        "kind": "brain",
        "model_ref": "internal-reasoner",
        "gateway_ref": "new-api",
    }
    assert brain.request is not None
    assert brain.request.purpose == "production_plan"
    assert "Provider" in brain.request.system_instruction
    assert brain.request.user_input["capabilities"][0]["key"] == "agent.intent.normalize"


@pytest.mark.asyncio
async def test_brain_planner_rejects_hallucinated_or_uninstalled_capability() -> None:
    planner = BrainPlanner(FakeBrain(capability="content.not-installed"))

    with pytest.raises(ValueError, match="未安装的能力"):
        await planner.create_plan(
            intent=AgentIntentSpec(
                goal="测试",
                deliverable="视频",
                confidence=0.8,
            ),
            capabilities=[
                CapabilityDefinition(
                    key="agent.intent.normalize",
                    version="1.0.0",
                    label="目标结构化",
                    execution_kind=ExecutionKind.inline,
                )
            ],
        )
