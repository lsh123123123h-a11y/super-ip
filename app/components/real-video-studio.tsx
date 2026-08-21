"use client";

import { useEffect, useState } from "react";
import {
  AvatarProvider,
  listAvatarProviders,
  previewAvatarRoute,
  ProviderRouteDecision,
  submitDigitalHumanWorkflow,
  uploadAsset,
} from "../lib/api";

type Props = {
  initialScript?: string;
  onNotify: (message: string) => void;
  onTaskCreated: () => void;
};

export default function RealVideoStudio({ initialScript, onNotify, onTaskCreated }: Props) {
  const [script, setScript] = useState(initialScript || "真正拖垮效率的，不是工具少，而是没有一套稳定的工作流。");
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [quality, setQuality] = useState<"720p" | "1080p">("720p");
  const [provider, setProvider] = useState<"auto" | "duix" | "opentalking">("auto");
  const [providers, setProviders] = useState<AvatarProvider[]>([]);
  const [route, setRoute] = useState<ProviderRouteDecision | null>(null);
  const [providerMessage, setProviderMessage] = useState("正在读取数字人能力网关…");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function loadProviders() {
      try {
        const catalog = await listAvatarProviders();
        if (!active) return;
        setProviders(catalog.providers);
        if ("selected_provider" in catalog.default_route) {
          setRoute(catalog.default_route);
          setProviderMessage(`自动路由当前选择 ${catalog.default_route.selected_provider}`);
        } else {
          setProviderMessage(catalog.default_route.error);
        }
      } catch (caught) {
        if (!active) return;
        setProviderMessage(caught instanceof Error ? caught.message : "能力网关暂不可用");
      }
    }
    void loadProviders();
    return () => { active = false; };
  }, []);

  async function chooseProvider(nextProvider: "auto" | "duix" | "opentalking") {
    setProvider(nextProvider);
    setError("");
    try {
      const decision = await previewAvatarRoute({ provider: nextProvider });
      setRoute(decision);
      setProviderMessage(`${decision.reason}：${decision.selected_provider} · ${decision.selected_execution}`);
    } catch (caught) {
      setRoute(null);
      setProviderMessage(caught instanceof Error ? caught.message : "当前路由不可用");
    }
  }

  async function submit() {
    if (!script.trim() || !avatarFile || !audioFile) {
      setError("请填写文案，并选择数字人参考视频和配音文件。");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const [avatar, audio] = await Promise.all([uploadAsset(avatarFile), uploadAsset(audioFile)]);
      await submitDigitalHumanWorkflow({
        script: script.trim(),
        avatar_video_path: avatar.provider_path,
        audio_path: audio.provider_path,
        aspect_ratio: "9:16",
        quality,
        provider,
        execution_mode: "auto",
      });
      onNotify("数字人任务已进入编排队列");
      onTaskCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="module-view">
      <section className="module-intro compact">
        <div>
          <span className="section-kicker">AVATAR ORCHESTRATION · DUIX / OPENTALKING</span>
          <h2>数字人口播生产线</h2>
          <p>素材上传后由编排层选择执行引擎；切换 Provider 不改变项目、任务和成片版本。</p>
        </div>
        <span className="status-pill">{route ? `当前：${route.selected_provider}` : "等待路由"}</span>
      </section>

      <div className="real-video-grid">
        <section className="panel production-form">
          <span className="section-kicker">STEP 01 · 创建任务</span>
          <h3>准备口播素材</h3>

          <label htmlFor="render-script">口播文案</label>
          <textarea id="render-script" value={script} onChange={(event) => setScript(event.target.value)} />

          <label htmlFor="avatar-file">数字人参考视频</label>
          <input id="avatar-file" type="file" accept="video/*" onChange={(event) => setAvatarFile(event.target.files?.[0] ?? null)} />
          <small>{avatarFile ? `${avatarFile.name} · ${(avatarFile.size / 1024 / 1024).toFixed(1)} MB` : "选择已经完成 Duix 形象准备的参考视频"}</small>

          <label htmlFor="audio-file">配音文件</label>
          <input id="audio-file" type="file" accept="audio/*" onChange={(event) => setAudioFile(event.target.files?.[0] ?? null)} />
          <small>{audioFile ? `${audioFile.name} · ${(audioFile.size / 1024 / 1024).toFixed(1)} MB` : "首版使用已生成的 WAV/MP3 配音"}</small>

          <div className="field-label">生成规格</div>
          <div className="choice-row">
            {(["720p", "1080p"] as const).map((item) => (
              <button className={quality === item ? "selected" : ""} key={item} onClick={() => setQuality(item)}>{item}</button>
            ))}
          </div>

          <div className="field-label">执行策略</div>
          <div className="provider-choice-grid">
            <button className={provider === "auto" ? "selected" : ""} onClick={() => void chooseProvider("auto")}>
              <b>自动路由</b><small>按优先级、可用性与执行方式选择</small><em>推荐</em>
            </button>
            {providers.map((item) => (
              <button
                key={item.provider_id}
                className={provider === item.provider_id ? "selected" : ""}
                disabled={!item.render_ready}
                onClick={() => void chooseProvider(item.provider_id as "duix" | "opentalking")}
              >
                <b>{item.label}</b><small>{item.render_ready ? item.execution_modes.join(" / ") : item.reason}</small><em>{item.status === "ready" ? "可用" : "待配置"}</em>
              </button>
            ))}
          </div>
          <p className="route-preview"><span>路由</span>{providerMessage}</p>

          {error && <p className="form-error">{error}</p>}
          <button className="generate-button" disabled={submitting} onClick={submit}>
            {submitting ? <><i className="spinner" /> 正在上传并创建任务...</> : <>提交数字人任务 <span>→</span></>}
          </button>
        </section>

        <section className="panel orchestration-preview">
          <span className="section-kicker">ORCHESTRATION</span>
          <h3>本次任务会这样执行</h3>
          <div className="orchestration-flow">
            <article><span>01</span><div><b>检查素材</b><small>验证文件、格式和任务幂等键</small></div></article>
            <article><span>02</span><div><b>记录路由决策</b><small>保存候选引擎、选择原因和策略版本</small></div></article>
            <article><span>03</span><div><b>{route?.selected_provider === "opentalking" ? "OpenTalking" : "Duix"} 渲染</b><small>Provider Job 独立记录原始状态和进度</small></div></article>
            <article><span>04</span><div><b>保存成片</b><small>记录独立作品版本，不覆盖历史</small></div></article>
          </div>
          <div className="orchestration-note">
            <b>真实异步链路</b>
            <p>任务状态和路由决策保存在 PostgreSQL，Redis 只负责排队。OpenTalking 未配置时不会假装可用，也不会影响 Duix 生产主链。</p>
          </div>
        </section>
      </div>
    </div>
  );
}
