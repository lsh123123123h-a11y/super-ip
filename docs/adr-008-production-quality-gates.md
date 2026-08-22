# ADR-008：Production Quality Gates

## Context

本地口头验证不能阻止错误进入 main。本阶段跨越认证、RLS、对象存储、计量和 migration，SQLite 或纯 unit test 无法证明 PostgreSQL policy、S3 adapter 和升级路径成立；同时必须防止新代码反向污染已封板 Runtime/Capability/Workflow/Provider 边界。

## Decision

- GitHub Actions 对 PR/main/本阶段分支执行单一 Alembic head、PostgreSQL 17 空库升级、非特权 runtime role 全量测试、Redis、MinIO S3、migration downgrade/re-upgrade、受支持旧基线升级、前端 lint/build 和 Compose config。
- PostgreSQL integration 不得在 CI skip；RLS 测试使用 `NOSUPERUSER NOBYPASSRLS` 非 owner 登录。
- 架构防回归测试检查 Agent Kernel 不导入 Provider/Workflow 实现、Provider 不写订单状态、Redis 不是业务事实、Capability key 不编码执行器技术，以及 OIDC/Storage adapter 边界。
- Readiness 实际检查 PostgreSQL、schema revision、Redis、生产配置与 active storage；Liveness 不依赖外部依赖。结构化日志贯穿 HTTP/Worker，统一 request/trace/tenant/principal 字段并递归脱敏；Prometheus 暴露 HTTP、Outbox、dead letter、quota reject 指标。

## Alternatives

- 仅跑快速 unit test：拒绝，无法覆盖数据库和对象存储语义。
- 依赖开发机已运行服务：拒绝，不可复现且会污染项目数据。
- 为绿色把 integration 标记 skip：拒绝。
- 本阶段引入完整 tracing/metrics 集群：拒绝，先冻结可导出的标准边界。

## Consequences

CI 时间和镜像下载增加，但关键平台不变量成为 merge gate。外部商业 OIDC/Provider 凭据不进入 CI；JWT 密码学与 adapter 用本地密钥验证，S3 用真实 MinIO API 验证。生产部署仍需使用实际 IdP/对象存储做环境 smoke。

## Invariants

- CI 只有单一 Alembic head，且从空库与受支持旧 baseline 都能到 head。
- 本阶段 migration 能 downgrade/re-upgrade，迁移不 import runtime side effects。
- PostgreSQL-only 测试在 CI 实际运行；不得减少既有 Runtime Foundation 测试。
- 前端不得用静态成功替代 readiness；Secret 不进入构建产物。
- PR 未通过质量门禁不得 merge，本 ADR 不授权自动 merge。

## Migration impact

CI 新增 PostgreSQL/Redis services 和可选 MinIO profile，先由 owner migration，再 bootstrap runtime role运行测试。Compose 增加幂等角色 bootstrap 与 readiness healthcheck。新增依赖限定为 PyJWT cryptographic validation、boto3 S3 adapter、prometheus-client 指标导出；Node 无新增依赖。

## Failure / recovery semantics

任一 migration、RLS、S3、测试、lint、build 或 Compose gate 失败即阻止合并。Readiness 依赖异常返回 503 并指出真实状态；liveness 仍可供编排器判断进程存活。CI 中断可从干净 runner 重跑，不依赖上次数据库或对象存储。Outbox/dead-letter 指标从 PostgreSQL 事实重建，Redis 不可用时不会报告虚假 ready。
