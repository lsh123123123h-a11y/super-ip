# 实施记录

## 2026-08-22：Production Platform Foundation 封板

- 目标：在不重写 Runtime Foundation 与 Capability/Workflow/Provider 核心边界的前提下，建立可上线的身份授权、数据库租户隔离、对象存储、计量计价、可观测性、管理端与自动质量门禁。
- 实际修改：新增 OIDC/JWT 与 Service Principal adapter、关系化 RBAC 和统一 permission gate；37 张 tenant-owned 表启用 FORCE RLS，并分离 migration owner 与非特权 runtime role；StorageBackend 支持 local/S3、presigned download、checksum、Provider staging/promotion 与 ArtifactVersion locator；新增不可变 UsageFact、版本化 PriceBook/PricingRule、Quota reservation、append-only Ledger 和统一 UsageReporter；增加真实 readiness、结构化脱敏日志、Prometheus 指标、平台运维 API 与 `/admin` 身份/资源计费分区；新增迁移 `20260822_0012`、ADR-005 至 ADR-008 和 GitHub Actions merge gates。
- 验证结果：隔离 PostgreSQL 17 空库升级后，以 `NOSUPERUSER NOBYPASSRLS` 非 owner 运行角色执行全部 88 项测试，`88 passed`、无 skip；相对封板前同条件 69 项增加 19 项，既有 Runtime Foundation 测试未删除。真实 MinIO 覆盖 S3 put/get/stat/presign，OIDC 覆盖签名/issuer/audience/exp/nbf/算法/请求头冒充；`0012 → 0011 → 0012` 通过，`20260821_0003 → head` 使用真实 legacy rows 验证 tenant/role 回填无丢失，前端 lint/build 与 Compose profile 均通过。
- 遗留风险：CI 与本地验证使用自签 JWT 和 MinIO，不代替目标部署环境的真实 IdP/S3 smoke；PostgreSQL system context 是受控应用 GUC，仍要求禁止 SQL 注入并严格保护 runtime 数据库凭据；本账本是内部计量账本，不包含支付、税务或发票语义。
- 可复用经验：RLS 必须用非 owner、非超级用户验证；Migration 和 Runtime 凭据必须分离；Provider 临时路径只能在 adapter 边界解释；Usage、Pricing、Quota 与 Ledger 必须分层，所有纠错通过追加事实完成；平台封板条件应由仓库 CI 自动证明，而不是依赖开发机口头结果。

## 2026-08-22：Runtime Foundation 封板闭环

- 目标：封闭 Step 决策永久等待、Legacy Plan 静默重跑、取消遗留非终态 Step、Evaluator 无限恢复和 Redis 消费失败丢事件五类最后可靠性缺口。
- 实际修改：Decision 增加 plan/step/order scope，Step resolution 持久化后用 Outbox 恢复原 attempt；claim 禁止补建旧 Plan；取消覆盖未来兼容的全部非终态 Step、Operation 与 pending Decision 并统一递增 fence；Evaluator 复用已落库 capability outcome 与 artifact 做有界 phase retry；ConsumedEvent 增加退避、processing takeover、恢复扫描和 dead-letter，未知 topic/schema 不再成功确认。新增迁移 `20260822_0011`。
- 验证结果：常规环境 47 项通过；隔离 PostgreSQL 空库升级到 head 后 69 项通过，新增覆盖 Decision resolve/tenant/idempotency/crash resume、Legacy Guard、全状态取消与 stale write、数据库提交后的外部 interrupt 失败隔离、Evaluator 成功重试/耗尽/lease takeover、Consumer duplicate/retry/dead-letter/expired claim/未知协议；`0011 → 0010 → 0011` 与 `20260821_0003 → head` 均通过。
- 遗留风险：跨 Redis 与业务副作用仍是至少一次语义，外部 Provider/Executor 必须继续提供幂等键和 fencing；人工介入订单尚未提供自动 Legacy 数据推断工具，因为无法可靠判断旧外部副作用是否已经发生。
- 可复用经验：恢复入口必须从数据库事实重建，不能依赖队列消息仍然存在；缺少权威运行态时宁可停止，也不能猜测并重放。

## 2026-08-22：Runtime Foundation 全面加固

- 目标：落实外部审计指出的步骤真相、长事务、迟到写回、版本漂移、伪 DAG、Artifact latest 解析、Outbox、租户约束、状态命名和存储耦合问题。
- 实际修改：新增 `AgentStepExecution` 与精确输入边；AgentStep、AgentOperation、WorkflowRun 全部采用短 claim + heartbeat + lease + fence；Capability/Evaluator/Workflow/Provider Adapter/Executor/Brain 路由精确版本持久化；ready set 并发执行，数字人计划允许脚本接收与已有音频检查并行；Outbox 增加 schema version、退避、死信和消费者去重；关键聚合增加复合租户 FK；统一 `retry_wait` / `canceled`；移除 `ExecutionKind.harness` 与 `bind_executor`；素材改用 storage locator 和 Provider staging adapter；内置能力补充具体 JSON Schema。
- 验证结果：常规环境 47 项通过、11 项数据库测试按预期跳过；隔离 PostgreSQL 空库全迁移后 58/58 通过，覆盖版本精确解析、DAG 依赖、无事件历史恢复、重复 claim、租约接管及迟到结果丢弃、Evaluator 锁外执行、消费者去重、跨租户 FK 和存储 staging；`20260821_0003 → head` 的降级与再升级通过。迁移链新增 `20260822_0004` 至 `20260822_0010`，临时测试库已删除。
- 遗留风险：真实 New API、Duix 与 OpenTalking 的生产凭据/服务连通仍需在部署环境做 smoke test；Consumer 的端到端语义仍是“至少一次 + 业务幂等/fencing”，不宣称分布式 exactly-once。
- 可复用经验：可恢复状态必须是一等数据模型；事件不能反推当前状态；版本选择只发生在控制记录创建时；任何可能越过 lease 的结果写回都必须携带 fence。

## 2026-08-21：AI Provider 控制面与动态 New API Brain

- 目标：把 New API / Brain 从日常 `.env` 配置升级为管理员可操作、动态生效并保存真实用量的 AI Provider 控制面。
- 实际修改：新增按租户隔离的 `AIProviderConfig`、`AIModelBinding`、`AIInvocation`；Provider Token 使用 Fernet 加密，API 只返回脱敏提示；新增 New API 连接测试、模型目录、启停、alias 绑定和调用事实 API；Brain 每次调用按 alias 动态解析数据库配置，`.env` 保留 bootstrap/fallback；规划、内容策略和内容生成分别使用 `reasoning.default` / `writing.default`；管理端「能力与通道」改为可编辑控制面，并保留媒体 Provider 折叠视图。
- 验证结果：隔离 PostgreSQL 全量迁移后 47 项后端测试通过，覆盖密钥非明文、alias 修改后同一 Brain 实例下一次调用生效、Token/延迟/成本事实记录和网关超时错误码；前端 ESLint 与生产构建通过；Compose 已迁移到 `20260821_0003`，API、Worker、Web 健康；未持久化配置的失败连接返回安全 502，日志不包含提交的 Token；隔离测试数据库已删除。
- 遗留风险：当前本地没有真实 New API 地址与 Token，因此没有冒充完成外部模型调用；正式 OIDC/RBAC/RLS 尚未完成，现阶段管理 API 在既有受信身份头之上校验租户 owner/admin；标准 Chat Completions 响应通常只提供 Token，不提供货币成本，成本字段保持空值直到网关明确返回或后续接入其授权日志 API。
- 可复用经验：New API 管上游渠道与网关计费，Super-IP 管业务语义 alias、生产上下文和本系统事实；Secret 加密主密钥属于部署 bootstrap，Provider Token 属于可动态更新的业务配置，两者不能混为同一层。

## 2026-08-21：纠正 Harness 默认假设并加入内容文章链路

- 目标：明确产品自己的 Agent Runtime 才是运行主体，普通内容能力通过 Brain/Handler 执行，Codex/Harness 等外部执行器只作为可选机制。
- 实际修改：`content.strategy` 与 `content.generate` 改为模型网关配置就绪后安装的 Brain-backed Handler，不再声明为 Harness 能力；新增 `content.article` Product，串联意图、内容策略和文章草稿；Runtime 向后续 Capability 提供最新可用 Artifact；增加内容策略完整性与文章基础质量规则；外部能力命名改为 `ExecutionKind.external` / `bind_external_executor` 并保留旧 `harness` 值和旧绑定方法兼容；Provider 内部就绪字段泛化为 `ready`，对旧 API 继续返回 `render_ready` 兼容字段。
- 验证结果：隔离 PostgreSQL 完整迁移后 45 项后端测试通过；新增测试覆盖 Brain 内容能力合同、文章/口播脚本输出分型、Artifact 传递、非数字人 Product 计划、Provider `ready` 兼容，以及无 External Executor 的内容 Runtime 完整链路；临时测试数据库已删除。
- 遗留风险：内容策略与生成尚未使用真实模型凭据做连通验证；内容研究/爆款研究仍缺搜索或平台数据 Tool/MCP；当前内容评价为确定性基础规则，语义质量、事实性与平台适配仍需 Brain + 领域规则组合评价。
- 可复用经验：Capability 描述业务语义，Brain、Provider、Workflow、Tool/MCP 和 External Executor 都只是其内部执行手段；只有真实安装且依赖就绪的实现才能进入规划目录；多步骤业务必须通过 Artifact 合同传递结果，不能依赖场景专用输入字段。

## 2026-08-21：通用能力、Workflow 插件与评价返工闭环

- 目标：保留现有 Agent Runtime、ProductionOrder、PlanVersion、AgentOperation、WorkflowRun、Outbox、Lease 等可靠骨架，移除会随新能力增加而持续恶化的数字人默认前提。
- 实际修改：Capability Registry 分离目录与 Handler/Executor 绑定，新增统一 Capability Dispatcher 和标准 Harness 终态结果；Product、Capability、Evaluator、Workflow、Provider、Executor 支持显式扩展模块注册；通用 Worker 从 518 行缩减为纯分发/恢复职责，数字人状态机迁入 `digital_human.render` Workflow 插件；Provider Registry 改为 capability 维度路由与策略注册；Runtime 真正写入 QualityEvaluation，并实现 accept、自动 rework、自动 replan、达到上限转人工；模板规划只引用已安装执行入口，避免静态 capability key 进入不可执行计划。
- 验证结果：Python 编译通过；隔离 PostgreSQL 全量迁移后 39 项后端测试通过，覆盖数字人完整成功链、评价失败后同一步骤返工、Harness capability 经 AgentOperation 执行并回到统一评价链；前端 ESLint、Next.js 生产构建和 Compose 配置检查通过；隔离测试数据库已删除；API、Worker 已使用新镜像重建，健康接口与通用 Provider 目录返回正常。
- 遗留风险：尚未接入真实 Codex/Hermes/Harness Adapter，当前只验证了稳定端口和测试 Adapter；内置评价器目前是确定性产物合同门禁，内容/画面质量仍需领域 evaluator；扩展注册是部署时 Python module registrar，尚未建设租户级动态安装、签名和沙箱；OIDC/RBAC/RLS、对象存储、计费价格表、配额与长期知识仍未进入本阶段。
- 可复用经验：新增能力必须同时声明定义、真实执行绑定和 evaluator；新增可靠长流程以 Workflow 插件注册，不向 Worker 添加业务分支；Provider 只负责 capability 执行归一化，不拥有生产单状态；目录中“已知”不等于运行时“已安装”。

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
