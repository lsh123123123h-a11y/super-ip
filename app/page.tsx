"use client";

import { useState } from "react";

type View = "studio" | "profiles" | "content" | "video" | "publish";

const navItems: { id: View; icon: string; label: string }[] = [
  { id: "studio", icon: "⌂", label: "创作工作台" },
  { id: "profiles", icon: "◇", label: "IP 档案" },
  { id: "content", icon: "✦", label: "内容策划" },
  { id: "video", icon: "▶", label: "视频工坊" },
  { id: "publish", icon: "↗", label: "发布中心" },
];

const pipeline = [
  { step: "01", title: "建立 IP 档案", note: "沉淀定位、受众与产品卖点", tone: "violet", target: "profiles" as View },
  { step: "02", title: "策划选题文案", note: "生成平台原生的内容方案", tone: "blue", target: "content" as View },
  { step: "03", title: "制作口播视频", note: "配音、字幕与画面一体编排", tone: "coral", target: "video" as View },
  { step: "04", title: "多平台发布", note: "适配封面、标题与发布时间", tone: "green", target: "publish" as View },
];

const scripts = [
  { tag: "认知反差", title: "真正拖垮效率的，不是工具少", hook: "你收藏了 100 个 AI 工具，为什么工作还是做不完？", score: 92 },
  { tag: "实操清单", title: "我的一人公司内容工作流", hook: "每天 45 分钟，我用这 4 步完成一周内容。", score: 89 },
  { tag: "痛点切入", title: "别再从空白文档开始写了", hook: "没有灵感时，高手都先做这一件事。", score: 86 },
];

export default function Home() {
  const [view, setView] = useState<View>("studio");
  const [showComposer, setShowComposer] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [brief, setBrief] = useState("帮职场人用 AI 减少重复工作，每天省出 2 小时");
  const [platform, setPlatform] = useState("小红书");
  const [toast, setToast] = useState("");

  function generate() {
    setGenerating(true);
    setGenerated(false);
    window.setTimeout(() => { setGenerating(false); setGenerated(true); }, 850);
  }

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 2200);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setView("studio")}><span className="brand-mark">IP</span><span>星流 AI</span></button>
        <nav className="nav-list" aria-label="主导航">
          {navItems.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => setView(item.id)}><span>{item.icon}</span>{item.label}</button>)}
        </nav>
        <div className="sidebar-spacer" />
        <div className="plan-card"><span className="plan-label">本月创作额度</span><strong>68%</strong><div className="meter"><i /></div><small>已使用 6,820 / 10,000 积分</small></div>
        <div className="user-row"><span className="avatar">TL</span><div><b>天雷的工作室</b><small>创作者计划</small></div><button aria-label="打开设置">···</button></div>
      </aside>

      <section className="workspace">
        <Header view={view} onCreate={() => setShowComposer(true)} />
        {view === "studio" && <Studio onNavigate={setView} onCreate={() => setShowComposer(true)} />}
        {view === "profiles" && <Profiles onNotify={notify} onCreate={() => setShowComposer(true)} />}
        {view === "content" && <ContentStudio brief={brief} setBrief={setBrief} platform={platform} setPlatform={setPlatform} generating={generating} generated={generated} onGenerate={generate} onNotify={notify} />}
        {view === "video" && <VideoStudio onNotify={notify} />}
        {view === "publish" && <PublishCenter onNotify={notify} />}
      </section>

      {showComposer && <Composer onClose={() => setShowComposer(false)} onStart={() => { setShowComposer(false); setView("content"); window.setTimeout(generate, 150); }} />}
      {toast && <div className="toast" role="status"><span>✓</span>{toast}</div>}
    </main>
  );
}

function Header({ view, onCreate }: { view: View; onCreate: () => void }) {
  const titles: Record<View, [string, string]> = {
    studio: ["2026年8月20日 · 星期四", "上午好，今天想创作什么？"],
    profiles: ["内容资产 · IP POSITIONING", "IP 档案"], content: ["AI 策划引擎 · STRATEGY", "内容策划"],
    video: ["可视化生产线 · PRODUCTION", "视频工坊"], publish: ["跨平台分发 · DISTRIBUTION", "发布中心"],
  };
  return <header className="topbar"><div><p>{titles[view][0]}</p><h1>{titles[view][1]}</h1></div><div className="top-actions"><button className="icon-button" aria-label="通知">○</button><button className="primary-button" onClick={onCreate}><span>＋</span>新建内容</button></div></header>;
}

function Studio({ onNavigate, onCreate }: { onNavigate: (view: View) => void; onCreate: () => void }) {
  return <>
    <section className="hero-card"><div className="hero-copy"><span className="eyebrow">AI CONTENT ENGINE</span><h2>把一个好想法，变成一套<br /><em>能增长的内容。</em></h2><p>从 IP 定位、爆款选题到口播成片和多平台发布，一条清晰的创作流水线。</p><div className="hero-actions"><button className="hero-primary" onClick={onCreate}>开始一次创作 <span>→</span></button><button className="hero-link" onClick={() => onNavigate("content")}>查看示例项目</button></div></div><div className="orbital" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="core">✦</div><span className="satellite one">文</span><span className="satellite two">音</span><span className="satellite three">画</span></div></section>
    <section className="section-block"><div className="section-heading"><div><span className="section-kicker">创作路径</span><h3>从想法到发布，只需四步</h3></div><button className="text-button" onClick={() => onNavigate("content")}>查看全部项目 →</button></div><div className="pipeline-grid">{pipeline.map((item) => <button className={`pipeline-card ${item.tone}`} key={item.step} onClick={() => onNavigate(item.target)}><div className="step-row"><span>{item.step}</span><i>→</i></div><h4>{item.title}</h4><p>{item.note}</p></button>)}</div></section>
    <section className="lower-grid"><article className="panel recent-panel"><div className="panel-title"><div><span className="section-kicker">继续创作</span><h3>最近项目</h3></div><button className="more-button">···</button></div><button className="project-row" onClick={() => onNavigate("content")}><span className="project-thumb thumb-one">01</span><span className="project-meta"><b>知识博主 30 天选题计划</b><span>内容策划 · 已生成 24 条文案</span></span><span className="progress"><b>76%</b><span><i style={{ width: "76%" }} /></span></span></button><button className="project-row" onClick={() => onNavigate("video")}><span className="project-thumb thumb-two">02</span><span className="project-meta"><b>AI 效率课新品发布</b><span>视频工坊 · 3 条待确认</span></span><span className="progress"><b>42%</b><span><i style={{ width: "42%" }} /></span></span></button></article><article className="panel insight-panel"><div className="panel-title"><div><span className="section-kicker">内容洞察</span><h3>本周表现</h3></div><span className="up-badge">↑ 18.4%</span></div><div className="metric-row"><div><strong>36</strong><span>已发布</span></div><div><strong>12.8w</strong><span>总播放</span></div><div><strong>4.7%</strong><span>互动率</span></div></div><p className="insight-note"><span>✦</span>“实操清单”类内容互动率最高，建议本周继续放大。</p></article></section>
  </>;
}

function Profiles({ onNotify, onCreate }: { onNotify: (s: string) => void; onCreate: () => void }) {
  return <div className="module-view"><section className="module-intro"><div><span className="section-kicker">让 AI 真正懂你</span><h2>先定义你是谁，再决定说什么。</h2><p>IP 档案会成为所有选题、文案和视觉内容的共同上下文。</p></div><button className="module-action" onClick={onCreate}>＋ 创建新档案</button></section><div className="profile-grid"><article className="profile-card featured"><div className="profile-top"><span className="profile-avatar purple">TL</span><span className="status-pill">主档案</span></div><h3>AI 效率教练 · 天雷</h3><p>帮助知识工作者建立可复制的 AI 工作流，把时间还给创造。</p><div className="tag-row"><span>职场效率</span><span>AI 实操</span><span>一人公司</span></div><div className="profile-stats"><div><b>86</b><small>内容资产</small></div><div><b>4.7%</b><small>平均互动</small></div><div><b>12.8w</b><small>月触达</small></div></div><button className="full-button" onClick={() => onNotify("档案编辑器已准备好")}>编辑档案</button></article><article className="profile-card"><div className="profile-top"><span className="profile-avatar amber">课</span><span className="status-pill draft">草稿</span></div><h3>AI 工作流训练营</h3><p>面向小团队和个体创业者的 21 天效率训练计划。</p><div className="tag-row"><span>课程产品</span><span>方法论</span></div><div className="profile-progress"><span><b>完整度 64%</b><i>补充受众痛点后，文案会更精准</i></span><div><em /></div></div><button className="full-button secondary" onClick={() => onNotify("已打开档案完善流程")}>继续完善</button></article><button className="new-profile" onClick={onCreate}><span>＋</span><b>建立新的内容身份</b><small>适用于新产品、新业务或新账号</small></button></div></div>;
}

function ContentStudio({ brief, setBrief, platform, setPlatform, generating, generated, onGenerate, onNotify }: { brief: string; setBrief: (s: string) => void; platform: string; setPlatform: (s: string) => void; generating: boolean; generated: boolean; onGenerate: () => void; onNotify: (s: string) => void }) {
  return <div className="module-view content-layout"><section className="prompt-panel"><span className="section-kicker">STEP 01 · 内容简报</span><h2>这次想讲什么？</h2><label>目标平台</label><div className="choice-row">{["抖音", "小红书", "视频号", "公众号"].map(p => <button className={platform === p ? "selected" : ""} key={p} onClick={() => setPlatform(p)}>{p}</button>)}</div><label htmlFor="brief">核心想法 / 产品卖点</label><textarea id="brief" value={brief} onChange={(e) => setBrief(e.target.value)} /><div className="prompt-tips"><span>✦ 已调用「AI 效率教练」档案</span><span>语气：真诚、克制、有方法</span></div><button className="generate-button" onClick={onGenerate} disabled={generating || !brief.trim()}>{generating ? <><i className="spinner" /> 正在策划内容...</> : <>生成选题与文案 <span>→</span></>}</button></section><section className="results-panel"><div className="results-head"><div><span className="section-kicker">AI 创作结果</span><h3>{generated ? `为「${platform}」生成了 3 个方向` : "等待你的内容简报"}</h3></div>{generated && <button className="ghost-button" onClick={onGenerate}>换一批</button>}</div>{!generated && !generating && <div className="empty-state"><span>✦</span><h4>从一句话开始</h4><p>AI 会结合你的 IP 档案，完成角度选择、钩子设计与脚本初稿。</p></div>}{generating && <div className="thinking"><div className="thinking-line wide" /><div className="thinking-line" /><div className="thinking-card" /><div className="thinking-card" /></div>}{generated && <div className="script-list">{scripts.map((script, index) => <article className="script-card" key={script.title}><div className="script-rank">0{index + 1}</div><div className="script-body"><div className="script-label"><span>{script.tag}</span><em>潜力分 {script.score}</em></div><h4>{script.title}</h4><p>“{script.hook}”</p><div><button onClick={() => onNotify("已复制文案到剪贴板")}>复制文案</button><button onClick={() => onNotify("已送入视频工坊")}>制作视频 →</button></div></div></article>)}</div>}</section></div>;
}

function VideoStudio({ onNotify }: { onNotify: (s: string) => void }) {
  const [active, setActive] = useState(2);
  const steps = ["脚本", "声音", "人物", "画面", "包装", "导出"];
  return <div className="module-view"><section className="module-intro compact"><div><span className="section-kicker">当前项目 · AI 效率课新品发布</span><h2>口播视频制作线</h2><p>每一步都可独立调整，随时回到上一步重新生成。</p></div><button className="module-action" onClick={() => onNotify("项目已保存")}>保存项目</button></section><div className="video-workspace"><aside className="stepper">{steps.map((step, index) => <button key={step} className={index === active ? "current" : index < active ? "done" : ""} onClick={() => setActive(index)}><span>{index < active ? "✓" : index + 1}</span><div><b>{step}</b><small>{index < active ? "已完成" : index === active ? "正在编辑" : "等待处理"}</small></div></button>)}</aside><section className="preview-stage"><div className="video-canvas"><div className="canvas-light" /><div className="presenter"><span>AI</span></div><div className="caption-preview"><em>真正拖垮效率的</em><strong>不是工具少</strong></div><span className="duration">00:08 / 00:42</span></div><div className="timeline"><div className="timeline-top"><b>画面时间线</b><span>42 秒 · 9:16 竖屏</span></div><div className="track"><span>人物口播</span><i className="clip clip-one">主镜头</i></div><div className="track"><span>信息卡片</span><i className="clip clip-two">关键词弹窗</i><i className="clip clip-three">步骤清单</i></div><div className="track"><span>字幕</span><i className="clip clip-four">智能字幕 · 已校对</i></div></div></section><aside className="property-panel"><span className="section-kicker">STEP {String(active + 1).padStart(2, "0")}</span><h3>{steps[active]}设置</h3><label>视觉风格</label><button className="style-choice active"><span className="style-swatch dark" /><div><b>深色科技</b><small>蓝青高光 · 信息卡片</small></div><em>✓</em></button><button className="style-choice"><span className="style-swatch warm" /><div><b>温暖书信</b><small>纸张质感 · 柔和强调</small></div></button><label>字幕样式</label><select><option>关键词高亮</option><option>简洁双行</option><option>逐字出现</option></select><button className="generate-button small" onClick={() => onNotify(`${steps[active]}设置已应用`)}>应用并预览</button></aside></div></div>;
}

function PublishCenter({ onNotify }: { onNotify: (s: string) => void }) {
  const [channels, setChannels] = useState(["抖音", "小红书"]);
  function toggle(channel: string) { setChannels(v => v.includes(channel) ? v.filter(x => x !== channel) : [...v, channel]); }
  return <div className="module-view"><section className="module-intro compact"><div><span className="section-kicker">统一管理 · 各平台原生适配</span><h2>准备发布 3 条内容</h2><p>标题、封面和话题会根据平台规则分别生成，不做机械复制。</p></div><button className="module-action" onClick={() => onNotify("已创建新的发布任务")}>＋ 添加发布任务</button></section><div className="publish-layout"><section className="publish-list"><div className="table-head"><span>内容</span><span>平台</span><span>发布时间</span><span>状态</span></div>{[1,2,3].map((item, i) => <article className="publish-row" key={item}><span className={`publish-cover cover-${item}`}>0{item}</span><div className="publish-title"><b>{["真正拖垮效率的，不是工具少", "我的一人公司内容工作流", "别再从空白文档开始写了"][i]}</b><small>{["42 秒口播视频", "9 张图文卡片", "68 秒口播视频"][i]}</small></div><div className="channel-dots"><i>抖</i><i>红</i>{i === 1 && <i>视</i>}</div><div className="publish-time"><b>{["今天 19:30", "明天 12:10", "周六 10:00"][i]}</b><small>Asia/Shanghai</small></div><span className={`queue-status ${i === 0 ? "ready" : ""}`}>{i === 0 ? "待确认" : "已排期"}</span></article>)}</section><aside className="publish-settings panel"><span className="section-kicker">快捷发布</span><h3>选择同步平台</h3><div className="channel-options">{["抖音", "小红书", "视频号", "公众号"].map(c => <button key={c} className={channels.includes(c) ? "selected" : ""} onClick={() => toggle(c)}><span>{c[0]}</span><b>{c}</b><em>{channels.includes(c) ? "✓" : "+"}</em></button>)}</div><div className="compliance-note"><span>盾</span><div><b>发布前合规检查</b><p>敏感词、绝对化用语与版权素材将自动复核。</p></div></div><button className="generate-button small" disabled={!channels.length} onClick={() => onNotify(`已为 ${channels.length} 个平台创建排期`)}>确认排期发布</button></aside></div></div>;
}

function Composer({ onClose, onStart }: { onClose: () => void; onStart: () => void }) {
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="composer" onMouseDown={(e) => e.stopPropagation()}><button className="modal-close" onClick={onClose}>×</button><span className="section-kicker">NEW CONTENT</span><h2>从哪种内容开始？</h2><p>选择一个起点，后续步骤仍然可以自由调整。</p><div className="composer-options"><button onClick={onStart}><span>✦</span><div><b>从一个想法开始</b><small>AI 帮你完成选题、文案与成片</small></div><em>→</em></button><button onClick={onStart}><span>↗</span><div><b>拆解对标内容</b><small>输入链接，提炼结构后原创改写</small></div><em>→</em></button><button onClick={onStart}><span>□</span><div><b>推广一个产品</b><small>围绕卖点生成完整发布方案</small></div><em>→</em></button></div></section></div>;
}
