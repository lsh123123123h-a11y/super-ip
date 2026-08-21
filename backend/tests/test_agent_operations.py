from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agent.operations import ExecutionPolicy, ExecutorDefinition
from app.agent.contracts import CapabilityOutcome, OutcomeStatus
from app.agent.executor import AgentExecutionResult
from app.executors.registry import ExecutorRegistry


class FakeExecutor:
    async def start(self, request):
        raise NotImplementedError

    async def resume(self, execution_id):
        raise NotImplementedError

    async def interrupt(self, execution_id):
        return None

    async def resolve_approval(self, execution_id, request_id, decision):
        return None

    async def collect_result(self, execution_id):
        return {}


def test_execution_policy_rejects_reservation_above_budget() -> None:
    with pytest.raises(ValidationError, match="预算预留"):
        ExecutionPolicy(
            budget_limit=Decimal("1.00"),
            budget_reserve=Decimal("1.01"),
        )


def test_executor_registry_separates_known_and_installed_executors() -> None:
    registry = ExecutorRegistry()
    known = ExecutorDefinition(
        key="harness.example",
        version="1.0.0",
        label="示例长任务执行器",
        supported_operations=["content.research"],
    )
    installed = ExecutorDefinition(
        key="harness.installed",
        version="1.0.0",
        label="已安装执行器",
        supported_operations=["content.research"],
    )
    registry.register(known)
    registry.register(installed, FakeExecutor())

    assert registry.executor("harness.example") is None
    assert {item.key for item in registry.installed_catalog()} == {"harness.installed"}
    assert registry.select_for("content.research") == "harness.installed"
    with pytest.raises(ValueError, match="重复注册"):
        registry.register(known)


def test_completed_executor_result_rejects_non_terminal_outcome() -> None:
    with pytest.raises(ValidationError, match="终态"):
        AgentExecutionResult(
            outcome=CapabilityOutcome(status=OutcomeStatus.waiting)
        )
