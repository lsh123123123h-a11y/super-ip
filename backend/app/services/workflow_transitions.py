from app.models.orchestration import WorkflowRun, WorkflowStatus


class InvalidWorkflowTransition(RuntimeError):
    pass


_ALLOWED: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.queued: {
        WorkflowStatus.running,
        WorkflowStatus.waiting_provider,
        WorkflowStatus.retry_wait,
        WorkflowStatus.failed_final,
        WorkflowStatus.canceling,
        WorkflowStatus.manual_intervention,
    },
    WorkflowStatus.running: {
        WorkflowStatus.waiting_provider,
        WorkflowStatus.retry_wait,
        WorkflowStatus.failed_final,
        WorkflowStatus.succeeded,
        WorkflowStatus.canceling,
        WorkflowStatus.manual_intervention,
    },
    WorkflowStatus.waiting_provider: {
        WorkflowStatus.waiting_provider,
        WorkflowStatus.retry_wait,
        WorkflowStatus.failed_final,
        WorkflowStatus.succeeded,
        WorkflowStatus.canceling,
        WorkflowStatus.manual_intervention,
    },
    WorkflowStatus.retry_wait: {
        WorkflowStatus.queued,
        WorkflowStatus.running,
        WorkflowStatus.waiting_provider,
        WorkflowStatus.retry_wait,
        WorkflowStatus.canceling,
        WorkflowStatus.failed_final,
        WorkflowStatus.manual_intervention,
    },
    WorkflowStatus.canceling: {
        WorkflowStatus.canceled,
        WorkflowStatus.manual_intervention,
    },
}


def transition_workflow(workflow: WorkflowRun, target: WorkflowStatus) -> None:
    current = workflow.status
    if current == target:
        return
    if target == WorkflowStatus.manual_intervention:
        workflow.status = target
        return
    if target not in _ALLOWED.get(current, set()):
        raise InvalidWorkflowTransition(
            f"Workflow 状态不能从 {current.value} 转为 {target.value}"
        )
    workflow.status = target
