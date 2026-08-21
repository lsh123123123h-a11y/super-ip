from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluationAction(str, Enum):
    accept = "accept"
    rework = "rework"
    replan = "replan"
    manual = "manual"


class EvaluatorDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal["agent.evaluator.v1"] = "agent.evaluator.v1"
    key: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    description: str = ""


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    action: EvaluationAction
    score_payload: dict[str, Any] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    feedback: str = ""

    @model_validator(mode="after")
    def validate_action(self) -> "EvaluationResult":
        if self.passed and self.action != EvaluationAction.accept:
            raise ValueError("通过的评价必须使用 accept")
        if not self.passed and self.action == EvaluationAction.accept:
            raise ValueError("未通过的评价不能使用 accept")
        return self
