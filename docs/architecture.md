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
    └─ Capability Contract → Capability Dispatcher
                              ├─ Handler → Brain / Tool / MCP / Provider / Workflow
                              └─ 可选 External Executor → AgentOperation
                                      ↓
                    Product / Capability / Workflow / Provider / Evaluator Registries
```

当前主链已落库为 `Project → ProductionOrder → AgentRun → PlanVersion → AgentStepExecution → ArtifactVersion`；需要 Provider 轮询的步骤再关联 `WorkflowRun`。`AgentEvent` 只保存审计时间线，不参与步骤完成度、重试或恢复判断。旧 `IPProfile / Campaign / ContentProject` 作为兼容业务对象保留，新 Agent 链路通过 Snapshot 和 ContentItem 逐步承接。

依赖方向固定为“适配器依赖合同”。`backend/app/agent/` 不导入能力插件、工作流 Schema 或 Provider；`agent_runtime.py` 只处理通用 `CapabilityOutcome` 和 `EvaluationResult`。数字人口播的工作流查询、提交、失败归一化与取消位于 `capabilities/avatar_render.py`，其具体状态机位于 `workflows/avatar_render.py`。

Capability Registry 分离“目录定义”和“可执行绑定”。普通业务能力默认绑定产品自己的 Handler；Handler 可以调用 Brain、Tool/MCP、Provider 或启动 Workflow。只有确实需要独立自主运行环境的能力才绑定可选 External Executor。未绑定的目录项不会进入规划器的 installed catalog。Product、Capability、Evaluator、Workflow、Provider、Executor 均支持通过部署配置中的扩展模块注册，新增业务不再修改通用 Worker。

所有可能等待外部系统的 Agent 内部工作统一进入 `AgentOperation` 控制面：

```text
API 事务
ProductionOrder + AgentRun + AgentOperation + Outbox
                         ↓
Worker 租约领取 → 权限/预算/超时检查 → BrainPort 或可选 AgentExecutorPort
                         ↓
PlanVersion / 外部执行句柄 / Usage / Trace / 有界重试
```

因此创建生产单不等待云模型。初始 API 可以返回 `plan=null`；后台规划成功后才创建 PlanVersion，并依据自动化策略进入方案确认或执行队列。

## 2. Brain、Capability 与执行机制边界

产品自己的 Agent Runtime 是唯一运行主体。`BrainPort` 是 Runtime 获取模型推理的端口，可用于结构化理解、规划、内容生成和后续模型评价；`Capability Contract` 表达业务能做什么，不能用执行器类型命名业务语义。`content.strategy`、`content.generate` 因而由 Brain-backed Handler 实现，只依赖模型网关，不依赖 Codex 或 Harness。

Provider 负责同类服务的可替换适配与路由；Workflow 负责需要等待、轮询、恢复或多阶段推进的可靠执行；Tool/MCP 应作为 Capability 内部调用的原子动作与资源访问入口，在出现真实内容研究/检索需求时按权限、审计和结果合同接入。`AgentExecutorPort` 仅保留给 Codex、Hermes、CLI 等拥有独立生命周期的自主外部执行器，不是核心内容能力的默认路径。

New API 作为独立的 OpenAI-compatible 内部模型网关，继续拥有上游渠道、负载均衡、Token、倍率与网关日志等管理能力；星流不复制它的管理后台。model alias 只在创建 AgentOperation / AgentStepExecution 时解析一次，并把 binding、Provider 配置版本、Adapter 版本、上游模型和路由策略快照持久化；执行时仅允许读取同一 Provider 的当前密钥，以支持凭据轮换而不改变任务语义。`.env` 仅作系统 bootstrap/fallback。星流向网关发送带 JSON Schema 的结构化请求，返回内容仍必须通过内核合同验证。

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
  → retry_wait（指数退避，最多 3 次）
  → failed_final
```

数据库是事实来源。`OutboxEvent` 在业务事务提交后再投递 Redis，事件带 schema version，发布失败采用指数退避并在达到上限后进入死信；消费者用 `ConsumedEvent` 保存 processing lease、失败退避、接管次数与 dead-letter。`BLPOP` 后处理失败或进程退出时，恢复扫描从原始 OutboxEvent 重建 envelope；未知 topic/schema 不得记为成功。业务执行仍用幂等键和 fencing 抵御“处理成功但确认前崩溃”的重复投递。Redis 不承担唯一任务事实。`StepAttempt` 不可变保存每次 Workflow 执行，`ProviderJob` 保存外部任务。

`AgentOperation` 与 `WorkflowRun` 的边界不同：前者承载 Agent 的异步规划和可选外部执行器任务；后者承载 Provider 调用或多阶段业务能力的可靠执行。两者都使用数据库租约与 Outbox，但不互相冒充。

## 5. 评价、返工与重规划

每个 PlanStep 的 evaluator 必须解析到已安装 Evaluator。能力成功后，Runtime 先定位本 PlanVersion 的不可变 ArtifactVersion，再写入 QualityEvaluation：

```text
Capability succeeded → Evaluate
  ├─ accept → step succeeded
  ├─ rework → 同一步骤新 execution_attempt，旧产物 returned
  ├─ replan → 新 AgentOperation(planning) 与新 PlanVersion
  └─ manual / 超过 max_auto_rework → manual_intervention
```

Evaluator 普通异常保持同一 AgentStepExecution 在 `evaluating` phase，以持久化的 `capability_outcome + output_artifact_version_id` 有界重试，不重新调用 Capability；精确 Evaluator 版本缺失属于永久运行时错误。每次评价领取与写回都验证 owner + fence，租约接管后旧评价结果不会落库。

外部 Executor 结果必须返回终态 `CapabilityOutcome`；Dispatcher 将其转换回同一条评价链。Handler、Provider/Workflow 和可选外部 Executor 都不各自实现质量闭环。内置内容评价器目前只增加了策略字段完整性、标题与正文长度等确定性规则；真正的内容质量仍应后续组合 Brain 与领域规则判断。

## 6. 编排可靠性规则

- 创建任务使用 `(owner_id, idempotency_key)` 唯一约束。
- Worker 只在短事务中领取执行权；AgentStepExecution、AgentOperation 与 WorkflowRun 均保存 lease、heartbeat 和单调 fence token。能力、模型和 Provider 调用在锁外执行，迟到结果必须用 owner + fence 条件写回。
- 每次重试生成新的 Provider 外部任务号：`{workflow_id}-{attempt}`，原任务记录不覆盖。
- 创建任务前执行 Provider 健康检查；显式指定不可用引擎时直接返回可行动错误，自动路由可选择下一就绪引擎。
- Duix 的 `10004 任务不存在` 在刚提交后可能是短暂可见性延迟；允许有限次数轮询，超过阈值才失败。
- 失败保留错误码、错误消息、步骤状态和 Provider 原始响应。
- 素材以 `storage_backend + storage_key` 和稳定 `asset://` locator 保存；业务计划不持久化 Duix 容器路径。Provider staging adapter 在提交边界把 locator 转换为 Duix mount 路径或其他 Provider 所需引用。

PlanStep 是真实 DAG：Worker 每轮领取完整 ready set 并并发执行独立节点；依赖输入通过 `AgentStepArtifactInput` 绑定精确 ArtifactVersion，重试和重规划不会重新解析“同 key 最新产物”。Capability、Evaluator、Workflow、Provider Adapter、External Executor 与 Brain 路由都使用创建时固定的精确版本。

PlanVersion 创建与完整 AgentStepExecution materialization 必须在同一事务完成。claim 阶段只读取权威 Step，不负责补建；发现 active Plan 缺少任一步骤时，订单进入 `manual_intervention` 并记录 `LEGACY_RUNTIME_STATE_UNSAFE_TO_RECONCILE`。部署升级不会自动重放旧 Plan；开发库是否重置由操作者显式决定。

DecisionRequest 以 `scope=plan|step|order` 区分方案审批、步骤内决策和订单控制。Step Decision resolve 后把结构化 resolution 写回原 Step 的 runtime binding，通过 Outbox 唤醒同一 attempt；重复 resolve 被拒绝，订单取消会使所有 pending Decision 失效并 fence 全部非终态 Step。

## 7. 后续扩展方式

接入 OpenTalking 或其他数字人服务时，新增 Provider，不修改营销业务工作流的对外协议。统一能力为 `avatar.render`，网关根据场景选择：

- Duix：当前生产主链，离线批量成片和本地/自托管数据；
- OpenTalking：第二引擎，覆盖视频创建、视频克隆与后续实时会话；通过星流视频桥归一化为异步 Provider Job；
- 云 Provider：突发扩容与高规格成片。

当前第二个非数字人 Product 为 `content.article`，通过 Brain-backed `content.strategy → content.generate` 验证 Artifact 在能力间传递以及统一 Evaluate 闭环。下一阶段优先加入真实 `content.research` / 爆款研究：先接搜索或平台数据 Tool/MCP，再由 Capability 形成有来源的研究 Artifact，并加入 Brain + 领域规则评价。External Executor Adapter 按真实自主执行场景再接，不作为这条业务链的前置条件。随后再按上线需求推进版本化价格、对象存储、OIDC/RBAC/RLS、配额与 Knowledge/Retrieval。
