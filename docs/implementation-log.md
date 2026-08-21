# 实施记录

## 2026-08-21：异步 AgentOperation 控制面

- 目标：让云大脑与后续 Harness 成为可恢复的 SaaS 后台任务，而不是阻塞 API 的同步调用或各自维护一套状态机。
- 实际修改：新增 `AgentOperation` 数据模型、迁移、ExecutionPolicy、TraceContext、ExecutorDefinition 与 Executor Registry；创建生产单改为同事务落库 Operation 和 Outbox 后立即返回，后台规划成功后才创建 PlanVersion；初始规划、用户要求调整和补素材重规划统一走 Operation；加入租约、权限、累计预算检查、超时、指数退避、暂停/取消保护、Usage 与 Trace 事件；前端支持 `plan=null` 的真实规划状态。
- 验证结果：后端 25 项常规测试通过，3 项隔离 PostgreSQL 集成测试通过，覆盖自动规划后能力派发、非自动模式规划后方案审核、规划完成前取消；迁移完成“全量升级”和本次版本“降级→再升级”；前端 ESLint 与 Next.js 生产构建通过；Compose 配置检查通过。
- 数据与部署：迁移前备份位于 `F:\ip-ai\.codex-work\backups\20260821-before-agent-operations.dump`，已验证为可读 PostgreSQL archive；项目数据库已升级到 `20260821_0002`，新增表后共 28 张业务表，现有数据未删除。API、Worker、Web 已部署新源码并通过健康检查；保留 `pre-agent-operations-20260821` 镜像标签用于回退，Migrate 镜像已验证包含 Alembic。
- 遗留风险：尚未提供真实 New API 凭据，未验证真实云模型；Executor Registry 尚无真实 Harness Adapter；Token Usage 尚未映射版本化单价，因此 `budget_spent` 暂不产生货币成本；OIDC/RBAC/RLS 仍未完成。因本机缺少上游基础镜像标签，本次使用已验证旧镜像作为本地依赖层叠加新源码；上游镜像仓库恢复后仍应执行一次干净构建。
- 可复用经验：所有会等待外部系统的 Agent 内部工作都应先持久化 Operation；API、外部调用和业务状态不能处于同一个长事务中，迟到结果必须先检查生产单与 Operation 终态。

## 2026-08-21：Agent 底座合同冻结与首个能力插件拆分

- 目标：停止按页面功能堆叠，先固定可支撑 SaaS Agent 的大脑、执行器、能力、计划、决策和产物合同。
- 实际修改：新增 `agent.intent.v1`、`agent.plan.v1`、`agent.capability.v1` 与 Brain/Executor Port；建立 Capability Registry；将数字人口播的 Workflow 查询、派发、失败和取消从 Agent Runtime 移入 `avatar.render` 插件；工作流、Outbox 与 Agent 派发事件改为同一事务提交；新增 New API / OpenAI-compatible 云大脑薄适配器与 BrainPlanner；模板规划器迁移到 Product 层；用户端撤下直达 Provider 选择的数字人工作室入口，并把计划与任务改为业务语言展示，技术通道仍只留在管理端。
- 验证结果：后端 23 项常规测试通过；隔离 PostgreSQL 集成测试确认通用 Runtime 能连续完成 3 个内联步骤并通过插件派发 `avatar.render`，测试库随后已删除；前端 ESLint 与 Next.js 生产构建通过。架构测试确认 Agent Runtime 不再导入 Workflow Schema、Provider 或数字人口播实现，并拒绝计划中的 Provider 等越界字段；BrainPlanner 会拒绝幻觉或未安装能力；New API 适配器通过 MockTransport 验证 URL、鉴权、结构化响应、Token 用量和异常收口。
- 遗留风险：尚未提供真实 New API 地址、密钥和模型，因此未做云端连通验证；云规划当前发生在创建生产单请求内，下一阶段应迁移到 Outbox 驱动的异步可恢复规划；Harness 只有稳定端口，尚未实现首个 Executor Adapter；正式 OIDC/RBAC/RLS、配额账本和对象存储仍未完成。
- 可复用经验：计划只引用业务 Capability，不能携带模型、Harness 或 Provider 选择；Agent Core 只消费统一 Outcome，具体能力必须自行拥有外部执行生命周期。

## 2026-08-21：Agent-first 核心与首条可恢复生产链

- 目标：将当前数字人工具正式迁移为非对话式 Agent 平台，以生产单而非聊天/工作流作为用户业务主体。
- 实际修改：新增 Tenant/User/Membership、Project、ProductionOrder、AgentRun、PlanVersion、DecisionRequest、Asset/AssetRef、ArtifactVersion、QualityEvaluation、AgentEvent 和 OutboxEvent；新增 Agent API、非对话生产界面、计划确认/重规划、补素材原地续跑、产物审核和 Agent 与数字人 Workflow 联动。Worker 改为短轮询、DB 租约、StepAttempt、Outbox 和 DB 恢复扫描。
- 验证结果：后端 12 项测试、前端 ESLint 和 Next.js 生产构建通过；真实 PostgreSQL/Redis + mock Duix 链路验证了计划 V2、跨计划事件隔离、5 个不可变产物版本和产物批准；新建数据库的迁移“升级→降级→再升级”通过，最终 27 张表。
- 遗留风险：当前 Principal 仍是开发环境受信请求头，尚未接入正式 OIDC/RBAC/RLS；`content.strategy`、`content.generate`、`audio.prepare`、`video.compose` 尚未配置真实 Provider；旧 Workflow API 仍保留 Provider 细节以兼容原界面。Docker 源码镜像重建因上游 Docker Hub 读取 EOF 未完成，本次通过现有镜像挂载新源码完成运行验证，不表示已部署。
- 可复用经验：每条步骤完成事件必须绑定 PlanVersion；否则重规划会误用旧计划事实。Provider 提交与 Redis 入队不能代替事务 Outbox，任务恢复以数据库为准。

## 2026-08-20：数字人能力网关第一阶段

- 目标：在不锁定模型与部署形态的前提下，将数字人任务从业务界面解耦为可路由、可追踪、可替换的供应商编排流程。
- 实际修改：建立统一数字人供应商协议、Duix 与 OpenTalking 适配器、健康感知路由、路由决策持久化、通用 Worker 执行，以及用户端供应商选择和管理端能力状态页。
- 验证结果：后端 9 项测试通过；前端生产构建和 ESLint 通过；Docker API、Worker、Web 重建成功；线上本机健康接口、供应商目录和路由预览正常。
- 遗留风险：OpenTalking 当前只完成探测与稳定桥接协议，启用生产渲染仍需部署桥接服务；数据库目前依赖 `create_all`，正式上线前应引入迁移；租户、RBAC、计费和审计尚未进入本阶段。
- 可复用经验：业务任务只提交能力与约束，具体模型、部署位置和供应商选择由版本化路由策略决定；所有路由结果随工作流落库，使后续灰度、回放和成本分析不依赖前端状态。

## 2026-08-20：用户端与管理端重构

- 目标：纠正单页工具导航，将产品重构为活动驱动的用户生产端与独立运营管理端，并把竞品分析后的功能骨架真正落实到产品中。
- 实际修改：用户端改为今日工作台、IP 大脑、营销活动、内容工作室、数字人工作室、资产中心、任务中心、发布与复盘；管理端新增独立 `/admin` 路由及经营、租户、账本、能力、路由、Worker、任务、授权、治理、配置和审计模块。新增 `IPProfile`、`Campaign`、`ContentProject` 后端对象及 API，脚本保存后再进入数字人任务。
- 验证结果：前端生产构建与 ESLint 通过；后端测试与编译通过；用户端和管理端均返回 200；通过独立测试租户完成 IP、活动、内容项目创建和关联验证，并已清理测试数据。
- 遗留风险：身份认证、RBAC、不可变账本、授权证据、通用云模型内容生成和平台发布尚未实现；当前数据库仍使用自动建表，正式发布前必须引入迁移。
- 可复用经验：用户端与管理端共享同一业务事实，但不共享信息架构；未接入的能力明确标记建设状态，不能用静态数字或假按钮伪装为生产能力。
