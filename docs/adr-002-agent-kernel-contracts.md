# ADR-002：先冻结 Agent 内核合同，再扩展产品能力

- 状态：Accepted
- 日期：2026-08-21

## 决定

星流只有一个面向客户的 Agent 产品。模型、Codex/Hermes/DeepSeek Harness、New API、CCSwitch、数字人引擎和后续供应商均为内部实现，不成为客户需要理解或选择的产品对象。

底座先冻结以下合同：

1. `AgentIntentSpec`：客户目标、交付物、约束、输入和假设；
2. `AgentPlanSpec / PlanStepSpec`：仅描述能力依赖、期望产物、评价器和检查点；
3. `BrainPort`：结构化理解、规划和评价，不泄漏具体模型协议；
4. `AgentExecutorPort`：可选地封装自主外部执行器的启动、恢复、中断、审批和结果收集；
5. `CapabilityDefinition / CapabilityOutcome`：业务能力的发现、执行、等待、决策、失败和产物；
6. `ArtifactDraft / DecisionSpec`：内核可持久化的业务输出。

`app.agent` 是稳定内核，只定义合同和端口，不得导入 Product Capability、Provider 或 Workflow Schema。Agent Runtime 只按 Capability Registry 调度，不对 `avatar.render` 等具体功能写条件分支。具体能力插件自己拥有工作流观察、派发和取消逻辑。

## 内部接入规则

- New API 作为 OpenAI-compatible 模型网关，负责密钥、渠道和模型路由；星流只保留薄 `BrainPort` 适配器。
- CCSwitch 可作为运维配置工具，但不进入生产单、计划或客户前端协议。
- Codex、Hermes、CLI Harness 等仅在需要独立自主执行环境时通过 `AgentExecutorPort` 接入；普通 Capability 默认由产品 Runtime 的 Handler 执行。
- 数字人口播是第一个 Capability 插件，不是 Agent Core，也不是产品总架构。
- 计划中禁止出现 Provider、外部 Executor、密钥或内部路由字段；Pydantic 合同使用 `extra=forbid` 拒绝这类泄漏。

## 后果

- 扩展新功能时新增 Capability 与执行适配器，不修改客户端生产单协议和 Agent Core 分支。
- 替换模型网关、Harness 或数字人供应商时，不迁移客户业务数据。
- 已登记但没有可执行绑定的能力不会进入规划目录；旧计划若引用不可用能力会明确进入 `manual_intervention`，不会生成假结果。
- 当前模板规划器作为未配置云大脑时的可测试降级；配置模型网关后由 `BrainPlanner` 生成并验证同一 `AgentPlanSpec`。
