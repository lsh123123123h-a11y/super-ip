from pathlib import Path

import pytest
from pydantic import BaseModel

from app.agent.operations import ExecutorDefinition
from app.core.config import Settings
from app.core.versioning import version_sort_key
from app.executors.registry import ExecutorRegistry
from app.models.orchestration import WorkflowRun, WorkflowStatus
from app.services.storage_service import AssetLocator, ProviderAssetStager
from app.services.workflow_transitions import (
    InvalidWorkflowTransition,
    transition_workflow,
)
from app.workflows.base import WorkflowDefinition
from app.workflows.registry import WorkflowRegistry


class _WorkflowInput(BaseModel):
    value: str


class _Handler:
    async def run(self, context):
        return None

    async def fail(self, context, exc):
        return None

    async def cancel(self, context):
        return None


def test_workflow_and_executor_registries_resolve_exact_versions() -> None:
    workflows = WorkflowRegistry()
    executors = ExecutorRegistry()
    for version in ("1.0.0", "2.0.0"):
        workflows.register(
            WorkflowDefinition(
                task_type="example.workflow",
                capability="example.run",
                version=version,
                input_model=_WorkflowInput,
                steps=(),
                handler=_Handler(),
            )
        )
        executors.register(
            ExecutorDefinition(
                key="example.executor",
                version=version,
                label=version,
            )
        )

    assert workflows.resolve("example.workflow").version == "2.0.0"
    assert workflows.resolve("example.workflow", "1.0.0").version == "1.0.0"
    assert executors.definition("example.executor").version == "2.0.0"
    assert executors.definition("example.executor", "1.0.0").version == "1.0.0"


def test_semver_default_prefers_stable_over_prerelease() -> None:
    assert version_sort_key("2.0.0") > version_sort_key("2.0.0-rc.1")
    assert version_sort_key("2.0.0-rc.10") > version_sort_key("2.0.0-rc.2")


def test_provider_staging_owns_duix_path_translation(tmp_path: Path) -> None:
    key = "tenant/t1/assets/example.wav"
    target = tmp_path / key
    target.parent.mkdir(parents=True)
    target.write_bytes(b"audio")
    stager = ProviderAssetStager(
        Settings(
            asset_storage_root=tmp_path,
            duix_shared_data_root=tmp_path / "duix",
            duix_container_data_root="/provider/data",
        )
    )

    locator = AssetLocator("local", key).as_uri()

    assert stager.stage("duix", locator) == "/provider/data/tenant/t1/assets/example.wav"
    assert stager.stage("opentalking", locator) == str(target.resolve())


def test_workflow_transition_rejects_terminal_reentry() -> None:
    workflow = WorkflowRun(
        owner_id="owner",
        task_type="example",
        capability="example.run",
        idempotency_key="key",
        input_payload={},
        status=WorkflowStatus.succeeded,
    )

    with pytest.raises(InvalidWorkflowTransition):
        transition_workflow(workflow, WorkflowStatus.running)
