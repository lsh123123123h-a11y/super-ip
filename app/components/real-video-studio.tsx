"use client";

import { useState } from "react";
import { submitDigitalHumanWorkflow, uploadAsset } from "../lib/api";

type Props = {
  onNotify: (message: string) => void;
  onTaskCreated: () => void;
};

export default function RealVideoStudio({ onNotify, onTaskCreated }: Props) {
  const [script, setScript] = useState("真正拖垮效率的，不是工具少，而是没有一套稳定的工作流。");
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [quality, setQuality] = useState<"720p" | "1080p">("720p");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

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
          <span className="section-kicker">DUIX · OFFLINE AVATAR</span>
          <h2>数字人口播生产线</h2>
          <p>素材上传后由编排层异步执行，关闭页面也不会丢失任务。</p>
        </div>
        <span className="status-pill">首版引擎：Duix</span>
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
            <article><span>02</span><div><b>进入 GPU 队列</b><small>编排服务控制并发和任务租约</small></div></article>
            <article><span>03</span><div><b>Duix 渲染</b><small>提交任务并持续同步提供方进度</small></div></article>
            <article><span>04</span><div><b>保存成片</b><small>记录独立作品版本，不覆盖历史</small></div></article>
          </div>
          <div className="orchestration-note">
            <b>真实异步链路</b>
            <p>任务状态保存在 PostgreSQL，Redis 只负责排队。重复点击不会重复生成；失败步骤可以继续重试。</p>
          </div>
        </section>
      </div>
    </div>
  );
}
