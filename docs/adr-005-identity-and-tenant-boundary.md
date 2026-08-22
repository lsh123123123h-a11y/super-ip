# ADR-005：Identity、Authorization 与 Tenant Boundary

## Context

开发期受信 `X-Tenant-Id` / `X-User-Id` 不能作为生产身份。仅依靠应用查询附加 `tenant_id` 也无法覆盖漏写过滤条件、后台任务和新增查询。Runtime Foundation 已封板，身份层必须在其外侧解析 Principal，不能把 IdP、角色判断或租户选择塞进 Capability、Workflow 或 Provider。

## Decision

- `AUTH_MODE=development|oidc` 是显式适配器选择；OIDC 模式只接受 Bearer JWT，验证 JWKS 签名、issuer、audience、exp、nbf 与算法白名单，并拒绝租户身份头。
- 外部身份通过 `(issuer, subject)` 映射 `ExternalIdentity → User → Membership → Role → Permission`。生产模式不从请求声明静默创建 Membership；Service Principal 使用独立模型、散列 Secret、声明权限和认证审计，不伪装 User。
- 所有管理和业务 mutation 通过统一 `AuthorizationService` permission gate。内置 owner/admin/member/viewer 权限矩阵写入关系表，前端仅展示控制面，后端仍是授权事实来源。
- 37 张 tenant-owned 表统一 `ENABLE/FORCE ROW LEVEL SECURITY`。策略读取事务级 `app.tenant_id`；API Session 禁止 system context，Worker 显式使用 system context。
- Migration 使用 owner URL；API/Worker 使用 `NOSUPERUSER NOBYPASSRLS` 且不是表 owner 的 runtime role。Compose 通过幂等 bootstrap SQL 创建并授权该角色。超级用户不能用来证明 RLS 生效。

Tenant-owned 清单：`memberships`、`service_principals`、`authentication_audit_events`、`projects`、`content_items`、`ip_profiles`、`campaigns`、`content_projects`、`ip_profile_snapshots`、`production_orders`、`agent_runs`、`agent_operations`、`plan_versions`、`agent_step_executions`、`agent_step_artifact_inputs`、`decision_requests`、`artifacts`、`artifact_versions`、`quality_evaluations`、`agent_events`、`outbox_events`、`assets`、`asset_refs`、`consent_snapshots`、`workflow_runs`、`step_attempts`、`provider_jobs`、`workflow_route_decisions`、`ai_provider_configs`、`ai_model_bindings`、`ai_invocations`、`usage_facts`、`price_books`、`pricing_rules`、`tenant_quotas`、`usage_reservations`、`ledger_entries`。

Global/system 表包括 `tenants`、`users`、`external_identities`、`permissions`、`roles`、`role_permissions`、`alembic_version`、`capability_catalog_entries`、`consumed_events`；它们不携带可由普通租户任意选择的 tenant scope。

## Alternatives

- 继续信任请求头：拒绝，生产环境可直接冒充租户。
- 每条 ORM 查询手写 tenant filter：保留为第一道防线，但不能替代数据库隔离。
- 在本阶段绑定单一 IdP SDK：拒绝；通用 OIDC adapter 足以形成可替换边界。
- API 与 Migration 共用 owner/superuser：拒绝；会使 FORCE RLS 的验收失真。

## Consequences

部署必须分别管理 migration 与 runtime 数据库凭据，并在 IdP 中稳定提供 tenant claim。权限变更动态从数据库读取，增加一次小型关系查询；Service Principal Secret 仅创建时返回一次。自定义 PostgreSQL GUC 由受控 Session 写入，应用 SQL 注入防护仍是安全前提。

## Invariants

- OIDC 模式不读取 tenant/user/role 请求头。
- Principal 必须由认证适配器产生；授权只使用统一 permission service。
- tenant-owned 表同时有应用过滤、复合租户约束和 RLS。
- 普通 runtime 连接永远不是 owner、superuser 或 `BYPASSRLS`。
- Worker bypass 只能由显式 system Session 获得；Service Principal 只能获得声明权限。
- Secret、JWT 和凭据不进入日志或读取响应。

## Migration impact

`20260822_0012` 新增外部身份、权限、角色、服务身份与认证审计表，为旧 Membership 回填 role，并为既有 business 表补 tenant ownership、索引与跨租户保护。部署顺序为：运行角色 bootstrap → owner 执行 Alembic → API/Worker 用 runtime role 启动。OIDC 上线前必须先建立外部身份与 Membership 映射。

## Failure / recovery semantics

JWKS、声明或 Membership 不可用时请求返回 401/403，不回退到受信头。运行角色或 tenant GUC 缺失时 RLS 返回空集/拒绝写入，不自动开启 bypass。Worker 恢复扫描使用显式 system Session，仍受既有 lease、fence、幂等与 Outbox 规则约束。角色 bootstrap 可幂等重跑；迁移失败时保持上一 revision 并禁止 readiness 通过。
