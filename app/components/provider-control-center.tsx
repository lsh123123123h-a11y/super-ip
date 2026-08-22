"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AIConnectionResult,
  AIInvocationPage,
  AIProvider,
  AIProviderWrite,
  AvatarProvider,
  createAIProvider,
  listAIInvocations,
  listAIProviders,
  listAvatarProviders,
  ProviderCatalog,
  setAIProviderEnabled,
  testAIProviderConnection,
  testSavedAIProvider,
  updateAIProvider,
} from "../lib/api";

const providerStatus: Record<AIProvider["status"], string> = {
  ready: "连接正常",
  untested: "等待检测",
  error: "连接异常",
  disabled: "已停用",
};

const mediaStatus: Record<AvatarProvider["status"], string> = {
  ready: "可用于生产路由",
  setup_required: "等待配置",
  unavailable: "当前不可达",
};

const aliasLabels: Record<string, string> = {
  "reasoning.default": "推理 / 规划",
  "writing.default": "内容生成",
  "evaluation.default": "质量评价",
  "vision.default": "视觉理解",
};

type ProviderForm = {
  name: string;
  baseUrl: string;
  apiKey: string;
  defaultModel: string;
  timeoutSeconds: number;
  aliases: Record<string, string>;
};

const emptyForm = (): ProviderForm => ({
  name: "New API 主网关",
  baseUrl: "",
  apiKey: "",
  defaultModel: "",
  timeoutSeconds: 120,
  aliases: {
    "reasoning.default": "",
    "writing.default": "",
    "evaluation.default": "",
    "vision.default": "",
  },
});

function formatNumber(value: number | null | undefined) {
  return value == null ? "—" : new Intl.NumberFormat("zh-CN").format(value);
}

function formatTime(value: string | null) {
  if (!value) return "尚无记录";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export default function ProviderControlCenter() {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [invocations, setInvocations] = useState<AIInvocationPage | null>(null);
  const [mediaCatalog, setMediaCatalog] = useState<ProviderCatalog | null>(null);
  const [editing, setEditing] = useState<AIProvider | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ProviderForm>(emptyForm);
  const [connection, setConnection] = useState<AIConnectionResult | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    setBusy("refresh");
    try {
      const [nextProviders, nextInvocations, nextMedia] = await Promise.all([
        listAIProviders(),
        listAIInvocations(),
        listAvatarProviders(),
      ]);
      setProviders(nextProviders);
      setInvocations(nextInvocations);
      setMediaCatalog(nextMedia);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI Provider 控制面读取失败");
    } finally {
      setBusy("");
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(initial);
  }, [refresh]);

  const metrics = useMemo(() => ({
    ready: providers.filter((item) => item.status === "ready" && item.enabled).length,
    aliases: providers.reduce((total, item) => total + item.bindings.filter((binding) => binding.enabled).length, 0),
  }), [providers]);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm());
    setConnection(null);
    setError("");
    setNotice("");
    setShowForm(true);
  }

  function openEdit(provider: AIProvider) {
    const aliases = { ...emptyForm().aliases };
    for (const binding of provider.bindings) aliases[binding.model_alias] = binding.upstream_model;
    setEditing(provider);
    setForm({
      name: provider.name,
      baseUrl: provider.base_url,
      apiKey: "",
      defaultModel: provider.default_model,
      timeoutSeconds: provider.timeout_seconds,
      aliases,
    });
    setConnection(null);
    setError("");
    setNotice("");
    setShowForm(true);
  }

  function patchForm(values: Partial<ProviderForm>) {
    setForm((current) => ({ ...current, ...values }));
    setConnection(null);
  }

  async function testCandidate() {
    setBusy("test-candidate");
    setError("");
    setNotice("");
    try {
      const result = await testAIProviderConnection({
        provider_id: editing?.id,
        base_url: form.baseUrl,
        api_key: form.apiKey || undefined,
        timeout_seconds: Math.min(form.timeoutSeconds, 120),
      });
      const selected = form.defaultModel && result.models.includes(form.defaultModel) ? form.defaultModel : result.models[0] ?? "";
      setConnection(result);
      setForm((current) => ({
        ...current,
        defaultModel: selected,
        aliases: {
          ...current.aliases,
          "reasoning.default": current.aliases["reasoning.default"] || selected,
          "writing.default": current.aliases["writing.default"] || selected,
        },
      }));
      setNotice(`连接成功，网关返回 ${result.model_count} 个可用模型，耗时 ${result.latency_ms}ms。`);
    } catch (caught) {
      setConnection(null);
      setError(caught instanceof Error ? caught.message : "连接测试失败");
    } finally {
      setBusy("");
    }
  }

  function providerPayload(): AIProviderWrite {
    const aliases = Object.entries(form.aliases)
      .filter(([, model]) => model.trim())
      .map(([model_alias, upstream_model]) => ({ model_alias, upstream_model: upstream_model.trim(), enabled: true }));
    return {
      name: form.name.trim(),
      adapter_type: "new_api",
      base_url: form.baseUrl.trim(),
      ...(form.apiKey.trim() ? { api_key: form.apiKey.trim() } : {}),
      default_model: form.defaultModel,
      timeout_seconds: form.timeoutSeconds,
      enabled: editing?.enabled ?? true,
      bindings: aliases,
    };
  }

  async function saveProvider(event: FormEvent) {
    event.preventDefault();
    if (!connection?.ok) {
      setError("请先测试连接并从真实模型目录中选择模型");
      return;
    }
    setBusy("save");
    setError("");
    try {
      const saved = editing
        ? await updateAIProvider(editing.id, providerPayload())
        : await createAIProvider(providerPayload());
      try {
        await testSavedAIProvider(saved.id);
      } catch (caught) {
        setShowForm(false);
        const message = `配置已安全保存，但保存后复检失败：${caught instanceof Error ? caught.message : "连接异常"}`;
        await refresh();
        setError(message);
        return;
      }
      setShowForm(false);
      setNotice(`${saved.name} 已保存并动态生效。`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider 保存失败");
    } finally {
      setBusy("");
    }
  }

  async function testSaved(provider: AIProvider) {
    setBusy(`test-${provider.id}`);
    setError("");
    try {
      const result = await testSavedAIProvider(provider.id);
      setNotice(`${provider.name} 连接正常：${result.model_count} 个模型，${result.latency_ms}ms。`);
      await refresh();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "连接测试失败";
      await refresh();
      setError(message);
    }
  }

  async function toggleProvider(provider: AIProvider) {
    setBusy(`toggle-${provider.id}`);
    setError("");
    try {
      await setAIProviderEnabled(provider.id, !provider.enabled);
      setNotice(provider.enabled ? `${provider.name} 已停用。` : `${provider.name} 已启用，请重新测试连接。`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider 状态更新失败");
      setBusy("");
    }
  }

  return <div className="ai-control-page">
    <section className="ai-control-hero">
      <div><span>AI PROVIDER CONTROL PLANE</span><h2>AI 能力 / API 管理中心</h2><p>管理 Super-IP 到模型网关的连接、密钥和模型别名。New API 继续负责上游渠道与路由，业务代码只依赖 Brain / Capability 合同。</p></div>
      <button onClick={openCreate}>＋ 添加 New API</button>
    </section>

    {error && <div className="ai-control-message error">{error}</div>}
    {notice && <div className="ai-control-message success">{notice}</div>}

    <section className="ai-fact-metrics">
      <article><span>可用网关</span><b>{metrics.ready}</b><small>{providers.length} 个已配置</small></article>
      <article><span>模型别名绑定</span><b>{metrics.aliases}</b><small>按 Brain 用途动态解析</small></article>
      <article><span>真实调用</span><b>{formatNumber(invocations?.summary.request_count)}</b><small>{formatNumber(invocations?.summary.failure_count)} 次失败</small></article>
      <article><span>真实 Token</span><b>{formatNumber(invocations?.summary.total_tokens)}</b><small>输入 {formatNumber(invocations?.summary.input_tokens)} · 输出 {formatNumber(invocations?.summary.output_tokens)}</small></article>
      <article><span>平均延迟</span><b>{invocations?.summary.average_latency_ms == null ? "—" : `${invocations.summary.average_latency_ms}ms`}</b><small>仅汇总已完成调用</small></article>
    </section>

    {showForm && <form className="ai-provider-form" onSubmit={saveProvider}>
      <header><div><span>{editing ? "EDIT GATEWAY" : "NEW GATEWAY"}</span><h3>{editing ? `编辑 ${editing.name}` : "接入 New API / OpenAI 兼容网关"}</h3><p>API Key 只会提交给后端加密保存；编辑时留空表示保留现有密钥。</p></div><button type="button" onClick={() => setShowForm(false)}>×</button></header>
      <div className="ai-provider-fields">
        <label><span>显示名称</span><input value={form.name} onChange={(event) => patchForm({ name: event.target.value })} required /></label>
        <label className="wide"><span>Base URL</span><input value={form.baseUrl} onChange={(event) => patchForm({ baseUrl: event.target.value })} placeholder="https://new-api.example.com" required /></label>
        <label className="wide"><span>API Key {editing?.secret_hint ? `· 当前 ${editing.secret_hint}` : ""}</span><input type="password" autoComplete="new-password" value={form.apiKey} onChange={(event) => patchForm({ apiKey: event.target.value })} placeholder={editing ? "留空保留现有密钥" : "sk-..."} required={!editing} /></label>
        <label><span>调用超时</span><select value={form.timeoutSeconds} onChange={(event) => patchForm({ timeoutSeconds: Number(event.target.value) })}><option value={60}>60 秒</option><option value={120}>120 秒</option><option value={300}>300 秒</option><option value={600}>600 秒</option></select></label>
      </div>
      <div className="ai-test-row"><button type="button" onClick={() => void testCandidate()} disabled={busy === "test-candidate"}>{busy === "test-candidate" ? "正在连接…" : "测试连接并读取模型"}</button>{connection && <span>✓ {connection.model_count} 个模型 · {connection.latency_ms}ms</span>}</div>
      {connection && <div className="ai-model-mapping">
        <header><div><span>MODEL ALIAS ROUTING</span><h4>把 Agent 用途绑定到真实模型</h4></div><label><span>Provider 默认模型</span><select value={form.defaultModel} onChange={(event) => setForm((current) => ({ ...current, defaultModel: event.target.value }))}>{connection.models.map((model) => <option key={model} value={model}>{model}</option>)}</select></label></header>
        <div>{Object.entries(aliasLabels).map(([alias, label]) => <label key={alias}><span><b>{label}</b><code>{alias}</code></span><select value={form.aliases[alias]} onChange={(event) => setForm((current) => ({ ...current, aliases: { ...current.aliases, [alias]: event.target.value } }))}><option value="">暂不绑定</option>{connection.models.map((model) => <option key={model} value={model}>{model}</option>)}</select></label>)}</div>
      </div>}
      <footer><button type="button" onClick={() => setShowForm(false)}>取消</button><button className="primary" type="submit" disabled={!connection?.ok || busy === "save"}>{busy === "save" ? "保存并复检中…" : "保存并立即生效"}</button></footer>
    </form>}

    <section className="ai-provider-section">
      <header><div><span>GATEWAYS</span><h3>模型网关与别名</h3></div><button onClick={() => void refresh()} disabled={busy === "refresh"}>↻ 刷新事实</button></header>
      {providers.length === 0 ? <div className="ai-empty-provider"><b>还没有 AI Provider</b><p>添加 New API，测试连接后选择模型；随后 Agent 规划与内容生成会直接使用数据库配置。</p><button onClick={openCreate}>添加第一个网关</button></div> : <div className="ai-provider-list">{providers.map((provider) => <article key={provider.id} className={provider.status}>
        <header><div><span className="ai-provider-dot" /><div><small>NEW API · v{provider.config_version}</small><h4>{provider.name}</h4></div></div><b>{providerStatus[provider.status]}</b></header>
        <p>{provider.base_url}</p>
        <div className="ai-provider-aliases">{provider.bindings.map((binding) => <span key={binding.model_alias}><code>{binding.model_alias}</code><b>{binding.upstream_model}</b></span>)}</div>
        <dl><div><dt>API Key</dt><dd>{provider.secret_hint}</dd></div><div><dt>调用 / 失败</dt><dd>{provider.request_count} / {provider.failure_count}</dd></div><div><dt>Token</dt><dd>{formatNumber(provider.total_tokens)}</dd></div><div><dt>平均延迟</dt><dd>{provider.average_latency_ms == null ? "—" : `${provider.average_latency_ms}ms`}</dd></div></dl>
        {provider.last_error_message && <aside>{provider.last_error_code} · {provider.last_error_message}</aside>}
        <footer><span>最近调用：{formatTime(provider.last_invoked_at)}</span><div><button onClick={() => openEdit(provider)}>编辑</button><button onClick={() => void testSaved(provider)} disabled={busy === `test-${provider.id}`}>{busy === `test-${provider.id}` ? "检测中…" : "测试连接"}</button><button onClick={() => void toggleProvider(provider)}>{provider.enabled ? "停用" : "启用"}</button></div></footer>
      </article>)}</div>}
    </section>

    <section className="ai-usage-section">
      <header><div><span>REAL INVOCATIONS</span><h3>Brain 调用事实</h3></div><p>成本仅在网关响应明确返回时记录，不推算或虚构。</p></header>
      <div className="ai-usage-table"><header><span>时间 / 用途</span><span>Provider / 模型</span><span>Token</span><span>延迟</span><span>成本</span><span>结果</span></header>{invocations?.items.length ? invocations.items.map((item) => <article key={item.id}><div><b>{formatTime(item.started_at)}</b><small>{item.purpose} · {item.model_alias}</small></div><div><b>{item.provider_name}</b><small>{item.response_model || item.requested_model}</small></div><span>{formatNumber(item.total_tokens)}</span><span>{item.latency_ms == null ? "—" : `${item.latency_ms}ms`}</span><span>{item.cost_amount == null ? "未返回" : `${item.cost_amount} ${item.cost_currency || ""}`}</span><b className={item.success ? "ok" : item.success === false ? "failed" : "pending"}>{item.success ? "成功" : item.success === false ? "失败" : "进行中"}</b>{item.error_message && <small className="row-error">{item.error_code} · {item.error_message}</small>}</article>) : <div className="ai-usage-empty">完成一次真实 Agent Brain 调用后，这里会出现模型、Token、延迟、请求 ID 与错误事实。</div>}</div>
    </section>

    {mediaCatalog && <details className="ai-media-providers"><summary>现有媒体 / 数字人 Provider（{mediaCatalog.providers.length}）</summary><div>{mediaCatalog.providers.map((provider) => <article key={provider.provider_id}><span className={provider.status} /><div><b>{provider.label}</b><small>{provider.capabilities.join(" · ")}</small></div><em>{mediaStatus[provider.status]}</em></article>)}</div></details>}
  </div>;
}
