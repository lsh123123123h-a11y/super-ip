# ADR-003：用统一 AgentOperation 承载异步规划与可选外部执行

- 状态：Accepted
- 日期：2026-08-21

## 决定

业务 API 不直接调用云模型或外部执行器。创建生产单只在同一事务中保存 `ProductionOrder + AgentRun + AgentOperation + OutboxEvent`，立即返回 `planning`；Worker 再领取 Operation，执行结构化规划并原子创建 `PlanVersion`、审核请求或后续运行消息。

`AgentOperation` 是异步规划与可选外部 Executor 共享的控制面，持久化：

- `queued / running / waiting / failed_retryable / succeeded / failed_final / canceled` 状态；
- 幂等键、尝试次数、指数退避、下次唤醒时间与 Worker 租约；
- Executor Key 与外部执行 ID；
- 必需权限、已授予权限、超时、预算上限、预算预留和实际消耗；
- `trace_id / span_id / parent_span_id` 与结构化 Usage；
- 安全错误码和错误摘要。

规划是 `operation_type=planning`，由 `BrainPlanner` 执行。只有需要独立自主运行环境的能力才使用 `operation_type=executor`，由 `ExecutorRegistry` 中已安装的 `AgentExecutorPort` 执行。普通 Capability 通过 Handler 调用 Brain、Provider、Workflow 或 Tool/MCP，不以安装 Executor 为前提。客户不能提交或选择 Executor Key；它只能由内部能力与策略决定。

## 可靠性规则

- Redis 只运输 Operation ID；数据库与 Outbox 是事实来源。
- Worker 执行外部调用前先提交租约，宕机后由过期租约恢复。
- 可重试错误使用有上限的指数退避；未安装 Executor、缺少权限和预算不足直接进入最终失败。
- 规划结果必须再次通过 `agent.plan.v1`，然后与 Operation 成功状态在同一事务提交。
- 暂停时 Operation 不继续领取；规划期间取消会将 Operation 标为 canceled，迟到结果不得覆盖生产单。
- Agent Trace 使用内部事件；客户活动摘要不得直接暴露模型、外部 Executor、Provider 或原始工具日志。

## 后果

- API 延迟不再受云模型响应时间影响，规划可以安全重试和恢复。
- 初始响应允许 `plan=null`；客户界面显示“后台形成方案”，并轮询生产单状态。
- 新 External Executor Adapter 只需注册 Executor Definition 与 Port 实现，不新增第二套队列和状态机。
- External Executor 是可选扩展面，不是内容策略、内容生成等核心业务能力的运行前提；模型 Token Usage 已记录，但货币成本仍需接入版本化价格表后才能写入 `budget_spent`。
