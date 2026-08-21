# 星流 AI：Agent-first 生产架构

## 1. 边界

产品是独立 Web 应用，本质上是长任务 Agent，“非对话式”只是客户交互形态。业务真相是生产单、计划、决策与产物版本，不依赖 Chat 线程才能继续执行。数字人口播现在是 `digital_human.video` Product Adapter 和 `digital_human.render` Workflow 插件，不再是通用 Worker 或 Agent Runtime 的默认前提。

```text
用户端 `/` / 管理端 `/admin`
    ↓
SaaS 业务层（Tenant、Project、ProductionOrder、Decision、ArtifactVersion）
    ↓
Agent Kernel（Intent、Plan、Policy、Evaluation、Replan）
    ├─ BrainPort → New API → 内部模型路由
    ├─ AgentExecutorPort → Codex / Hermes / DeepSeek Harness
    └─ Capability Contract → Capability Dispatcher
                              ├─ Handler → inline / durable plugin
                              └─ Executor binding → Harness AgentOperation
                                      ↓
                         Product / Workflow / Provider / Evaluator Registries
```

当前主链已落库为 `Project → ProductionOrder → AgentRun → PlanVersion → WorkflowRun → ArtifactVersion`。旧 `IPProfile / Campaign / ContentProject` 作为兼容业务对象保留，新 Agent 链路通过 Snapshot 和 ContentItem 逐步承接。

依赖方向固定为“适配器依赖合同”。`backend/app/agent/` 不导入能力插件、工作流 Schema 或 Provider；`agent_runtime.py` 只处理通用 `CapabilityOutcome` 和 `EvaluationResult`。数字人口播的工作流查询、提交、失败归一化与取消位于 `capabilities/avatar_render.py`，其具体状态机位于 `workflows/avatar_render.py`。

Capability Registry 分离“目录定义”和“可执行绑定”。能力可以绑定普通 Handler 或 Harness Executor；未绑定的目录项不会进入规划器的 installed catalog。Product、Capability、Evaluator、Workflow、Provider、Executor 均支持通过部署配置中的扩展模块注册，新增业务不再修改通用 Worker。

所有可能等待外部系统的 Agent 内部工作统一进入 `AgentOperation` 控制面：

```text
API 事务
ProductionOrder + AgentRun + AgentOperation + Outbox
                         ↓
Worker 租约领取 → 权限/预算/超时检查 → BrainPort 或 AgentExecutorPort
                         ↓
PlanVersion / 外部执行句柄 / Usage / Trace / 有界重试
```

因此创建生产单不等待云模型。初始 API 可以返回 `plan=null`；后台规划成功后才创建 PlanVersion，并依据自动化策略进入方案确认或执行队列。

## 2. 大脑、执行器与能力不是三套产品

`BrainPort` 负责需要模型判断的结构化理解、规划和评价；`AgentExecutorPort` 负责需要 Harness 长时运行的执行；`Capability Contract` 负责产品可交付能力。三者都隐藏在同一个星流 Agent 后面，前端不提供 Harness、模型或 Provider 选择。

New API 只作为 OpenAI-compatible 内部模型网关。星流向它发送带 JSON Schema 的结构化请求，返回内容必须再次通过内核合同验证。CCSwitch 只可辅助运维配置，不作为业务运行时依赖。

## 3. Provider / Capability / Workflow 边界

Duix 只负责“音频 + 参考视频 → 数字人口播视频”。商业产品还需要保存任务、排队、重试、隔离用户、记录作品版本、管理配额和处理失败退款。这些都属于自有编排层，不能塞进 Duix Provider。

Provider Registry 以 capability 路由，不再以数字人作为固定类别。每个 Provider 声明能力、执行模式、健康状态、轮询间隔与归一化结果；每项 capability 可注册独立的版本化路由策略。Provider 的职责被限制为：

- 把统一 Capability 请求转换为目标服务参数；
- 提交、查询并归一化进度、成功、失败和结果引用；
- 隐藏服务错误码、容器路径和接口差异；
- 返回标准结果，不写业务订单或用户状态。

## 4. Agent 与 Workflow 的状态分层

生产单控制用户可见的长任务状态：

```text
planning / awaiting_plan_approval
  → queued / running
  → awaiting_decision / evaluating / retry_wait / paused
  → succeeded / failed_final / canceled / manual_intervention
```

`WorkflowRun` 仅保存单个可靠执行单元。通用 Worker 只负责 Outbox、队列分发、租约和恢复扫描；具体步骤由 Workflow Registry 按 `task_type` 解析。当前首个工作流插件为 `digital_human.render`：

```text
queued
  → running / 检查素材
  → waiting_provider / Duix 渲染
  → running / 保存成片
  → succeeded

任一步失败
  → failed_retryable（最多 3 次）
  → failed_final
```

数据库是事实来源。`OutboxEvent` 在业务事务提交后再投递 Redis，Worker 通过 DB 租约和恢复扫描重新发现任务；Redis 不再承担唯一任务事实。`StepAttempt` 不可变保存每次执行，`ProviderJob` 保存外部任务。

`AgentOperation` 与 `WorkflowRun` 的边界不同：前者承载 Agent 的规划和 Harness 级长任务；后者承载媒体等确定性业务能力的可靠执行。两者都使用数据库租约与 Outbox，但不互相冒充。

## 5. 评价、返工与重规划

每个 PlanStep 的 evaluator 必须解析到已安装 Evaluator。能力成功后，Runtime 先定位本 PlanVersion 的不可变 ArtifactVersion，再写入 QualityEvaluation：

```text
Capability succeeded → Evaluate
  ├─ accept → step succeeded
  ├─ rework → 同一步骤新 execution_attempt，旧产物 returned
  ├─ replan → 新 AgentOperation(planning) 与新 PlanVersion
  └─ manual / 超过 max_auto_rework → manual_intervention
```

Harness 结果必须返回终态 `CapabilityOutcome`；Dispatcher 将其转换回同一条评价链。这样 Handler、CLI/Harness、后续 MCP/Tool Adapter 不需要各自实现质量闭环。

## 6. 编排可靠性规则

- 创建任务使用 `(owner_id, idempotency_key)` 唯一约束。
- Worker 用数据库行锁领取任务，避免多个 Worker 同时执行同一条工作流。
- 每次重试生成新的 Provider 外部任务号：`{workflow_id}-{attempt}`，原任务记录不覆盖。
- 创建任务前执行 Provider 健康检查；显式指定不可用引擎时直接返回可行动错误，自动路由可选择下一就绪引擎。
- Duix 的 `10004 任务不存在` 在刚提交后可能是短暂可见性延迟；允许有限次数轮询，超过阈值才失败。
- 失败保留错误码、错误消息、步骤状态和 Provider 原始响应。
- Duix 与 API 通过同一宿主机共享目录交换素材；业务 API 只下发 Duix 容器内路径。

## 7. 后续扩展方式

接入 OpenTalking 或其他数字人服务时，新增 Provider，不修改营销业务工作流的对外协议。统一能力为 `avatar.render`，网关根据场景选择：

- Duix：当前生产主链，离线批量成片和本地/自托管数据；
- OpenTalking：第二引擎，覆盖视频创建、视频克隆与后续实时会话；通过星流视频桥归一化为异步 Provider Job；
- 云 Provider：突发扩容与高规格成片。

下一阶段优先接入第一个真实 Codex/Harness Executor Adapter，并用“内容研究或内容生成”作为第二个非数字人 Product + Workflow 验证扩展面；同时把领域评价器接入 Brain/规则组合评价。随后再接版本化价格表与 `budget_spent`、对象存储，正式 OIDC/RBAC/RLS、配额账本和长期 Knowledge/Retrieval 按真实多租户上线节奏推进。新能力必须沿用已冻结合同，不反向修改 Agent Core。
