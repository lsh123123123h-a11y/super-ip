# 星流 AI · 超级 IP 营销工作台

独立部署的超级 IP 营销应用。当前首条真实生产链路聚焦：

`上传参考视频与配音 → 创建编排任务 → Duix 离线数字人渲染 → 任务中心查看进度`

## 目录

- `app/`：Next.js 独立 Web 前端。
- `backend/app/main.py`：FastAPI 业务 API。
- `backend/app/worker.py`：异步编排 Worker。
- `backend/app/providers/duix.py`：Duix Provider 适配器。
- `docs/architecture.md`：编排层边界、状态机与扩展规则。
- `docker-compose.yml`：PostgreSQL、Redis、API、Worker、Web 与可选 Duix 服务。

## 本地启动

### 前端

```bash
npm install
npm run dev
```

### 后端基础设施

先复制 `.env.example` 为 `.env`、`backend/.env.example` 为 `backend/.env`，然后启动 PostgreSQL 与 Redis。

```bash
docker compose up -d postgres redis
```

### API 与 Worker

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/uvicorn app.main:app --reload --port 8000
.venv/Scripts/python -m app.worker
```

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

## 网关接口

- `GET /health`：业务 API 存活检查。
- `GET /v1/providers`：数字人能力网关及 Duix 连通状态。
- `POST /v1/assets/upload`：上传 Duix 可读取的音视频素材。
- `POST /v1/workflows/digital-human`：创建数字人渲染工作流。
- `GET /v1/workflows`：任务中心列表。
- `POST /v1/workflows/{id}/retry`：重新执行可重试任务。

## 独立部署说明

本项目不依赖 ChatGPT 登录、OpenAI Sites、Cloudflare D1 或 R2。生产环境应配置自己的域名、用户认证、PostgreSQL、Redis 和 S3 兼容对象存储。
