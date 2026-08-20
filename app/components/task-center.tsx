"use client";

import { useCallback, useEffect, useState } from "react";
import { listWorkflows, providerAssetUrl, retryWorkflow, Workflow } from "../lib/api";

const statusLabel: Record<Workflow["status"], string> = {
  queued: "排队中",
  running: "处理中",
  waiting_provider: "Duix 渲染中",
  succeeded: "已完成",
  failed_retryable: "可重试",
  failed_final: "失败",
  cancelled: "已取消",
};

export default function TaskCenter() {
  const [items, setItems] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryingId, setRetryingId] = useState("");

  const refresh = useCallback(async () => {
    try {
      setItems(await listWorkflows());
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  async function retry(workflowId: string) {
    setRetryingId(workflowId);
    try {
      await retryWorkflow(workflowId);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务重试失败");
    } finally {
      setRetryingId("");
    }
  }

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [refresh]);

  return (
    <div className="module-view">
      <section className="module-intro compact">
        <div>
          <span className="section-kicker">ASYNC WORKFLOWS</span>
          <h2>任务中心</h2>
          <p>查看排队、Duix 渲染和结果保存的真实进度。</p>
        </div>
        <button className="module-action" onClick={() => void refresh()}>刷新状态</button>
      </section>

      {error && <div className="task-error">后端暂不可用：{error}</div>}
      {loading && <div className="task-empty">正在读取任务…</div>}
      {!loading && !items.length && <div className="task-empty">还没有任务，先去视频工坊提交第一条数字人口播。</div>}

      <section className="task-list">
        {items.map((workflow) => (
          <article className="task-card" key={workflow.id}>
            <div className="task-card-head">
              <div><span>{workflow.input_payload.quality} · {workflow.input_payload.aspect_ratio}</span><h3>{workflow.input_payload.title || workflow.input_payload.script.slice(0, 32)}</h3></div>
              <b className={`task-status ${workflow.status}`}>{statusLabel[workflow.status]}</b>
            </div>
            <div className="task-progress"><i style={{ width: `${workflow.progress}%` }} /></div>
            <div className="task-steps">
              {workflow.steps.map((step) => (
                <div className={step.status} key={step.step_key}><span>{step.status === "succeeded" ? "✓" : step.position + 1}</span><b>{step.label}</b><small>{step.progress}%</small></div>
              ))}
            </div>
            {workflow.error_message && <p className="task-message">{workflow.error_message}</p>}
            <div className="task-actions">
              {workflow.status === "failed_retryable" && <button disabled={retryingId === workflow.id} onClick={() => void retry(workflow.id)}>{retryingId === workflow.id ? "重新入队中…" : "重试任务"}</button>}
              {workflow.status === "succeeded" && typeof workflow.output_payload?.artifact_path === "string" && <a href={providerAssetUrl(workflow.output_payload.artifact_path)} target="_blank" rel="noreferrer">下载成片</a>}
              {workflow.status === "succeeded" && typeof workflow.output_payload?.result_url === "string" && <a href={workflow.output_payload.result_url} target="_blank" rel="noreferrer">打开成片</a>}
            </div>
            <footer><code>{workflow.id}</code><time>{new Date(workflow.created_at).toLocaleString("zh-CN")}</time></footer>
          </article>
        ))}
      </section>
    </div>
  );
}
