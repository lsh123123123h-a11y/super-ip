# New API 参考边界

观察日期：2026-08-20。

## 可以直接借鉴

- 渠道/密钥管理：服务商、Base URL、Key、多 Key 轮询、启停和连通测试。
- 逻辑模型：对用户暴露稳定模型别名，内部映射多个上游模型。
- 路由：优先级、权重、失败重试、自动禁用、用户/分组限流。
- 权限与商业化：用户、角色、分组、Token、模型权限、配额、充值、订阅。
- 计费：模型倍率、分组倍率、预消费/后消费、请求日志和成本统计。
- 运维：渠道健康、性能监控、错误日志、异步任务轮询与超时退款。

## 不应让 New API 承担

- IP 档案、营销活动、内容项目和作品版本。
- 数字人训练授权、形象/声音资产生命周期。
- 多步骤长任务的业务状态、人工复核、回退点和产物依赖。
- Duix/OpenTalking 的本地或自托管 Worker、GPU 调度、素材传输与成片持久化。
- 多平台账号授权、发布审核和营销数据回流。

## 推荐边界

```text
业务前端/管理端
       ↓
业务 API + 工作流编排（事实来源）
       ↓
能力网关 Capability Gateway
  ├─ LLM/Embedding/Image/通用音视频 API → New API（可选）
  ├─ 数字人视频 → Avatar/Media Job Router
  │    ├─ Duix Adapter → 本地/自托管 Worker 或商业云 API
  │    └─ OpenTalking Adapter → 自托管 Worker/远程推理
  ├─ 视频包装 → FFmpeg/云媒体 Adapter
  └─ 发布 → 各平台官方 Adapter / 本地受控桥
```

业务侧只认识能力名，不认识供应商模型名：

- `text.generate`
- `text.embed`
- `image.generate`
- `asr.transcribe`
- `speech.synthesize`
- `voice.clone`
- `avatar.render`
- `avatar.video_clone`
- `avatar.session.realtime`
- `video.compose`
- `video.generate`
- `publish.content`

通用 LLM/图片等能力默认使用云 API，不把 Ollama/vLLM 本地部署列入当前范围。数字人/媒体路由输入至少包含：租户策略、素材类型、授权、允许的执行位置、质量档、成本上限、期望时延、地域、所需能力、并发、Worker/通道健康和回退链。

## 关键判断

New API 可以先部署为通用模型渠道中心，但必须由本项目的业务编排与能力合同再包一层。原因是 OpenAI 兼容只统一了部分请求格式，并没有统一 Duix/OpenTalking 的形象素材、训练/预处理、异步状态、进度、取消、退款、产物和质量语义。

OpenTalking 最新官方说明已经包含视频创建和视频克隆，不再只按实时会话能力建模；但它是可插拔编排框架，并非默认具备商业云 API、计费和 SLA，因此需要独立 Adapter 与 Worker/远程推理部署评估。
