"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AgentProject,
  createAgentProject,
  createProductionOrder,
  getProductionOrder,
  listAgentProjects,
  listProductionOrders,
  ProductionOrder,
  ProductionOrderOverview,
  reviewAgentArtifact,
  resolveAgentDecision,
  updateProductionOrderInputs,
  uploadAsset,
} from "../lib/api";


const statusText: Record<ProductionOrder["status"], string> = {
  draft: "草稿",
  planning: "Agent 规划中",
  awaiting_plan_approval: "等待方案确认",
  queued: "等待 Agent 执行",
  running: "Agent 执行中",
  awaiting_decision: "需要你的决策",
  evaluating: "质量评价中",
  retry_wait: "等待重试",
  paused: "已暂停",
  canceling: "正在取消",
  canceled: "已取消",
  succeeded: "已完成",
  failed_retryable: "可恢复失败",
  failed_final: "最终失败",
  manual_intervention: "能力建设中",
};

const activeStatuses: ProductionOrder["status"][] = [
  "planning", "queued", "running", "evaluating", "retry_wait", "canceling",
];

const artifactStepText: Record<string, string> = {
  intent_spec: "理解目标与约束",
  strategy_proposal: "制定内容策略",
  script: "准备口播脚本",
  voice_audio: "准备与检查声音",
  avatar_video: "生成数字人口播画面",
  final_video: "合成可发布成片",
  delivery_package: "整理交付包",
};

export default function AgentProductionCenter({ onNotify }: { onNotify: (message: string) => void }) {
  const [projects, setProjects] = useState<AgentProject[]>([]);
  const [orders, setOrders] = useState<ProductionOrder[]>([]);
  const [projectId, setProjectId] = useState("");
  const [intent, setIntent] = useState("");
  const [mode, setMode] = useState<"many_confirmations" | "key_checkpoints" | "automatic">("key_checkpoints");
  const [selected, setSelected] = useState<ProductionOrderOverview | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resolving, setResolving] = useState("");
  const [supplying, setSupplying] = useState(false);
  const [reviewing, setReviewing] = useState("");
  const [materialScript, setMaterialScript] = useState("");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const idempotencyKey = useRef(crypto.randomUUID());

  const refresh = useCallback(async () => {
    try {
      const [nextProjects, nextOrders] = await Promise.all([listAgentProjects(), listProductionOrders()]);
      setProjects(nextProjects);
      setOrders(nextOrders);
      setProjectId((current) => current || nextProjects[0]?.id || "");
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Agent 生产数据读取失败");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selected || !activeStatuses.includes(selected.order.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getProductionOrder(selected.order.id);
        setSelected(next);
        await refresh();
      } catch {
        // The next manual refresh will surface a persistent API failure.
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [refresh, selected]);

  async function submit() {
    if (!intent.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      let targetProjectId = projectId;
      if (!targetProjectId) {
        const project = await createAgentProject({
          name: "我的 IP 内容项目",
          goal: "持续生产符合 IP 定位的可发布内容",
        });
        setProjects([project]);
        targetProjectId = project.id;
        setProjectId(project.id);
      }
      const overview = await createProductionOrder(
        {
          project_id: targetProjectId,
          title: intent.trim().slice(0, 60),
          intent_text: intent.trim(),
          automation_mode: mode,
          inputs: { deliverable: "9:16 数字人口播成片", target_platforms: ["抖音"] },
        },
        idempotencyKey.current,
      );
      idempotencyKey.current = crypto.randomUUID();
      setSelected(overview);
      setIntent("");
      await refresh();
      onNotify("生产单已交给 Agent");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生产单创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function openOrder(orderId: string) {
    try {
      setSelected(await getProductionOrder(orderId));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生产单读取失败");
    }
  }

  async function decide(decisionId: string, optionKey: string) {
    if (optionKey === "open_assets") {
      document.getElementById("agent-material-supply")?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
      return;
    }
    let payload: Record<string, unknown> = {};
    if (optionKey === "request_changes") {
      const instruction = window.prompt("请写下希望 Agent 调整的目标或约束：");
      if (!instruction?.trim()) return;
      payload = { instruction: instruction.trim() };
    }
    setResolving(decisionId);
    try {
      const overview = await resolveAgentDecision(decisionId, optionKey, payload);
      setSelected(overview);
      await refresh();
      onNotify("决策已交给 Agent 继续执行");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "决策提交失败");
    } finally {
      setResolving("");
    }
  }

  async function supplyMaterials() {
    if (!selected || !materialScript.trim() || !audioFile || !avatarFile) {
      setError("请同时选择口播脚本、配音音频和数字人参考视频");
      return;
    }
    setSupplying(true);
    setError("");
    try {
      const [audio, avatar] = await Promise.all([
        uploadAsset(audioFile, selected.order.project_id),
        uploadAsset(avatarFile, selected.order.project_id),
      ]);
      const overview = await updateProductionOrderInputs(selected.order.id, {
        script: materialScript.trim(),
        audio_asset_id: audio.asset_id,
        avatar_asset_id: avatar.asset_id,
        aspect_ratio: "9:16",
        quality: "720p",
      });
      setSelected(overview);
      setMaterialScript("");
      setAudioFile(null);
      setAvatarFile(null);
      await refresh();
      onNotify("素材已绑定，Agent 已从新计划继续生产");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生产素材提交失败");
    } finally {
      setSupplying(false);
    }
  }

  async function reviewArtifact(versionId: string, action: "approve" | "return") {
    let note = "";
    if (action === "return") {
      const instruction = window.prompt("请写下退回原因或修改要求：");
      if (!instruction?.trim()) return;
      note = instruction.trim();
    }
    if (!selected) return;
    setReviewing(versionId);
    try {
      await reviewAgentArtifact(versionId, action, note);
      setSelected(await getProductionOrder(selected.order.id));
      onNotify(action === "approve" ? "产物版本已批准" : "产物版本已退回");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "产物审核失败");
    } finally {
      setReviewing("");
    }
  }

  return <div className="agent-production-page">
    <section className="agent-intent-card">
      <div>
        <span className="ux-overline">GOAL-DRIVEN AGENT</span>
        <h2>告诉 Agent 你最终想交付什么</h2>
        <p>这不是聊天线程。提交后会形成可恢复的生产单、计划、决策请求和产物版本。</p>
      </div>
      <label>
        <span>项目</span>
        <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
          {!projects.length && <option value="">首次提交时自动创建项目</option>}
          {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
        </select>
      </label>
      <textarea
        aria-label="生产目标"
        value={intent}
        onChange={(event) => setIntent(event.target.value)}
        placeholder="例如：把我关于 AI 工作流的观点做成一条 60 秒数字人口播，表达克制、有方法感，最终给我可发布成片。"
      />
      <div className="agent-submit-row">
        <div className="ux-pill-choice">
          {([
            ["many_confirmations", "多确认"],
            ["key_checkpoints", "关键处确认"],
            ["automatic", "自动完成"],
          ] as const).map(([key, label]) => <button key={key} className={mode === key ? "active" : ""} onClick={() => setMode(key)}>{label}</button>)}
        </div>
        <button className="ux-primary" disabled={!intent.trim() || submitting} onClick={() => void submit()}>
          {submitting ? "Agent 正在接单…" : "创建生产单 →"}
        </button>
      </div>
      {error && <p className="form-error">{error}</p>}
    </section>

    <div className="agent-production-grid">
      <section className="agent-order-list">
        <header><div><span className="ux-overline">PRODUCTION ORDERS</span><h3>生产单</h3></div><button onClick={() => void refresh()}>刷新</button></header>
        {!orders.length && <div className="ux-empty-state"><span>✦</span><h3>还没有生产单</h3><p>从一个目标开始，Agent 会自行形成计划。</p></div>}
        {orders.map((order) => <button className={selected?.order.id === order.id ? "active" : ""} key={order.id} onClick={() => void openOrder(order.id)}>
          <span className={`agent-order-status ${order.status}`} />
          <div><b>{order.title}</b><small>{statusText[order.status]} · {new Date(order.updated_at).toLocaleString("zh-CN")}</small></div>
          <i>→</i>
        </button>)}
      </section>

      <section className="agent-order-detail">
        {!selected && <div className="ux-empty-state"><span>◎</span><h3>选择一张生产单</h3><p>这里显示 Agent 的结构化理解、当前计划、决策和产物。</p></div>}
        {selected && <>
          <header className="agent-detail-head"><div><span>{statusText[selected.order.status]}</span><h2>{selected.order.title}</h2><p>{selected.order.intent_text}</p></div><b>{selected.plan ? `PLAN V${selected.plan.version}` : "正在形成方案"}</b></header>
          {selected.decisions.filter((decision) => decision.status === "pending").map((decision) => <section className="agent-decision-card" key={decision.id}>
            <span>需要你的决策</span><h3>{decision.title}</h3><p>{decision.summary}</p><div>{decision.options.map((option) => <button className={option.key === decision.recommended_option ? "recommended" : ""} disabled={resolving === decision.id} onClick={() => void decide(decision.id, option.key)} key={option.key}>{option.label}</button>)}</div>
          </section>)}
          {selected.plan && ["awaiting_decision", "manual_intervention", "failed_retryable"].includes(selected.order.status) && <section className="agent-material-card" id="agent-material-supply">
            <header><div><span className="ux-overline">SUPPLY MATERIALS</span><h3>补齐素材后原地续跑</h3></div><small>自动生成 Plan V{selected.plan.version + 1}</small></header>
            <textarea value={materialScript} onChange={(event) => setMaterialScript(event.target.value)} placeholder="粘贴已确认的口播脚本…" />
            <div className="agent-material-files">
              <label><span>配音音频</span><input type="file" accept="audio/*" onChange={(event) => setAudioFile(event.target.files?.[0] || null)} /><small>{audioFile?.name || "WAV / MP3 / M4A"}</small></label>
              <label><span>数字人参考视频</span><input type="file" accept="video/*" onChange={(event) => setAvatarFile(event.target.files?.[0] || null)} /><small>{avatarFile?.name || "MP4 / MOV"}</small></label>
            </div>
            <button className="ux-primary" disabled={supplying} onClick={() => void supplyMaterials()}>{supplying ? "正在上传并重排计划…" : "提交素材并继续生产 →"}</button>
          </section>}
          {selected.plan ? <section className="agent-plan-card"><header><div><span className="ux-overline">AGENT PLAN</span><h3>{selected.plan.goal}</h3></div><small>{selected.plan.plan_payload.steps.length} 个步骤</small></header><ol>{selected.plan.plan_payload.steps.map((step, index) => <li key={step.key}><span>{String(index + 1).padStart(2, "0")}</span><div><b>{artifactStepText[step.expected_artifact] || "完成本阶段生产"}</b><small>{step.checkpoint === "none" ? "Agent 自动推进" : step.checkpoint === "final" ? "成片检查点" : "关键处确认"}</small></div><em>由 Agent 安排</em></li>)}</ol></section> : <section className="agent-plan-card"><header><div><span className="ux-overline">AGENT PLAN</span><h3>Agent 正在后台理解目标并形成方案</h3></div><small>可安全离开页面</small></header><p>规划任务已经持久化；即使页面关闭或 Worker 重启，也会继续恢复执行。</p></section>}
          <section className="agent-artifacts-card"><header><h3>产物版本</h3><span>{selected.artifact_versions.length} 个版本</span></header>{selected.artifact_versions.length ? selected.artifact_versions.map((version) => <article key={version.id}><span>V{version.version}</span><div><b>{version.artifact_key || version.artifact_type || "生产产物"} · {version.status === "approved" ? "已批准" : version.status === "returned" ? "已退回" : "候选"}</b><small>{new Date(version.created_at).toLocaleString("zh-CN")}</small></div><em>{version.checksum ? "已校验" : "媒体引用"}</em>{version.status === "candidate" && <div className="agent-artifact-actions"><button disabled={reviewing === version.id} onClick={() => void reviewArtifact(version.id, "approve")}>批准</button><button disabled={reviewing === version.id} onClick={() => void reviewArtifact(version.id, "return")}>退回</button></div>}</article>) : <p>Agent 执行后，脚本、声音、视频和交付包会在这里按版本出现。</p>}</section>
        </>}
      </section>
    </div>
  </div>;
}
