# 星流 AI · 非对话式 Agent 生产平台

星流的核心是长任务 Agent，不是聊天包装的工具集。用户提交最终目标后，系统形成可恢复的 `ProductionOrder`，再由 Agent Runtime 进行理解、规划、决策、执行、评价和重规划。

`目标 → IntentSpec → PlanVersion → Durable Workflow → ArtifactVersion → 结构化审核/决策`

数字人是首个真实执行能力 `avatar.render`，而非产品本体。Codex、Hermes、DeepSeek Harness 通过 `AgentExecutorPort` 接入，模型通过 `BrainPort` 接入；这些内部选择都不改变客户端的生产单协议。

产品现在明确分为两个入口：

- `/`：用户端，以“Agent 生产”为主入口，查看生产单、计划、决策请求和产物版本。
- `/admin`：管理端，围绕租户、账本、能力通道、路由、Worker、任务运维、授权与治理工作。

## 目录

- `app/`：Next.js 独立 Web 前端。
- `backend/app/main.py`：FastAPI 业务 API。
- `backend/app/worker.py`：异步编排 Worker。
- `backend/app/services/agent_runtime.py`：目标驱动的 Agent 运行时与重规划。
- `backend/app/agent/`：稳定的 Intent、Plan、Brain、Executor、Capability 合同。
- `backend/app/capabilities/`：可插拔业务能力；数字人口播是首个插件。
- `backend/app/integrations/new_api_brain.py`：New API / OpenAI-compatible 云大脑薄适配器。
- `backend/app/services/agent_operation_service.py`：异步规划、Harness 执行、租约、重试、权限、预算、超时和 Trace 控制面。
- `backend/app/executors/`：内部 Harness Executor 注册表；不进入客户协议。
- `backend/app/services/outbox_service.py`：数据库事务与 Redis 消息的可恢复衔接。
- `backend/app/providers/duix.py`：Duix Provider 适配器。
- `backend/app/providers/opentalking.py`：OpenTalking 服务探测与星流视频桥适配器。
- `backend/app/services/provider_registry.py`：Provider 目录、健康路由、回退候选和策略版本。
- `docs/architecture.md`：编排层边界、状态机与扩展规则。
- `docker-compose.yml`：PostgreSQL、Redis、API、Worker、Web 与可选 Duix 服务。

## Production Platform Foundation

Phase 2 在既有 Runtime、Capability、Workflow 与 Provider 合同外新增平台控制面，不改变这些核心边界：

- Identity：开发模式显式使用受信头；生产模式使用 OIDC/JWT（JWKS、issuer、audience、时间声明、算法白名单）或独立 Service Principal。角色与权限由统一关系模型和授权服务解析。
- Tenant isolation：API/Worker 使用非 owner、`NOSUPERUSER NOBYPASSRLS` 的数据库运行角色；37 张 tenant-owned 表启用 FORCE RLS。Migration 单独使用 owner 凭据。
- Storage：业务只保存 `asset://backend/key`；local 与 S3-compatible 共用同一合同，Provider 路径只在 staging/promotion adapter 内出现。
- Metering：不可变 UsageFact、版本化 PriceBook/PricingRule、Quota reservation 和 append-only Ledger 分层保存；未配置价格时只记录用量，不伪造金额。
- Operations：`/health/live` 只检查进程，`/health/ready` 实查 PostgreSQL revision、Redis、Storage 和生产配置；`/metrics` 导出 HTTP、Outbox、dead letter 与 quota 指标。

生产环境必须设置 `AUTH_MODE=oidc` 及 OIDC 参数、稳定的 `SERVICE_PRINCIPAL_PEPPER`、对象存储凭据，并分别提供 `DATABASE_URL`（非特权 runtime role）和 `MIGRATION_DATABASE_URL`（migration owner）。

## 本地启动

### 前端

```bash
npm install
npm run dev
```

### 后端基础设施与迁移

先复制 `.env.example` 为 `.env`、`backend/.env.example` 为 `backend/.env`，然后启动 PostgreSQL 与 Redis。

```bash
docker compose up -d postgres postgres-runtime-role redis
cd backend
.venv/Scripts/alembic upgrade head
```

Compose 全栈会先幂等创建 `xingliu_runtime` 运行角色，再由独立 `migrate` service 使用 owner 连接升级 schema；API/Worker 不使用 owner 连接。只运行本地 Alembic 时，`backend/.env` 的 `MIGRATION_DATABASE_URL` 应指向 owner，`DATABASE_URL` 应指向 runtime role。

需要验证 S3-compatible adapter 时显式启动 MinIO profile：

```bash
docker compose --profile object-storage up -d minio minio-init
```

### API 与 Worker

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/uvicorn app.main:app --reload --port 8000
.venv/Scripts/python -m app.worker
```

### 使用云端模型大脑

日常配置从管理端 `/admin` 的「AI 能力与通道」完成：填写 New API 地址与 Token、测试连接、选择模型并绑定 `reasoning.default` / `writing.default` 等 alias。配置保存到 PostgreSQL 后会被下一次 Brain 调用动态读取，不需要重启 API 或 Worker。

`.env` 只保留系统级密钥加密主密钥，以及首次部署/故障回退时可选的 OpenAI-compatible bootstrap 网关：

```dotenv
AI_PROVIDER_SECRET_KEY=replace-with-one-stable-fernet-key
MODEL_GATEWAY_BASE_URL=https://your-new-api.example/v1
MODEL_GATEWAY_API_KEY=replace-with-server-side-key
MODEL_GATEWAY_DEFAULT_MODEL=your-internal-model-name
MODEL_GATEWAY_TIMEOUT_SECONDS=120
AGENT_OPERATION_LEASE_SECONDS=180
AGENT_OPERATION_RETRY_BASE_SECONDS=10
PLANNING_TIMEOUT_SECONDS=180
PLANNING_MAX_ATTEMPTS=3
```

管理员提交的 Provider Token 使用 Fernet 加密后入库，读取接口只返回末四位提示，不返回明文或密文。`AI_PROVIDER_SECRET_KEY` 必须由 API 与 Worker 共享并稳定保管；丢失后数据库中的 Token 无法解密。未配置数据库 Provider 或 bootstrap 网关时使用合同化模板规划器；配置后 `BrainPlanner` 结果仍必须通过 `agent.plan.v1` 校验。每次真实调用都会保存模型 alias、Provider、Token、延迟、请求 ID、成功/失败和安全错误摘要；只有网关响应明确提供成本时才记录成本。

### 使用 Duix

本机现有 Duix 服务使用 `http://localhost:8383/easy`，并将宿主机目录挂载为容器内 `/code/data`。API/Worker 必须同时满足：

1. `DUIX_BASE_URL` 能访问 Duix；
2. `DUIX_HOST_DATA_ROOT` 与 Duix 当前 `/code/data` 的宿主机挂载源完全相同。

当前机器已检测到的挂载源是 `F:/tianlei/codex/xiangmu/Duix-Avatar/data/face2face`，示例环境文件已按此配置。不要移动该目录；部署到其他机器时只改环境变量。

也可以在确认 GPU、磁盘和端口空闲后，显式启动 Compose 中的可选 Duix 服务：

```bash
docker compose --profile duix up -d
```

Duix 镜像体积大且需要 NVIDIA GPU；不要在未确认硬件、磁盘和许可证前执行该命令。

开发编排链路时可设置 `DUIX_MOCK=true`，验证队列和状态机而不启动 GPU 推理。

## 使用 OpenTalking

OpenTalking 先以第二引擎接入。配置 `OPENTALKING_BASE_URL` 后，管理端会真实探测其 `/health` 与 `/models`；只有再部署星流管理的视频桥并设置 `OPENTALKING_RENDER_ENABLED=true`，它才会进入生产路由。

视频桥使用以下稳定异步合同，负责把 OpenTalking 的 avatar、model、session、录制与 offline bundle 细节封装起来：

- `POST /xingliu/render`：提交音频、参考素材、规格和 Provider options，返回 `job_id`。
- `GET /xingliu/render/{job_id}`：返回统一 `status/progress/result_url`。

未启用桥接器时，界面明确显示“待配置”，不会用演示结果冒充可用能力。

## Agent 客户接口

- `GET/POST /v1/projects`：Agent 项目。
- `GET/POST /v1/production-orders`：创建和查询长任务生产单。
- `GET /v1/production-orders/{id}`：返回当前 AgentRun、PlanVersion、DecisionRequest 和 ArtifactVersion。
- `POST /v1/production-orders/{id}/{pause|resume|cancel}`：持久化的任务控制。
- `PATCH /v1/production-orders/{id}/inputs`：补充脚本/音频/形象素材，创建新计划版本并原地续跑。
- `POST /v1/decisions/{id}/resolve`：结构化决策，支持批准计划、调整后重规划和取消。
- `GET /v1/artifacts/{id}/versions`：不可变产物版本。
- `POST /v1/artifact-versions/{id}/{approve|return}`：产物批准与退回。

## 执行网关与兼容接口

- `GET /health` / `GET /health/live`：进程存活检查。
- `GET /health/ready`：PostgreSQL、migration revision、Redis、Storage 与生产配置 readiness。
- `GET /metrics`：Prometheus 文本指标。
- `GET /v1/admin/operations/platform`：平台依赖、Runtime、Outbox 与 dead-letter 控制面。
- `GET /v1/admin/identity/{members|roles|service-principals}`：身份与权限控制面。
- `GET /v1/admin/{usage|pricing|quotas|ledger}`：计量、价格、配额与账本控制面。
- `GET/POST/PUT /v1/admin/ai-providers`：AI Provider 与模型 alias 控制面（租户 owner/admin）。
- `POST /v1/admin/ai-providers/test-connection`：保存前测试连接并读取真实模型目录。
- `POST /v1/admin/ai-providers/{id}/test`：使用已加密保存的 Token 复检连接。
- `GET /v1/admin/ai-providers/invocations`：Super-IP 业务级 Brain 调用事实与用量。
- `GET /v1/providers`：数字人 Provider、健康、能力、执行方式和默认路由。
- `POST /v1/providers/route-preview`：在不创建任务时预览实际路由决策。
- `POST /v1/assets/upload`：上传 Duix 可读取的音视频素材。
- `POST /v1/workflows/digital-human`：创建数字人渲染工作流。
- `GET /v1/workflows`：任务中心列表。
- `POST /v1/workflows/{id}/retry`：重新执行可重试任务。

## 业务对象接口

- `GET/POST/PATCH /v1/business/ip-profiles`：IP 大脑与版本。
- `GET/POST/PATCH /v1/business/campaigns`：营销活动。
- `GET/POST/PATCH /v1/business/content-projects`：内容项目、脚本和生产状态。

每个工作流都会保存路由候选、选中 Provider、执行方式、选择原因和策略版本。调整 `AVATAR_PROVIDER_ORDER` 或启用新的 Adapter，不需要改变内容项目和前端任务协议。

## 当前能力边界

已真实运行：生产单、异步可恢复规划、计划版本、决策、Outbox 恢复、数字人异步执行、产物版本、审核、租户边界，以及数据库驱动的 New API 控制面。Agent Core 按能力合同调度；普通 Brain 调用不依赖 External Executor。当前本地环境尚未录入真实 New API Token，因此没有伪造云端调用或用量；管理员保存真实网关后，规划与内容能力会动态使用该配置。

## 独立部署说明

本项目不依赖 ChatGPT 登录、OpenAI Sites、Cloudflare D1 或 R2。生产环境应配置自己的域名、用户认证、PostgreSQL、Redis 和 S3 兼容对象存储。
