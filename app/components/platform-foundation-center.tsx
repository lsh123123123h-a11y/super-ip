"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getPlatformSnapshot,
  LedgerEntry,
  listLedgerEntries,
  listPriceBooks,
  listServicePrincipals,
  listTenantMembers,
  listTenantQuotas,
  listTenantRoles,
  listUsageFacts,
  PlatformSnapshot,
  PriceBook,
  ServicePrincipal,
  TenantMember,
  TenantQuota,
  TenantRole,
  UsageFact,
} from "../lib/api";

export default function PlatformFoundationCenter({ view }: { view: "platform" | "identity" | "billing" }) {
  if (view === "platform") return <PlatformPanel />;
  if (view === "identity") return <IdentityPanel />;
  return <BillingPanel />;
}

function LoadState({ error, onRetry }: { error: string; onRetry: () => void }) {
  return <div className="admin-warning">{error}<button onClick={onRetry}>重试</button></div>;
}

function PlatformPanel() {
  const [snapshot, setSnapshot] = useState<PlatformSnapshot | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { setSnapshot(await getPlatformSnapshot()); setError(""); } catch (caught) { setError(caught instanceof Error ? caught.message : "平台状态读取失败"); } }, []);
  useEffect(() => { const initial = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(initial); }, [load]);
  if (error) return <LoadState error={error} onRetry={() => void load()} />;
  const components = snapshot ? Object.entries(snapshot.components) : [];
  return <div className="admin-page platform-foundation">
    <section className="admin-page-lead"><div><span>PRODUCTION PLATFORM</span><h2>平台概览来自实时依赖和恢复事实。</h2><p>Readiness、存储配置、Outbox 与 Dead Letter 均由后端返回；未配置项不会显示为正常。</p></div><b className={`admin-version ${snapshot?.status === "ready" ? "" : "warning"}`}>{snapshot?.status ?? "读取中"}</b></section>
    <section className="admin-zero-metrics">
      {components.map(([name, detail]) => <article key={name}><span>{name}</span><b>{detail.status}</b><small>{String(detail.backend ?? detail.schema_revision ?? detail.auth_mode ?? "实时探测")}</small></article>)}
    </section>
    <section className="admin-ledger-model"><h3>Outbox / Consumer Recovery</h3><div><span>01</span><b>待发布 {snapshot?.outbox.backlog ?? "—"}</b></div><div><span>02</span><b>Outbox 死信 {snapshot?.outbox.dead_letters ?? "—"}</b></div><div><span>03</span><b>Consumer 死信 {snapshot?.outbox.consumer_dead_letters ?? "—"}</b></div></section>
  </div>;
}

function IdentityPanel() {
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [roles, setRoles] = useState<TenantRole[]>([]);
  const [services, setServices] = useState<ServicePrincipal[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { const [m, r, s] = await Promise.all([listTenantMembers(), listTenantRoles(), listServicePrincipals()]); setMembers(m); setRoles(r); setServices(s); setError(""); } catch (caught) { setError(caught instanceof Error ? caught.message : "身份控制面读取失败"); } }, []);
  useEffect(() => { const initial = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(initial); }, [load]);
  if (error) return <LoadState error={error} onRetry={() => void load()} />;
  return <div className="admin-page platform-foundation">
    <section className="admin-page-lead"><div><span>IDENTITY & AUTHORIZATION</span><h2>成员、角色与机器身份是独立事实。</h2><p>生产 OIDC 不接受租户 Header；Service Principal 只获得显式声明的权限。</p></div></section>
    <section className="admin-table"><header><span>成员</span><span>Subject</span><span>角色</span><span>状态</span><span>加入时间</span></header>{members.map((item) => <article key={item.user_id}><div><b>{item.display_name || item.user_id}</b><small>{item.user_id}</small></div><span>{item.external_subject}</span><b>{item.role}</b><b>{item.status}</b><span>{new Date(item.created_at).toLocaleDateString()}</span></article>)}</section>
    <section className="admin-foundation-grid">{roles.map((role) => <article key={role.key}><span>{role.key.toUpperCase()}</span><h3>{role.name}</h3><p>{role.permissions.join(" · ")}</p><b>{role.permissions.length} permissions</b></article>)}</section>
    <section className="admin-table"><header><span>Service Principal</span><span>Client ID</span><span>权限</span><span>状态</span><span>最近认证</span></header>{services.length ? services.map((item) => <article key={item.id}><div><b>{item.name}</b><small>{item.id}</small></div><span>{item.client_id}</span><span>{item.permissions.length}</span><b>{item.status}</b><span>{item.last_authenticated_at ? new Date(item.last_authenticated_at).toLocaleString() : "尚未使用"}</span></article>) : <div className="ai-usage-empty">尚未创建 Service Principal</div>}</section>
  </div>;
}

function BillingPanel() {
  const [usage, setUsage] = useState<UsageFact[]>([]);
  const [books, setBooks] = useState<PriceBook[]>([]);
  const [quotas, setQuotas] = useState<TenantQuota[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { const [u, p, q, l] = await Promise.all([listUsageFacts(), listPriceBooks(), listTenantQuotas(), listLedgerEntries()]); setUsage(u); setBooks(p); setQuotas(q); setLedger(l); setError(""); } catch (caught) { setError(caught instanceof Error ? caught.message : "计量控制面读取失败"); } }, []);
  useEffect(() => { const initial = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(initial); }, [load]);
  if (error) return <LoadState error={error} onRetry={() => void load()} />;
  return <div className="admin-page platform-foundation">
    <section className="admin-page-lead"><div><span>USAGE / PRICING / QUOTA / LEDGER</span><h2>用量事实与收费流水分离。</h2><p>Price Book 版本会固定到 Ledger；退款和修账只追加反向流水。</p></div></section>
    <section className="admin-zero-metrics"><article><span>Usage Facts</span><b>{usage.length}</b></article><article><span>Price Books</span><b>{books.length}</b></article><article><span>Active Quotas</span><b>{quotas.length}</b></article><article><span>Ledger Entries</span><b>{ledger.length}</b></article></section>
    <section className="admin-table"><header><span>Metric</span><span>数量</span><span>来源</span><span>Provider / Model</span><span>发生时间</span></header>{usage.slice(0, 20).map((item) => <article key={item.id}><b>{item.metric}</b><span>{String(item.quantity)} {item.unit}</span><span>{item.source_type}</span><span>{item.provider_id ?? item.model ?? "平台"}</span><span>{new Date(item.occurred_at).toLocaleString()}</span></article>)}</section>
    <section className="admin-foundation-grid">{books.map((book) => <article key={book.id}><span>V{book.version}</span><h3>{book.name}</h3><p>{book.rules.map((rule) => `${rule.metric}: ${rule.unit_price}/${rule.unit_size} ${rule.unit}`).join(" · ")}</p><b>{book.currency}</b></article>)}{quotas.map((quota) => <article key={quota.id}><span>{quota.period}</span><h3>{quota.metric}</h3><p>used {String(quota.used_quantity)} · reserved {String(quota.reserved_quantity)}</p><b>hard {quota.hard_limit === null ? "∞" : String(quota.hard_limit)}</b></article>)}</section>
    <section className="admin-table"><header><span>类型</span><span>金额</span><span>Metric</span><span>来源</span><span>Price Version</span></header>{ledger.slice(0, 20).map((item) => <article key={item.id}><b>{item.entry_type}</b><span>{String(item.amount)} {item.currency}</span><span>{item.metric ?? "—"}</span><span>{item.source_type}</span><span>{item.price_book_version ?? "—"}</span></article>)}</section>
  </div>;
}
