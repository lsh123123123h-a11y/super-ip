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

## 本地启动

### 前端

```bash
npm install
npm run dev
```

### 后端基础设施与迁移

先复制 `.env.example` 为 `.env`、`backend/.env.example` 为 `backend/.env`，然后启动 PostgreSQL 与 Redis。

```bash
docker compose up -d postgres redis
cd backend
.venv/Scripts/alembic upgrade head
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

模型、渠道和密钥由内部 New API 管理，星流只配置一个 OpenAI-compatible 网关入口：

```dotenv
MODEL_GATEWAY_BASE_URL=https://your-new-api.example/v1
MODEL_GATEWAY_API_KEY=replace-with-server-side-key
MODEL_GATEWAY_DEFAULT_MODEL=your-internal-model-name
MODEL_GATEWAY_TIMEOUT_SECONDS=120
AGENT_OPERATION_LEASE_SECONDS=180
AGENT_OPERATION_RETRY_BASE_SECONDS=10
PLANNING_TIMEOUT_SECONDS=180
PLANNING_MAX_ATTEMPTS=3
```

密钥只放后端环境变量，不进入浏览器、生产单或计划。未完整配置时使用合同化模板规划器；配置后 `BrainPlanner` 生成的结果仍必须通过 `agent.plan.v1` 校验。生产单 API 不等待模型响应：规划被保存为 `AgentOperation`，由 Worker 异步执行、租约恢复和有界重试。

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

- `GET /health`：业务 API 存活检查。
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

已真实运行：生产单、异步可恢复规划、计划版本、决策、Outbox 恢复、数字人异步执行、产物版本、审核和租户边界查询。Agent Core 已改为按能力合同调度，不包含数字人口播专用分支。New API 大脑端口已接通合同与异步 Operation，但尚未配置真实云密钥；Harness Executor Registry 已建立但尚未安装真实 Adapter；未安装的业务能力会进入 `manual_intervention`，不会伪造已完成。

## 独立部署说明

本项目不依赖 ChatGPT 登录、OpenAI Sites、Cloudflare D1 或 R2。生产环境应配置自己的域名、用户认证、PostgreSQL、Redis 和 S3 兼容对象存储。
