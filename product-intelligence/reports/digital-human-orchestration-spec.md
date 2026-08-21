# 数字人视频编排层规格草案

截至：2026-08-20｜状态：S4 架构决策草案｜不代表已实现

## 1. 编排层目标

同一个内容项目可以把数字人视频任务交给 Duix、OpenTalking、本地 GPU Worker、自托管服务器或商业云 API，而用户端、业务对象、审核流程和发布流程不发生分叉。

编排层必须统一解决八件事：

1. 输入素材和授权检查。
2. 能力匹配与 Provider/执行位置路由。
3. 长任务状态、进度与断点恢复。
4. 幂等、重试、超时、取消和补偿。
5. 中间产物与最终产物版本。
6. 预估成本、实际成本、扣费和退款。
7. 审片、退回指定步骤和增量重渲染。
8. Provider/Worker 健康、审计和人工接管。

## 2. 系统分层

```text
用户端 / 管理端
       ↓
Business API
Tenant / IP / Campaign / Project / Asset / Consent / Deliverable
       ↓
Workflow Orchestrator
步骤依赖、状态机、检查点、补偿、版本、人工审核
       ↓
Capability Gateway
统一能力合同、路由策略、Provider 选择、成本估算、回退链
       ├─ New API Adapter → LLM / Embedding / Image / 通用云 API
       ├─ Duix Adapter
       │    ├─ Local/Self-hosted Duix Worker
       │    └─ Duix Commercial Cloud API
       ├─ OpenTalking Adapter
       │    ├─ Self-hosted OpenTalking Worker
       │    └─ Remote inference / future hosted endpoint
       ├─ Media Compose Adapter → FFmpeg Worker / 云媒体 API
       └─ Publish Adapter → 抖音 / 导出包 / 调起发布
```

New API 不负责数字人项目状态。Duix/OpenTalking 原始任务 ID、步骤、日志和错误保存在 `provider_job`，业务工作流只使用统一状态。

## 3. 核心业务对象

| 对象 | 职责 | 不应包含 |
|---|---|---|
| `content_project` | 一次内容生产的业务容器 | Provider 原始字段 |
| `script_version` | 文案及平台变体版本 | 直接覆盖历史版本 |
| `asset` | 图片、音频、视频、形象、声音、模板 | 无租户/来源的孤儿文件 |
| `consent_snapshot` | 权利人、用途、期限、撤回状态 | 仅一个“已同意”布尔值 |
| `workflow_run` | 一次完整生产运行 | 供应商专属状态 |
| `workflow_step` | 可重试、可跳过、可审核的步骤 | 隐式前端进度 |
| `provider_job` | Duix/OpenTalking/New API 原始请求和状态 | 成为业务唯一事实来源 |
| `deliverable_version` | 可审核、可发布的成片版本 | 静默覆盖旧成片 |
| `ledger_entry` | 预占、实扣、释放、退款、算力成本 | 可修改余额字段代替流水 |

## 4. 数字人能力合同

### 4.1 能力名称

- `avatar.prepare`：形象训练、预处理或模板准备。
- `avatar.render`：音频/文本驱动数字人视频。
- `avatar.video_clone`：上传视频或摄像头驱动的动作/表演克隆。
- `avatar.session.realtime`：实时会话数字人，当前不进入首版主流程。
- `voice.clone`：声音克隆。
- `speech.synthesize`：文本转音频。
- `video.compose`：字幕、B-roll、BGM、封面、片头尾和比例包装。

### 4.2 `avatar.render` 统一输入

```json
{
  "tenant_id": "tenant_x",
  "project_id": "project_x",
  "avatar_asset_id": "asset_avatar_x",
  "audio_asset_id": "asset_audio_x",
  "script_version_id": "script_v3",
  "consent_snapshot_id": "consent_x",
  "output": {
    "aspect_ratio": "9:16",
    "resolution": "1080p",
    "background_mode": "source",
    "alpha_or_green_screen": false
  },
  "policy": {
    "allowed_providers": ["duix", "opentalking"],
    "allowed_execution": ["self_hosted", "cloud_api"],
    "quality_tier": "standard",
    "max_cost": null,
    "deadline_seconds": 3600
  }
}
```

### 4.3 统一输出

```json
{
  "provider_job_id": "pj_x",
  "status": "succeeded",
  "progress": 100,
  "output_asset_id": "asset_video_x",
  "duration_ms": 65320,
  "provider": "duix",
  "execution": "self_hosted",
  "estimated_cost": 1.20,
  "actual_cost": 1.08,
  "quality_metadata": {},
  "provider_metadata_ref": "encrypted://provider-job/pj_x"
}
```

业务表不直接保存 Duix/OpenTalking 的原始响应；原始响应加密保存并通过引用关联，供运维排障。

## 5. 工作流状态机

```text
draft
  → validating
  → queued
  → dispatching
  → running
  → awaiting_review
  → succeeded

任一执行状态可进入：
  retry_wait / paused / canceling / canceled / failed / manual_intervention
```

典型成片步骤：

```text
brief.freeze
→ script.generate
→ script.review
→ speech.synthesize
→ audio.review
→ avatar.render
→ video.compose
→ deliverable.review
→ publish.package
```

每个步骤保存 `input_snapshot`、`output_asset_ids`、`attempt`、`idempotency_key`、`provider_job_id` 和 `config_version`。修改字幕只重跑 `video.compose`，修改文案则从 `speech.synthesize` 起创建新分支，不覆盖已确认成片。

## 6. Duix 与 OpenTalking Adapter

### Duix Adapter

- 支持开源本地/自托管提交与进度查询。
- 商业云 API 作为独立 channel，不能假设与开源 API 字段、质量或价格相同。
- 映射形象预处理、音频驱动、进度轮询、结果下载、超时和失败代码。
- Phase 1 作为首个生产闭环，因为当前 ip-ai 已有 Duix 基础。

### OpenTalking Adapter

- 最新官方能力包含实时会话、视频创建和视频克隆。
- 它是编排框架，不是单一模型；Adapter 必须记录实际 talking-head backend 和版本。
- Phase 2 先验证 `avatar.render` 与 `avatar.video_clone`，实时会话留作后续能力。
- 若后端通过远程推理服务执行，仍由同一 `provider_job` 记录远程任务和回调。

### 双引擎基准

用同一组 10 个素材/音频/脚本比较：

- 输入预处理耗时。
- 端到端成功率和失败类型。
- 首帧/总时延。
- 口型、身份、表情、动作和时间一致性。
- 1080P/竖屏/远景等场景适配。
- 单分钟完全成本和失败成本。
- 取消、重试和增量渲染能力。
- 授权、删除、数据保留和商用边界。

## 7. 本地/自托管 Worker 协议

Worker 不开放公网入站端口，由 Worker 主动连接控制面：

1. 使用设备身份注册，管理员批准后获得可吊销证书。
2. 周期上报引擎、版本、GPU/显存、并发、队列、磁盘和健康。
3. 通过长轮询/WebSocket 拉取匹配任务。
4. 使用短期签名 URL 下载被授权素材。
5. 按统一事件上报 `accepted/preparing/running/progress/uploading/succeeded/failed`。
6. 产物上传对象存储并提交哈希、时长、分辨率和引擎元数据。
7. 控制面验收产物后确认任务；失败或失联按策略重派或人工介入。

需要版本矩阵：`worker_version × adapter_version × engine_version × model/backend_version`。不兼容 Worker 进入维护状态，不继续接单。

## 8. 路由与回退

数字人路由输入：

- 能力：render / video clone / realtime。
- 形象和驱动素材类型。
- 授权允许的执行地域和方式。
- 分辨率、时长、比例、透明背景等硬约束。
- 租户套餐、优先级、质量档和成本上限。
- Provider/Worker 健康、队列、并发和预计完成时间。
- 已知质量基准与失败历史。

示例回退链：

```text
Duix self-hosted standard
  → Duix cloud standard
  → OpenTalking self-hosted compatible backend
  → manual_intervention
```

是否允许自动跨引擎回退由任务策略决定。涉及形象重新训练、质量明显变化或额外费用时，必须请求用户/管理员确认，不能静默切换。

## 9. 幂等、成本与可靠性

- `idempotency_key = tenant + workflow + step + input_hash + config_version`。
- 提交 Provider 前写 Outbox；Worker 接受后回写 Provider Job，避免“已扣费但任务不存在”。
- Webhook 和轮询都转换为内部事件；重复/乱序回调按版本号和状态转换表去重。
- 提交前预占额度；成功后按实际量结算；失败按收费规则释放或扣除可解释成本。
- 同一 Provider Job 只允许一个终态；人工修正必须新增审计事件，不直接改历史。
- 对象存储产物按租户、项目和版本隔离；下载使用短期 URL。

## 10. 管理端必须可操作的内容

- Capability、Provider、Channel 和 Worker 的启停与灰度。
- Duix/OpenTalking 版本、支持能力和兼容矩阵。
- 路由策略、回退链、成本上限和租户覆盖。
- 队列深度、成功率、P50/P95、失败分类和单位分钟成本。
- 单任务时间线、输入快照、Provider 原始状态、重试、取消、补偿和人工接管。
- 额度预占、实扣、释放、退款、供应商费用和自托管算力成本。
- 形象/声音授权到期、撤回、删除传播和违规冻结。

## 11. 轻语 IP 功能等价映射

| 轻语能力 | 本产品对应能力 | 实现方式 |
|---|---|---|
| IP 大脑 | 版本化 IP 档案/知识/禁区 | Business API＋云 LLM/RAG |
| 对标链接 | 链接提取、结构拆解、改写 | 平台 Adapter＋内容工作流 |
| 法务审查 | 发布前合规步骤 | 规则＋云模型＋人工审核 |
| 声音克隆 | Voice Asset/Consent/Provider Job | 云 API 或受控媒体 Worker |
| 数字人 V1/V2 | Duix/OpenTalking Channel/质量档 | 同一 `avatar.render` 合同 |
| 素材向量化 | 转写、标签、Embedding、语义检索 | 云 API＋资产索引 |
| 智能剪辑 | 字幕、B-roll、BGM、比例、模板 | Media Compose 工作流 |
| 封面标题 | 候选生成、模板、人工确认 | 云模型＋模板引擎 |
| 批量任务 | Workflow Batch/Queue | 编排器＋配额/并发 |
| 账号发布 | Platform Adapter/Publish Record | 官方 API 优先，受控降级 |
| 剪映草稿 | 可选编辑项目包 | 专用导出 Adapter |
| 本地数据库备份 | 租户数据导出与受控恢复 | SaaS 数据治理，不复制桌面文件结构 |

“完成”必须同时具备真实输入、任务状态、可用产物、成本记录和失败恢复；静态页面或前端倒计时不计完成。

## 12. Phase 1 验收边界

Phase 1 只要求 Duix 一条生产链，但接口从第一天按多 Provider 设计：

- 业务层没有 Duix 专属字段。
- `avatar.render` 合同和 Provider Adapter 分离。
- Worker/云 API 都映射为 `provider_job`。
- 任一步可恢复，重复提交不产生重复扣费。
- 10 个真实项目端到端成功率目标不低于 90%。
- 每个成片可追溯脚本、音频、形象、授权、引擎、配置、成本和审核版本。

OpenTalking 在 Phase 1 同期只做技术 Spike，不阻塞 Duix 闭环；通过双引擎基准后再进入正式生产路由。
