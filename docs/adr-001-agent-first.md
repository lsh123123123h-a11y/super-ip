# ADR-001：Agent-first 产品与运行时边界

- 状态：Accepted
- 日期：2026-08-21

## 决定

星流 AI 定义为“非对话式长任务 Agent”。非对话只是交互表现，不是能力本质。主业务对象固定为 `Project + ProductionOrder + ArtifactVersion`，不以 Chat、Thread 或 Prompt 作为业务真相。

Agent Runtime 持有目标、计划、评价、政策和重规划权；Durable Workflow 只负责依赖、状态、租约、重试、超时、取消和恢复；Provider 只实现版本化 Capability Contract。

## 理由

- 同一生产目标可由 Codex、Hermes、DeepSeek Harness、本地 Worker 或云 API 完成，客户不应绑定供应商。
- 长任务需要离开页面后继续、异常恢复、幂等和不可变产物，聊天记录无法承担这些职责。
- 用户只在策略检查点、缺少关键输入、超过预算或高风险副作用前接收 `DecisionRequest`。

## 后果

- 前端主入口使用生产单、计划、决策和产物版本，不要求用户维持对话。
- 所有外部执行必须从 Capability 进入，具体 Provider 不进入客户协议。
- 新计划、新产物与局部重做创建新版本，不覆盖旧事实。
- 尚未接入的能力必须明确停在 `manual_intervention`，不用静态演示结果冒充生产结果。
