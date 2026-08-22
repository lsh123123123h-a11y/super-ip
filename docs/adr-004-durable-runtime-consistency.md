# ADR-004：持久化步骤执行、精确版本与 fencing

状态：已接受（2026-08-22）

## 决策

1. `AgentStepExecution` 是每个 PlanStep attempt 的权威运行态；`AgentEvent` 仅作审计。
2. PlanVersion 创建时固定 Capability 与 Evaluator 版本；Workflow、Provider Adapter、External Executor 和 Brain 路由分别在其控制记录创建时固定。
3. AgentStepExecution、AgentOperation、WorkflowRun 均采用短事务 claim、heartbeat、lease 和单调 fence token。外部调用不持有聚合根行锁，写回必须验证 owner + fence。
4. DAG 每轮并发执行 ready set；依赖边保存精确 ArtifactVersion 引用。
5. Outbox 使用版本化 envelope、指数退避与死信；消费者保存去重状态。由于崩溃可发生在副作用完成与确认之间，业务端仍必须幂等并使用 fencing。
6. 跨租户聚合所有权由 `(tenant_id, id)` 复合约束落到 PostgreSQL。素材只保存稳定 storage locator，Provider 专属路径由 staging adapter 负责。

## 后果

部署新实现版本不会改变已创建任务的含义；租约接管后的迟到结果会被丢弃；删除或缺失事件历史不影响任务恢复。旧的 `harness` 执行类型、`bind_executor` 别名、`cancelled` 拼写和 `failed_retryable` 运行态不再进入新代码路径。
