"use client";

import { useCallback, useEffect, useState } from "react";
import { AvatarProvider, listAvatarProviders, ProviderCatalog } from "../lib/api";

const statusText: Record<AvatarProvider["status"], string> = {
  ready: "可用于生产路由",
  setup_required: "等待配置",
  unavailable: "当前不可达",
};

export default function ProviderControlCenter() {
  const [catalog, setCatalog] = useState<ProviderCatalog | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setCatalog(await listAvatarProviders());
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "能力网关读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(initial);
  }, [refresh]);

  return (
    <div className="module-view">
      <section className="module-intro compact">
        <div>
          <span className="section-kicker">ADMIN · CAPABILITY CONTROL</span>
          <h2>数字人能力管理</h2>
          <p>查看 Provider、执行方式、健康状态和自动路由结果；这里展示真实配置，不模拟可用状态。</p>
        </div>
        <button className="module-action" onClick={() => void refresh()} disabled={loading}>{loading ? "检查中…" : "重新检查"}</button>
      </section>

      {error && <div className="task-error">后端暂不可用：{error}</div>}
      {catalog && <>
        <section className="gateway-summary panel">
          <div><span>能力合同</span><b>{catalog.capability}</b></div>
          <div><span>策略版本</span><b>{catalog.policy_version}</b></div>
          <div><span>优先顺序</span><b>{catalog.priority.join(" → ")}</b></div>
          <div><span>默认选择</span><b>{"selected_provider" in catalog.default_route ? catalog.default_route.selected_provider : "无可用路由"}</b></div>
        </section>

        <section className="provider-admin-grid">
          {catalog.providers.map((provider) => (
            <article className={`provider-admin-card ${provider.status}`} key={provider.provider_id}>
              <header><div><span>{provider.category}</span><h3>{provider.label}</h3></div><b>{statusText[provider.status]}</b></header>
              <p>{provider.reason || "适配器已就绪，可被自动或显式路由选择。"}</p>
              <dl>
                <div><dt>接入阶段</dt><dd>{provider.integration_state}</dd></div>
                <div><dt>执行方式</dt><dd>{provider.execution_modes.join(" / ")}</dd></div>
                <div><dt>健康探测</dt><dd>{provider.probe.reachable === true ? "已连通" : provider.probe.reachable === false ? "未连通" : "未探测"}</dd></div>
              </dl>
              <div className="capability-tags">{provider.capabilities.map((capability) => <span key={capability}>{capability}</span>)}</div>
            </article>
          ))}
        </section>

        <aside className="admin-boundary-note">
          <b>当前边界</b>
          <p>Duix 保持生产主链；OpenTalking 已进入可探测、可配置的 Adapter 位置，视频桥接服务未启用前不会进入生产路由。后续可以调整优先顺序，不需要修改内容项目或前端任务结构。</p>
        </aside>
      </>}
    </div>
  );
}
