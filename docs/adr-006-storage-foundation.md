# ADR-006：Storage Foundation

## Context

既有 `asset://backend/key` 已把业务引用和本机路径初步分离，但上传、下载和 Provider 输出仍需要统一生命周期、对象存储和完整性语义。业务对象不能持久化 `F:\...`、`/code/data/...`，数据库 JSON 也不能承载二进制。

## Decision

- 冻结 `StorageBackend` 合同：`put/get/delete/exists/stat/copy/generate_download_url`，实现 `local` 与 S3-compatible 两个 adapter。
- `Asset` 与 `ArtifactVersion` 持久化 backend、key、media type、size、SHA-256；稳定引用继续使用 `asset://backend/key`。
- 上传先写任务级临时文件，再放入 active backend；数据库提交失败则补偿删除对象。下载先校验 tenant ownership；S3 使用短期 presigned URL，不能签名时才受控流式返回。
- Provider staging/promotion 是唯一允许解释容器或 Provider 路径的边界。输入在该边界下载并校验 checksum；输出在成功落业务 ArtifactVersion 前提升到稳定平台存储。
- MinIO 仅作为可选开发/CI S3-compatible profile，不成为生产架构依赖。

## Alternatives

- 保留共享盘为业务 locator：拒绝，部署拓扑会污染领域模型。
- 把文件或 base64 放进 PostgreSQL JSON：拒绝，破坏数据库与备份边界。
- 业务 Workflow 直接调用 boto3：拒绝，会让 Provider/Workflow 与存储实现耦合。
- 本阶段引入独立媒体服务：拒绝，当前 backend contract 足够且无需新增分布式系统。

## Consequences

本地开发仍可使用 local backend；生产切换 S3 不改变 Asset/Artifact 合同。跨 backend promotion 需要短暂本地 staging 和额外 I/O。应用数据库只保存 locator 与元数据，不保存 Storage Secret；S3 凭据由部署环境注入。

## Invariants

- 业务表和计划中不得出现宿主机/容器绝对路径。
- 对象 key 必须经过 traversal 校验并限定在 backend root/bucket。
- tenant 授权发生在生成下载 URL 或读取 bytes 之前。
- Provider 成功引用必须先 promotion，再创建可下载 ArtifactVersion。
- 二进制不进入 JSON/日志；Secret 不进入数据库业务配置或前端。

## Migration impact

`20260822_0012` 为 `artifact_versions` 增加 storage backend/key/media/size/checksum。现有 Asset locator 保持兼容；历史 ArtifactVersion 可以为空，只有新产物强制走 promotion。新增 boto3 仅用于 S3 adapter，MinIO 镜像只在显式 profile 与 CI 启动。

## Failure / recovery semantics

上传失败不创建 Asset；数据库提交失败尝试删除已写对象。对象不存在返回 404，backend 不可用返回 503，路径非法返回 400。Provider promotion 失败时 Workflow 进入既有有界 retry/manual 流程，不把 Provider 临时路径声明为正式产物。重复 promotion 使用稳定目标 key，可由同一 Workflow attempt 安全重试；孤儿对象通过后续运维对账清理，不在请求中递归扫描 bucket。
