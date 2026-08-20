# 超级 IP 营销 AI：数字人编排架构

## 1. 边界

产品是独立 Web 应用，不依赖 ChatGPT 容器、ChatGPT 登录或 OpenAI Sites。业务层只调用自有 API；Duix 是首个数字人执行引擎，不直接暴露给浏览器。

```text
Web 工作台
    ↓
业务 API（账号、作品、任务、资产）
    ↓
工作流编排层（状态机、幂等、重试、审计）
    ↓
数字人能力网关（统一 Provider 契约）
    ↓
Duix 离线渲染；以后可并列 OpenTalking/云厂商
```

## 2. 为什么不能让前端直连 Duix

Duix 只负责“音频 + 参考视频 → 数字人口播视频”。商业产品还需要保存任务、排队、重试、隔离用户、记录作品版本、管理配额和处理失败退款。这些都属于自有编排层，不能塞进 Duix Provider。

Provider 的职责被限制为：

- 把统一请求转换为 Duix `/easy/submit` 参数；
- 轮询 `/easy/query` 并归一化进度、成功和失败；
- 隐藏 Duix 错误码、容器路径和接口差异；
- 返回标准结果，不写业务订单或用户状态。

## 3. 当前工作流

工作流类型：`digital_human.render`

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

数据库中的 `workflow_runs` 是任务事实来源，`workflow_steps` 保存步骤级进度与尝试次数，`provider_jobs` 保存每次 Duix 调用。Redis 只运输任务 ID，即使 Redis 重启，数据库任务仍然存在。

## 4. 编排可靠性规则

- 创建任务使用 `(owner_id, idempotency_key)` 唯一约束。
- Worker 用数据库行锁领取任务，避免多个 Worker 同时执行同一条工作流。
- 每次重试生成新的 Duix 外部任务号：`{workflow_id}-{attempt}`。
- Duix 的 `10004 任务不存在` 在刚提交后可能是短暂可见性延迟；允许有限次数轮询，超过阈值才失败。
- 失败保留错误码、错误消息、步骤状态和 Provider 原始响应。
- Duix 与 API 通过同一宿主机共享目录交换素材；业务 API 只下发 Duix 容器内路径。

## 5. 后续扩展方式

接入 OpenTalking 或其他数字人服务时，新增 Provider，不修改营销业务工作流的对外协议。网关根据场景选择：

- Duix：离线批量成片、成本可控、本地数据；
- OpenTalking：实时互动、直播或会话式数字人；
- 云 Provider：突发扩容与高规格成片。

下一阶段应依次补充用户认证/租户隔离、对象存储、配额与计费账本、任务取消和超时补偿、内容生产工作流，以及发布渠道适配器。
