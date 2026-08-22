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


def test_plan_contract_rejects_ambiguous_artifact_producers() -> None:
    payload = _plan_payload()
    payload["steps"][1]["expected_artifact"] = "intent_spec"

    with pytest.raises(ValidationError):
        AgentPlanSpec.model_validate(payload)


def test_capability_registry_separates_catalog_from_installed_handlers() -> None:
    registry = get_capability_registry()

    assert registry.definition("content.strategy") is not None
    assert registry.definition("content.strategy").execution_kind == ExecutionKind.inline
    assert registry.handler("avatar.render") is not None
    assert registry.handler("content.strategy") is not None
    assert "content.strategy" in {
        item.key for item in registry.installed_catalog()
    }
    assert registry.resolve("content.strategy").metadata == {
        "requires": ["brain"],
        "model_alias": "reasoning.default",
    }
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


def test_capability_registry_keeps_old_versions_exactly_addressable() -> None:
    registry = CapabilityRegistry()
    for version in ("1.0.0", "2.0.0"):
        registry.register(
            CapabilityDefinition(
                key="example.versioned",
                version=version,
                label=f"示例能力 {version}",
                execution_kind=ExecutionKind.inline,
            )
        )

    assert registry.resolve("example.versioned").definition.version == "2.0.0"
    assert registry.resolve("example.versioned", "1.0.0").definition.version == "1.0.0"
    assert registry.resolve("example.versioned", "3.0.0") is None


def test_external_binding_is_not_installed_until_executor_adapter_exists() -> None:
    registry = CapabilityRegistry()
    definition = CapabilityDefinition(
        key="content.research",
        version="1.0.0",
        label="内容研究",
        execution_kind=ExecutionKind.external,
    )
    registry.register(definition, source="test.catalog")
    assert registry.installed_catalog() == []

    registry.bind_external_executor(
        definition.key,
        "external.research-agent",
        metadata={"allowed_tools": ["web.search"]},
    )

    registration = registry.resolve(definition.key)
    assert registration is not None
    assert registration.external_executor_key == "external.research-agent"
    assert registration.executor_key == "external.research-agent"
    assert registration.metadata["allowed_tools"] == ["web.search"]
    assert registry.installed_catalog() == []


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


def test_generic_worker_does_not_contain_domain_or_provider_state_machine() -> None:
    worker_path = Path(__file__).parents[1] / "app" / "worker.py"
    source = worker_path.read_text(encoding="utf-8").lower()

    assert "avatar" not in source
    assert "duix" not in source
    assert "providerjob" not in source


def test_generic_registries_and_workflow_service_do_not_import_avatar_plugins() -> None:
    app_root = Path(__file__).parents[1] / "app"
    targets = [
        app_root / "services" / "workflow_service.py",
        app_root / "services" / "provider_registry.py",
        app_root / "product" / "planning.py",
    ]
    for target in targets:
        source = target.read_text(encoding="utf-8").lower()
        assert "app.providers.duix" not in source
        assert "app.providers.opentalking" not in source
        assert "digital_human_plan" not in source
        assert "avatar_render" not in source
