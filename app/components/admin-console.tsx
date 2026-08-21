"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import ProviderControlCenter from "./provider-control-center";
import TaskCenter from "./task-center";
import { AvatarProvider, listAvatarProviders, listWorkflows, previewAvatarRoute, ProviderCatalog, ProviderRouteDecision, Workflow } from "../lib/api";

type AdminView = "overview" | "tenants" | "ledger" | "providers" | "routing" | "workers" | "operations" | "consent" | "governance" | "configuration" | "audit";

const adminNavigation: Array<{ label: string; items: Array<{ id: AdminView; icon: string; title: string }> }> = [
  { label: "运营中心", items: [{ id: "overview", icon: "⌂", title: "经营总览" }, { id: "tenants", icon: "人", title: "租户与用户" }, { id: "ledger", icon: "账", title: "套餐与账本" }] },
  { label: "能力平台", items: [{ id: "providers", icon: "能", title: "能力与通道" }, { id: "routing", icon: "路", title: "路由策略" }, { id: "workers", icon: "节", title: "媒体 Worker" }] },
  { label: "治理与运维", items: [{ id: "operations", icon: "任", title: "任务运维" }, { id: "consent", icon: "权", title: "资产与授权" }, { id: "governance", icon: "盾", title: "内容治理" }, { id: "configuration", icon: "配", title: "配置中心" }, { id: "audit", icon: "审", title: "审计与客服" }] },
];

const adminTitles: Record<AdminView, [string, string]> = {
  overview: ["OPERATION OVERVIEW", "经营总览"], tenants: ["TENANT & IDENTITY", "租户与用户"], ledger: ["PLAN & LEDGER", "套餐与账本"],
  providers: ["CAPABILITY CONTROL", "能力与通道"], routing: ["ROUTING POLICY", "路由策略"], workers: ["MEDIA WORKERS", "数字人 / 媒体 Worker"],
  operations: ["TASK OPERATIONS", "任务运维"], consent: ["ASSET & CONSENT", "资产与授权"], governance: ["CONTENT GOVERNANCE", "内容治理"],
  configuration: ["SYSTEM CONFIGURATION", "配置中心"], audit: ["AUDIT & SUPPORT", "审计与客服"],
};

export default function AdminConsole() {
  const [view, setView] = useState<AdminView>("overview");
  const [catalog, setCatalog] = useState<ProviderCatalog | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextCatalog, nextWorkflows] = await Promise.all([listAvatarProviders(), listWorkflows()]);
      setCatalog(nextCatalog);
      setWorkflows(nextWorkflows);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "管理数据读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { const initial = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(initial); }, [refresh]);

  return <main className="admin-shell">
    <aside className="admin-sidebar">
      <Link href="/admin" className="admin-brand"><span>星</span><div><b>星流控制台</b><small>ADMIN CONTROL PLANE</small></div></Link>
      <div className="admin-environment"><span className="online" /> <div><small>当前环境</small><b>本地生产预备环境</b></div></div>
      <nav aria-label="管理端主导航">{adminNavigation.map((group) => <section key={group.label}><p>{group.label}</p>{group.items.map((item) => <button className={view === item.id ? "active" : ""} onClick={() => setView(item.id)} key={item.id}><span>{item.icon}</span>{item.title}</button>)}</section>)}</nav>
      <div className="admin-sidebar-foot"><Link href="/">← 返回用户端</Link><div><span>AD</span><p><b>系统管理员</b><small>开发环境角色</small></p><i>···</i></div></div>
    </aside>
    <section className="admin-main">
      <header className="admin-topbar"><div><p>{adminTitles[view][0]}</p><h1>{adminTitles[view][1]}</h1></div><div><span className={`admin-api-state ${error ? "error" : ""}`}><i />{error ? "部分服务异常" : loading ? "读取系统状态" : "控制面已连接"}</span><button onClick={() => void refresh()}>↻ 刷新数据</button></div></header>
      {error && <div className="admin-warning">{error}</div>}
      {view === "overview" && <AdminOverview loading={loading} workflows={workflows} catalog={catalog} onNavigate={setView} />}
      {view === "tenants" && <TenantCenter />}
      {view === "ledger" && <LedgerCenter />}
      {view === "providers" && <ProviderControlCenter />}
      {view === "routing" && <RoutingCenter catalog={catalog} />}
      {view === "workers" && <WorkerCenter providers={catalog?.providers ?? []} onRefresh={refresh} />}
      {view === "operations" && <TaskCenter />}
      {view === "consent" && <AdminFoundationModule type="consent" />}
      {view === "governance" && <AdminFoundationModule type="governance" />}
      {view === "configuration" && <AdminFoundationModule type="configuration" />}
      {view === "audit" && <AdminFoundationModule type="audit" />}
    </section>
  </main>;
}

function AdminOverview({ loading, workflows, catalog, onNavigate }: { loading: boolean; workflows: Workflow[]; catalog: ProviderCatalog | null; onNavigate: (view: AdminView) => void }) {
  const metrics = useMemo(() => {
    const active = workflows.filter((item) => ["queued", "running", "waiting_provider"].includes(item.status)).length;
    const succeeded = workflows.filter((item) => item.status === "succeeded").length;
    const failed = workflows.filter((item) => item.status.startsWith("failed")).length;
    return { total: workflows.length, active, succeeded, failed, successRate: workflows.length ? Math.round(succeeded / workflows.length * 100) : 0, readyProviders: catalog?.providers.filter((item) => item.status === "ready").length ?? 0 };
  }, [workflows, catalog]);

  return <div className="admin-dashboard">
    <section className="admin-metrics">
      <article><span>工作流总量</span><b>{loading ? "—" : metrics.total}</b><small>来自真实任务表</small></article>
      <article><span>正在执行 / 排队</span><b>{loading ? "—" : metrics.active}</b><small>队列与 Provider 等待</small></article>
      <article><span>成功率</span><b>{loading ? "—" : `${metrics.successRate}%`}</b><small>{metrics.succeeded} 成功 · {metrics.failed} 失败</small></article>
      <article><span>生产可用通道</span><b>{loading ? "—" : metrics.readyProviders}</b><small>{catalog?.providers.length ?? 0} 个已注册 Provider</small></article>
    </section>
    <section className="admin-overview-grid">
      <article className="admin-system-panel"><header><div><span>PRODUCTION PIPELINE</span><h3>任务与能力状态</h3></div><button onClick={() => onNavigate("operations")}>进入任务运维 →</button></header><div className="admin-pipeline-bars"><div><span>成功</span><i><em style={{ width: `${metrics.total ? metrics.succeeded / metrics.total * 100 : 0}%` }} /></i><b>{metrics.succeeded}</b></div><div><span>执行中</span><i><em className="blue" style={{ width: `${metrics.total ? metrics.active / metrics.total * 100 : 0}%` }} /></i><b>{metrics.active}</b></div><div><span>失败</span><i><em className="red" style={{ width: `${metrics.total ? metrics.failed / metrics.total * 100 : 0}%` }} /></i><b>{metrics.failed}</b></div></div><footer>这里只汇总真实 Workflow，不生成虚构收入或 GMV。</footer></article>
      <article className="admin-readiness"><header><div><span>SAAS READINESS</span><h3>上线准备度</h3></div></header>{[["数字人编排与任务",true],["独立用户端 / 管理端",true],["租户、登录与 RBAC",false],["额度账本与退款",false],["授权证据与内容治理",false]].map(([label, ready]) => <div key={String(label)}><span className={ready ? "done" : "pending"}>{ready ? "✓" : "!"}</span><b>{label}</b><small>{ready ? "已形成第一阶段能力" : "后端事实对象待建设"}</small></div>)}</article>
    </section>
    <section className="admin-provider-strip"><div><span>能力网关</span><b>{catalog?.policy_version ?? "读取中"}</b></div>{catalog?.providers.map((provider) => <article key={provider.provider_id}><span className={provider.status} /><div><b>{provider.label}</b><small>{provider.status === "ready" ? "可进入生产路由" : provider.reason || "等待配置"}</small></div></article>)}<button onClick={() => onNavigate("providers")}>管理能力通道 →</button></section>
  </div>;
}

function TenantCenter() {
  return <div className="admin-page"><section className="admin-page-lead"><div><span>TENANT BOUNDARY</span><h2>租户、成员与权限必须成为独立事实。</h2><p>当前 API 仍使用 <code>local-user</code>，所以这里明确展示开发态边界，不伪造多租户能力。</p></div><button disabled>＋ 新建租户</button></section><section className="admin-table"><header><span>租户 / 工作空间</span><span>成员</span><span>计划</span><span>状态</span><span>操作</span></header><article><div><b>本地开发工作空间</b><small>owner_id: local-user</small></div><span>1</span><span>未绑定套餐</span><b className="warning">开发模式</b><button>查看边界</button></article></section><aside className="admin-next-block"><b>后端建设顺序</b><div><span>01</span>Tenant / Workspace</div><div><span>02</span>User / Membership / Role</div><div><span>03</span>RBAC 与高风险操作审计</div><div><span>04</span>数据导出、删除与冻结</div></aside></div>;
}

function LedgerCenter() {
  return <div className="admin-page"><section className="admin-page-lead"><div><span>IMMUTABLE LEDGER</span><h2>额度、成本和退款不能只存在 Provider 日志里。</h2><p>账本尚未启用，因此管理端不显示虚构余额、收入和毛利。</p></div><button disabled>创建套餐</button></section><section className="admin-zero-metrics"><article><span>预占额度</span><b>未启用</b></article><article><span>实际扣减</span><b>未启用</b></article><article><span>失败释放</span><b>未启用</b></article><article><span>退款流水</span><b>未启用</b></article></section><section className="admin-ledger-model"><h3>生产账本事件</h3>{["reserve · 任务受理时预占","capture · 成功后按真实用量扣减","release · 失败或取消时释放","refund · 售后补偿与退款","adjustment · 管理员调整并强制审计"].map((item, index) => <div key={item}><span>{String(index + 1).padStart(2,"0")}</span><b>{item}</b></div>)}</section></div>;
}

function RoutingCenter({ catalog }: { catalog: ProviderCatalog | null }) {
  const [decision, setDecision] = useState<ProviderRouteDecision | null>(null);
  const [message, setMessage] = useState("");
  async function preview(provider: "auto" | "duix" | "opentalking") { try { const next = await previewAvatarRoute({ provider }); setDecision(next); setMessage(""); } catch (caught) { setDecision(null); setMessage(caught instanceof Error ? caught.message : "路由不可用"); } }
  return <div className="admin-page"><section className="admin-page-lead"><div><span>VERSIONED ROUTING</span><h2>路由策略决定“谁来执行”，业务项目不绑定模型。</h2><p>当前优先顺序来自环境配置；策略编辑和灰度发布 API 尚未建设。</p></div><b className="admin-version">{catalog?.policy_version ?? "读取中"}</b></section><section className="admin-route-layout"><article><span>当前 Provider 优先级</span><div className="admin-route-chain">{catalog?.priority.map((item, index) => <div key={item}><i>{index + 1}</i><b>{item}</b><small>{catalog.providers.find((provider) => provider.provider_id === item)?.status ?? "unknown"}</small></div>)}</div></article><article><span>实时路由预演</span><div className="admin-route-buttons"><button onClick={() => void preview("auto")}>自动选择</button><button onClick={() => void preview("duix")}>指定 Duix</button><button onClick={() => void preview("opentalking")}>指定 OpenTalking</button></div>{decision && <div className="admin-decision"><small>最终选择</small><b>{decision.selected_provider} · {decision.selected_execution}</b><p>{decision.reason}</p></div>}{message && <div className="admin-decision error">{message}</div>}</article></section></div>;
}

function WorkerCenter({ providers, onRefresh }: { providers: AvatarProvider[]; onRefresh: () => Promise<void> }) {
  return <div className="admin-page"><section className="admin-page-lead"><div><span>MEDIA EXECUTION NODES</span><h2>节点健康、版本和维护状态属于管理端。</h2><p>当前通过 Provider 探测呈现真实可达性；GPU、心跳和队列深度仍需 Worker 注册表。</p></div><button onClick={() => void onRefresh()}>重新探测</button></section><section className="admin-worker-grid">{providers.map((provider) => <article key={provider.provider_id}><header><span className={provider.status} /><div><small>{provider.provider_id}</small><h3>{provider.label}</h3></div><b>{provider.status === "ready" ? "ONLINE" : "SETUP"}</b></header><dl><div><dt>执行方式</dt><dd>{provider.execution_modes.join(" / ")}</dd></div><div><dt>能力数量</dt><dd>{provider.capabilities.length}</dd></div><div><dt>生产路由</dt><dd>{provider.render_ready ? "允许" : "禁止"}</dd></div><div><dt>健康探测</dt><dd>{provider.probe.reachable === true ? "已连通" : "未连通"}</dd></div></dl><footer>{provider.reason || "节点可用于数字人生产任务"}</footer></article>)}</section></div>;
}

function AdminFoundationModule({ type }: { type: "consent" | "governance" | "configuration" | "audit" }) {
  const content = {
    consent: { title: "形象、声音与素材授权", note: "数字人生成必须绑定授权快照、期限、用途与撤回状态。", items: ["数字人形象授权记录","声音克隆授权记录","素材版权与来源","到期、撤回与删除任务"] },
    governance: { title: "内容治理与生成标识", note: "敏感规则、AI 标识和投诉处理应该贯穿生成与发布。", items: ["敏感词与绝对化用语","AI 生成内容标识","违规冻结与人工复核","投诉、举报与申诉"] },
    configuration: { title: "版本化系统配置", note: "Prompt、工作流和模板不能散落在代码或前端常量中。", items: ["Prompt 模板与版本","工作流定义与灰度","字幕 / 封面模板","功能开关与租户策略"] },
    audit: { title: "审计、客服与用户时间线", note: "高风险操作和售后处理必须能回放完整事实链。", items: ["管理员操作审计","用户任务与账本时间线","失败补偿与人工介入","工单、公告和申诉"] },
  }[type];
  return <div className="admin-page"><section className="admin-page-lead"><div><span>FOUNDATION MODULE</span><h2>{content.title}</h2><p>{content.note}</p></div><b className="admin-not-ready">后端待建设</b></section><section className="admin-foundation-grid">{content.items.map((item, index) => <article key={item}><span>{String(index + 1).padStart(2,"0")}</span><h3>{item}</h3><p>已进入管理端信息架构；完成事实对象、权限与审计后开放操作。</p><b>PLANNED</b></article>)}</section></div>;
}
