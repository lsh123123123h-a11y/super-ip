import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent.contracts import (
    AgentPlanSpec,
    CapabilityDefinition,
    ExecutionKind,
)
from app.capabilities.registry import CapabilityRegistry, get_capability_registry


def _plan_payload() -> dict:
    return {
        "goal": "生成可发布内容",
        "steps": [
            {
                "key": "intent",
                "capability": "agent.intent.normalize",
                "expected_artifact": "intent_spec",
                "evaluator": "intent_v1",
            },
            {
                "key": "render",
                "capability": "avatar.render",
                "depends_on": ["intent"],
                "expected_artifact": "avatar_video",
                "evaluator": "avatar_v1",
            },
        ],
    }


def test_plan_contract_accepts_only_product_level_capabilities() -> None:
    plan = AgentPlanSpec.model_validate(_plan_payload())

    assert [step.key for step in plan.steps] == ["intent", "render"]
    assert plan.contract == "agent.plan.v1"


def test_plan_contract_rejects_infrastructure_selection_fields() -> None:
    payload = _plan_payload()
    payload["steps"][1]["provider"] = "some-provider"

    with pytest.raises(ValidationError):
        AgentPlanSpec.model_validate(payload)


def test_plan_contract_rejects_forward_or_unknown_dependencies() -> None:
    payload = _plan_payload()
    payload["steps"][0]["depends_on"] = ["render"]

    with pytest.raises(ValidationError):
        AgentPlanSpec.model_validate(payload)


def test_capability_registry_separates_catalog_from_installed_handlers() -> None:
    registry = get_capability_registry()

    assert registry.definition("content.strategy") is not None
    assert registry.handler("content.strategy") is None
    assert registry.handler("avatar.render") is not None
    assert "content.strategy" not in {item.key for item in registry.installed_catalog()}
    assert "avatar.render" in {item.key for item in registry.installed_catalog()}


def test_capability_registry_rejects_duplicate_contracts() -> None:
    registry = CapabilityRegistry()
    definition = CapabilityDefinition(
        key="example.run",
        version="1.0.0",
        label="示例能力",
        execution_kind=ExecutionKind.inline,
    )
    registry.register(definition)

    with pytest.raises(ValueError, match="重复注册"):
        registry.register(definition)


def test_agent_runtime_does_not_import_workflows_providers_or_product_plugins() -> None:
    runtime_path = Path(__file__).parents[1] / "app" / "services" / "agent_runtime.py"
    tree = ast.parse(runtime_path.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    forbidden_prefixes = (
        "app.models.orchestration",
        "app.schemas.workflows",
        "app.services.workflow_service",
        "app.providers",
    )

    assert not any(
        module.startswith(prefix)
        for module in imports
        for prefix in forbidden_prefixes
    )
    assert "avatar.render" not in runtime_path.read_text(encoding="utf-8")
