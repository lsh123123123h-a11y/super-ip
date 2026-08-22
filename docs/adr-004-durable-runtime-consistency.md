# ADR-004：持久化步骤执行、精确版本与 fencing

状态：已接受（2026-08-22）

## 决策

1. `AgentStepExecution` 是每个 PlanStep attempt 的权威运行态；`AgentEvent` 仅作审计。
2. PlanVersion 创建时固定 Capability 与 Evaluator 版本；Workflow、Provider Adapter、External Executor 和 Brain 路由分别在其控制记录创建时固定。
3. AgentStepExecution、AgentOperation、WorkflowRun 均采用短事务 claim、heartbeat、lease 和单调 fence token。外部调用不持有聚合根行锁，写回必须验证 owner + fence。
4. DAG 每轮并发执行 ready set；依赖边保存精确 ArtifactVersion 引用。
5. Outbox 使用版本化 envelope、指数退避与死信；消费者保存去重状态。由于崩溃可发生在副作用完成与确认之间，业务端仍必须幂等并使用 fencing。
6. 跨租户聚合所有权由 `(tenant_id, id)` 复合约束落到 PostgreSQL。素材只保存稳定 storage locator，Provider 专属路径由 staging adapter 负责。
7. Decision 显式区分 `plan`、`step` 与 `order` scope。Step Decision 的 resolution 写回原 AgentStepExecution，并通过 Outbox 恢复同一 attempt；Capability 从 durable runtime binding 读取结果。
8. Active PlanVersion 必须在创建事务内同步 materialize 全部 AgentStepExecution。缺少权威 Step 的旧 Plan 不允许在 claim 阶段补建或静默重跑，统一进入 `manual_intervention / LEGACY_RUNTIME_STATE_UNSAFE_TO_RECONCILE`。开发环境如需清空旧任务，只能由部署操作者显式重置数据库，Runtime 不自动删除或重放。
9. Evaluator 普通异常只重试 evaluation phase，复用已持久化 CapabilityOutcome 与 ArtifactVersion；次数有界并受 fence 保护。Redis 仅作投递 transport，Consumer 失败或 claim 后崩溃时从 PostgreSQL Outbox 恢复，未知 topic/schema 也进入同一重试与死信链。

## 后果

部署新实现版本不会改变已创建任务的含义；租约接管后的迟到结果会被丢弃；删除或缺失事件历史不影响任务恢复。迁移前遗留的 active Plan 如果没有完整 Step 权威态将停止并等待人工处置，不会因升级产生重复副作用。旧的 `harness` 执行类型、`bind_executor` 别名、`cancelled` 拼写和 `failed_retryable` 运行态不再进入新代码路径。
