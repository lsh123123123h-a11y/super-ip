"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import TaskCenter from "./task-center";
import AgentProductionCenter from "./agent-production-center";
import {
  Campaign,
  ContentProject,
  createCampaign as createCampaignRequest,
  createContentProject,
  IPProfile,
  listCampaigns,
  listContentProjects,
  listIPProfiles,
  listWorkflows,
  providerAssetUrl,
  saveIPProfile,
  updateContentProject,
  uploadAsset,
  Workflow,
} from "../lib/api";

type UserView =
  | "dashboard"
  | "ip-brain"
  | "campaigns"
  | "content"
  | "assets"
  | "tasks"
  | "publish";

const navigation: Array<{ label: string; items: Array<{ id: UserView; icon: string; title: string }> }> = [
  {
    label: "经营与规划",
    items: [
      { id: "dashboard", icon: "⌂", title: "今日工作台" },
      { id: "ip-brain", icon: "◎", title: "IP 大脑" },
      { id: "campaigns", icon: "◇", title: "营销活动" },
    ],
  },
  {
    label: "内容生产",
    items: [
      { id: "content", icon: "✦", title: "Agent 生产" },
      { id: "assets", icon: "▣", title: "资产中心" },
    ],
  },
  {
    label: "交付与增长",
    items: [
      { id: "tasks", icon: "◷", title: "任务中心" },
      { id: "publish", icon: "↗", title: "发布与复盘" },
    ],
  },
];

const titles: Record<UserView, { eyebrow: string; title: string }> = {
  dashboard: { eyebrow: "TODAY · 生产总览", title: "今天先把这 3 件事推进" },
  "ip-brain": { eyebrow: "IP CONTEXT", title: "IP 大脑" },
  campaigns: { eyebrow: "CAMPAIGN", title: "营销活动" },
  content: { eyebrow: "AGENT PRODUCTION", title: "Agent 生产中心" },
  assets: { eyebrow: "ASSET LIBRARY", title: "资产中心" },
  tasks: { eyebrow: "WORKFLOW", title: "任务中心" },
  publish: { eyebrow: "DELIVERY", title: "发布与复盘" },
};

export default function UserConsole() {
  const [view, setView] = useState<UserView>("dashboard");
  const [toast, setToast] = useState("");

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2400);
  }, []);

  return (
    <main className="ux-shell">
      <aside className="ux-sidebar">
        <button className="ux-brand" onClick={() => setView("dashboard")}>
          <span className="ux-brand-mark">星</span>
          <span><b>星流 AI</b><small>超级 IP 营销工作台</small></span>
        </button>

        <div className="ux-workspace-switch">
          <span className="ux-workspace-avatar">本</span>
          <span><small>当前工作空间</small><b>本地开发工作空间</b></span>
          <i>⌄</i>
        </div>

        <nav className="ux-navigation" aria-label="用户端主导航">
          {navigation.map((group) => (
            <section key={group.label}>
              <p>{group.label}</p>
              {group.items.map((item) => (
                <button
                  className={view === item.id ? "active" : ""}
                  key={item.id}
                  onClick={() => setView(item.id)}
                >
                  <span>{item.icon}</span>{item.title}
                </button>
              ))}
            </section>
          ))}
        </nav>

        <div className="ux-sidebar-bottom">
          <div className="ux-credit-card"><span>额度与账本</span><b>尚未启用</b><small>正式计费前不展示虚构余额</small></div>
          <Link href="/admin" className="ux-admin-link"><span>⚙</span>进入管理端 <i>→</i></Link>
        </div>
      </aside>

      <section className="ux-main">
        <header className="ux-topbar">
          <div><p>{titles[view].eyebrow}</p><h1>{titles[view].title}</h1></div>
          <div className="ux-top-actions">
            <button className="ux-search" aria-label="搜索">⌕</button>
            <button className="ux-secondary">导入内容</button>
            <button className="ux-primary" onClick={() => setView("content")}><span>＋</span> 新建内容项目</button>
          </div>
        </header>

        {view === "dashboard" && <Dashboard onNavigate={setView} />}
        {view === "ip-brain" && <IpBrain onNotify={notify} />}
        {view === "campaigns" && <CampaignHub onNavigate={setView} onNotify={notify} />}
        {view === "content" && <AgentProductionCenter onNotify={notify} />}
        {view === "assets" && <AssetCenter onNotify={notify} />}
        {view === "tasks" && <TaskCenter />}
        {view === "publish" && <DeliveryCenter onNotify={notify} />}
      </section>
      {toast && <div className="ux-toast" role="status"><span>✓</span>{toast}</div>}
    </main>
  );
}

function Dashboard({ onNavigate }: { onNavigate: (view: UserView) => void }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(async () => {
      try {
        const [nextCampaigns, nextProjects, nextWorkflows] = await Promise.all([listCampaigns(), listContentProjects(), listWorkflows()]);
        if (active) { setCampaigns(nextCampaigns); setProjects(nextProjects); setWorkflows(nextWorkflows); }
      } catch {
        // Individual modules expose detailed API errors; the dashboard keeps an empty truthful state.
      } finally {
        if (active) setLoading(false);
      }
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, []);

  const campaign = campaigns.find((item) => item.status === "active") ?? campaigns[0];
  const campaignProjects = campaign ? projects.filter((item) => item.campaign_id === campaign.id) : [];
  const scriptReady = campaignProjects.filter((item) => item.status !== "draft").length;
  const running = workflows.filter((item) => ["queued", "running", "waiting_provider"].includes(item.status)).length;
  const succeeded = workflows.filter((item) => item.status === "succeeded").length;
  const failed = workflows.filter((item) => item.status.startsWith("failed")).length;
  const nextActions = Number(!campaign) + Number(campaignProjects.length === 0) + running + succeeded;

  return (
    <div className="ux-dashboard">
      <section className="ux-focus-card">
        <div className="ux-focus-head">
          <div><span className="ux-overline">{campaign ? "当前主活动" : "第一步"}</span><h2>{loading ? "正在读取你的生产上下文…" : campaign?.name ?? "建立第一个营销活动"}</h2><p>{campaign ? `目标：${campaign.goal || "尚未填写活动目标"}` : "把目标、渠道和内容项目放进同一个可追踪的生产单元。"}</p></div>
          <button onClick={() => onNavigate("campaigns")}>{campaign ? "查看活动详情" : "创建活动"} →</button>
        </div>
        <div className="ux-flowline">
          {[
            ["01", "活动简报", campaign ? "已建立" : "待建立", campaign ? "done" : "active"],
            ["02", "选题脚本", `${scriptReady} / ${campaign?.target_content_count || 0}`, campaignProjects.length ? "active" : ""],
            ["03", "数字人成片", `${succeeded} 个成功`, running ? "active" : ""],
            ["04", "异常处理", `${failed} 个失败`, failed ? "active" : ""],
            ["05", "发布复盘", "待接平台", ""],
          ].map(([number, label, note, state]) => <article className={state} key={label}><span>{state === "done" ? "✓" : number}</span><div><b>{label}</b><small>{note}</small></div></article>)}
        </div>
      </section>

      <section className="ux-dashboard-grid">
        <div className="ux-work-queue">
          <div className="ux-section-title"><div><span className="ux-overline">NEXT ACTIONS</span><h3>需要你处理</h3></div><b>{nextActions}</b></div>
          {!campaign && <button className="ux-action-row" onClick={() => onNavigate("campaigns")}><span className="violet">活</span><div><b>建立第一个营销活动</b><small>明确目标、渠道和内容数量</small></div><em>待开始</em><i>→</i></button>}
          <button className="ux-action-row" onClick={() => onNavigate("content")}><span className="violet">稿</span><div><b>{campaignProjects.length ? `继续编辑 ${campaignProjects.length} 个内容项目` : "创建第一个内容项目"}</b><small>{campaign?.name ?? "尚未关联营销活动"}</small></div><em>内容</em><i>→</i></button>
          <button className="ux-action-row" onClick={() => onNavigate("tasks")}><span className="amber">任</span><div><b>{running ? `${running} 个生产任务正在执行` : "检查生产任务状态"}</b><small>真实队列、执行进度与失败重试</small></div><em>{running ? "进行中" : "任务"}</em><i>→</i></button>
          <button className="ux-action-row" onClick={() => onNavigate("publish")}><span className="green">审</span><div><b>{succeeded ? `审核 ${succeeded} 个真实成片` : "等待第一条成片"}</b><small>只展示真实成功的工作流产物</small></div><em>{succeeded ? "待审核" : "空"}</em><i>→</i></button>
        </div>

        <aside className="ux-quick-start"><div className="ux-section-title"><div><span className="ux-overline">QUICK START</span><h3>从哪里开始</h3></div></div><div className="ux-start-grid"><button onClick={() => onNavigate("content")}><span>✦</span><b>一个想法</b><small>从目标和观点开始</small></button><button onClick={() => onNavigate("content")}><span>↗</span><b>对标内容</b><small>拆结构后原创改写</small></button><button onClick={() => onNavigate("campaigns")}><span>◇</span><b>一个产品</b><small>建立完整营销活动</small></button><button onClick={() => onNavigate("content")}><span>▶</span><b>现有文案</b><small>交给 Agent 安排制作</small></button></div></aside>
      </section>

      <section className="ux-production-strip"><div><span className="ux-overline">PRODUCTION</span><h3>真实生产状态</h3></div><article><b>{campaign?.target_content_count ?? 0}</b><small>活动内容目标</small></article><article><b>{projects.length}</b><small>已保存内容项目</small></article><article><b>{succeeded}</b><small>真实成功成片</small></article><article><b>{failed}</b><small>失败待处理</small></article><button onClick={() => onNavigate("tasks")}>打开任务中心 →</button></section>
    </div>
  );
}

function IpBrain({ onNotify }: { onNotify: (message: string) => void }) {
  const sections = [
    ["identity", "身份定位", "你是谁，以及为什么值得被关注"],
    ["audience", "目标人群", "你为谁解决什么高频问题"],
    ["offer", "产品与 Offer", "内容最终承接的产品与行动"],
    ["voice", "表达系统", "语气、句式、价值观和记忆点"],
    ["evidence", "证据库", "案例、数据、资质和用户反馈"],
    ["boundary", "内容边界", "敏感禁区、承诺边界和平台规则"],
  ] as const;
  const [active, setActive] = useState<(typeof sections)[number][0]>("identity");
  const [profileId, setProfileId] = useState("");
  const [version, setVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [profile, setProfile] = useState({
    name: "",
    promise: "",
    audience: "",
    offer: "",
    voice: "",
    evidence: "",
    boundary: "",
  });

  useEffect(() => {
    let activeRequest = true;
    const timer = window.setTimeout(async () => {
      try {
        const items = await listIPProfiles();
        const item = items[0];
        if (activeRequest && item) {
          setProfileId(item.id);
          setVersion(item.version);
          setProfile({ name: item.name, promise: item.promise, audience: item.audience, offer: item.offer, voice: item.voice, evidence: item.evidence, boundary: item.boundary });
        }
      } catch (error) {
        if (activeRequest) onNotify(error instanceof Error ? error.message : "IP 大脑读取失败");
      }
    }, 0);
    return () => { activeRequest = false; window.clearTimeout(timer); };
  }, [onNotify]);

  async function persistProfile() {
    if (!profile.name.trim()) { onNotify("请先填写 IP / 品牌名称"); return; }
    setSaving(true);
    try {
      const saved = await saveIPProfile({ id: profileId || undefined, ...profile, is_primary: true });
      setProfileId(saved.id);
      setVersion(saved.version);
      onNotify("IP 大脑已保存到后端");
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "IP 大脑保存失败");
    } finally {
      setSaving(false);
    }
  }

  const field = active === "identity" ? "promise" : active;
  const value = profile[field as keyof typeof profile];

  return (
    <div className="ux-module-page">
      <section className="ux-context-banner">
        <div><span className="ux-overline">当前 IP</span><h2>{profile.name || "建立你的第一个 IP 档案"}</h2><p>所有活动、脚本和数字人项目都会引用这一份可版本化上下文。</p></div>
        <div className="ux-context-actions"><span>{version ? `已持久化版本 · v${version}` : "尚未创建后端档案"}</span><button disabled={saving} onClick={() => void persistProfile()}>{saving ? "保存中…" : "保存当前版本"}</button></div>
      </section>
      <div className="ux-editor-layout">
        <nav className="ux-editor-nav" aria-label="IP 大脑章节">
          {sections.map(([id, title, note], index) => <button className={active === id ? "active" : ""} onClick={() => setActive(id)} key={id}><span>{String(index + 1).padStart(2, "0")}</span><div><b>{title}</b><small>{note}</small></div><i>→</i></button>)}
        </nav>
        <section className="ux-editor-panel">
          <span className="ux-overline">{sections.find(([id]) => id === active)?.[1]}</span>
          <h3>{sections.find(([id]) => id === active)?.[2]}</h3>
          {active === "identity" && <label>IP / 品牌名称<input value={profile.name} onChange={(event) => setProfile({ ...profile, name: event.target.value })} /></label>}
          <label>{active === "identity" ? "核心价值承诺" : "当前内容"}<textarea value={value} onChange={(event) => setProfile({ ...profile, [field]: event.target.value })} /></label>
          <div className="ux-editor-hint"><span>✦</span><p><b>如何被下游使用</b>内容工作室会把这里的内容作为结构化上下文，而不是每次让你重新复制 Prompt。</p></div>
          <footer><span>保存后会成为内容项目可引用的真实 IP 对象。</span><button disabled={saving} onClick={() => void persistProfile()}>保存本节</button></footer>
        </section>
      </div>
    </div>
  );
}

function CampaignHub({ onNavigate, onNotify }: { onNavigate: (view: UserView) => void; onNotify: (message: string) => void }) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [target, setTarget] = useState(10);
  const [channels, setChannels] = useState<string[]>(["抖音"]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextCampaigns, nextProjects] = await Promise.all([listCampaigns(), listContentProjects()]);
      setCampaigns(nextCampaigns);
      setProjects(nextProjects);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "活动读取失败");
    } finally {
      setLoading(false);
    }
  }, [onNotify]);

  useEffect(() => { const timer = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(timer); }, [refresh]);

  async function createCampaign() {
    if (!name.trim()) return;
    try {
      await createCampaignRequest({ name: name.trim(), goal: goal.trim(), channels, target_content_count: target, status: "draft" });
      setName(""); setGoal(""); setTarget(10); setChannels(["抖音"]); setCreating(false);
      await refresh();
      onNotify("营销活动已保存到后端");
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "活动创建失败");
    }
  }

  return (
    <div className="ux-module-page">
      <section className="ux-module-lead"><div><span className="ux-overline">CAMPAIGN OPERATING SYSTEM</span><h2>先定义营销目标，再组织内容生产。</h2><p>活动把 IP、目标、渠道、内容项目、预算和发布结果串在一起。</p></div><button onClick={() => setCreating(true)}>＋ 新建营销活动</button></section>
      <section className="ux-campaign-list">
        {campaigns.map((campaign) => { const related = projects.filter((item) => item.campaign_id === campaign.id); const scriptReady = related.filter((item) => item.status !== "draft").length; const progress = campaign.target_content_count ? Math.min(100, Math.round(related.length / campaign.target_content_count * 100)) : 0; const statusText = { draft: "草稿", active: "进行中", paused: "已暂停", completed: "已完成" }[campaign.status]; return <article key={campaign.id}>
          <header><div><span className={campaign.status === "active" ? "live" : "draft"}>{statusText}</span><h3>{campaign.name}</h3><p>{campaign.goal || "尚未填写目标"} · {campaign.channels.join(" / ") || "尚未选择渠道"}</p></div><button onClick={() => onNavigate("content")}>进入内容生产 →</button></header>
          <div className="ux-campaign-progress"><span><i style={{ width: `${progress}%` }} /></span><b>{progress}%</b></div>
          <footer><span><b>{related.length}</b> 个内容项目</span><span>脚本 {scriptReady}</span><span>目标 {campaign.target_content_count}</span><span>状态 {statusText}</span></footer>
        </article>; })}
      </section>
      {!loading && !campaigns.length && <section className="ux-empty-state"><span>◇</span><h3>还没有营销活动</h3><p>创建后会生成真实 Campaign 对象，内容项目可以归属到活动并统计进度。</p></section>}
      {creating && <dialog open className="ux-dialog-backdrop"><section className="ux-dialog"><button className="ux-dialog-close" onClick={() => setCreating(false)}>×</button><span className="ux-overline">NEW CAMPAIGN</span><h2>建立营销活动</h2><p>这次不是临时卡片，创建后会写入后端 Campaign 表。</p><label>活动名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：秋季新品首发获客计划" /></label><label>营销目标<input value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="例如：获得 100 个有效咨询" /></label><label>目标内容数量<input type="number" min="0" value={target} onChange={(event) => setTarget(Number(event.target.value))} /></label><label>渠道<div className="ux-pill-choice">{["抖音","小红书","视频号","公众号"].map((item) => <button type="button" className={channels.includes(item) ? "active" : ""} onClick={() => setChannels((current) => current.includes(item) ? current.filter((channel) => channel !== item) : [...current, item])} key={item}>{item}</button>)}</div></label><div><button onClick={() => setCreating(false)}>取消</button><button className="primary" disabled={!name.trim()} onClick={() => void createCampaign()}>创建活动</button></div></section></dialog>}
    </div>
  );
}

export function ContentWorkspace({ onSendToAvatar, onNotify }: { onSendToAvatar: (script: string) => void; onNotify: (message: string) => void }) {
  const [step, setStep] = useState(0);
  const [source, setSource] = useState<"idea" | "benchmark" | "product" | "copy">("idea");
  const [platform, setPlatform] = useState("抖音");
  const [brief, setBrief] = useState("");
  const [angle, setAngle] = useState("认知反差");
  const [script, setScript] = useState("");
  const [projectId, setProjectId] = useState("");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [profiles, setProfiles] = useState<IPProfile[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(async () => {
      try {
        const [nextCampaigns, nextProfiles] = await Promise.all([listCampaigns(), listIPProfiles()]);
        if (active) {
          setCampaigns(nextCampaigns);
          setProfiles(nextProfiles);
          setCampaignId(nextCampaigns[0]?.id ?? "");
          setProfileId(nextProfiles[0]?.id ?? "");
        }
      } catch {
        // The editor remains usable without linked context; saves will surface API errors.
      }
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, []);

  function buildDraft() {
    const opening = angle === "认知反差" ? "真正拖垮你效率的，可能不是工具太少，而是工具之间没有形成一套流程。" : `如果你正在为“${brief.slice(0, 24)}”发愁，先别急着继续找工具。`;
    setScript(`${opening}\n\n${brief.trim()}\n\n我的建议是：先固定输入、处理和交付三个环节，再决定每一步该用什么 AI。工具会变，但可复制的流程会留下来。\n\n如果你想看我怎么搭这套流程，评论区留下“工作流”。`);
    setStep(2);
  }

  async function persistProject(status: ContentProject["status"]): Promise<ContentProject | null> {
    setSaving(true);
    try {
      const payload = {
        campaign_id: campaignId || null,
        ip_profile_id: profileId || null,
        title: script.trim().split("\n")[0]?.slice(0, 80) || brief.trim().slice(0, 80) || "未命名内容项目",
        source_type: source,
        platform,
        brief,
        angle,
        script,
        status,
      };
      const saved = projectId ? await updateContentProject(projectId, payload) : await createContentProject(payload);
      setProjectId(saved.id);
      return saved;
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "内容项目保存失败");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function confirmScript() {
    if (await persistProject("script_ready")) setStep(3);
  }

  async function startProduction() {
    if (await persistProject("in_production")) onSendToAvatar(script);
  }

  return (
    <div className="ux-content-studio">
      <section className="ux-project-context"><div><span>所属活动</span><select value={campaignId} onChange={(event) => setCampaignId(event.target.value)}><option value="">不关联活动</option>{campaigns.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></div><i>›</i><div><span>引用 IP</span><select value={profileId} onChange={(event) => setProfileId(event.target.value)}><option value="">不引用 IP</option>{profiles.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></div><em>{projectId ? "已保存项目" : "新项目"}</em></section>
      <div className="ux-studio-steps">
        {["内容起点", "策略角度", "脚本编辑", "送入制作"].map((label, index) => <button className={`${step === index ? "active" : ""} ${step > index ? "done" : ""}`} onClick={() => index <= step && setStep(index)} key={label}><span>{step > index ? "✓" : index + 1}</span><div><b>{label}</b><small>{["想法 / 对标 / 产品 / 文案", "平台、目标与内容结构", "逐句确认可编辑版本", "数字人、图文或文章"][index]}</small></div></button>)}
      </div>
      <section className="ux-studio-canvas">
        {step === 0 && <><span className="ux-overline">STEP 01 · SOURCE</span><h2>这条内容从哪里开始？</h2><div className="ux-source-modes">{([ ["idea","✦","一个想法"], ["benchmark","↗","对标内容"], ["product","◇","推广产品"], ["copy","□","已有文案"] ] as const).map(([id, icon, label]) => <button className={source === id ? "active" : ""} onClick={() => setSource(id)} key={id}><span>{icon}</span><b>{label}</b></button>)}</div><label>核心素材<textarea value={brief} onChange={(event) => setBrief(event.target.value)} /></label><footer><span>{profileId ? `引用 IP：${profiles.find((item) => item.id === profileId)?.name}` : "尚未引用 IP 档案"}</span><button disabled={!brief.trim()} onClick={() => setStep(1)}>下一步：确定策略 →</button></footer></>}
        {step === 1 && <><span className="ux-overline">STEP 02 · STRATEGY</span><h2>先定平台和表达角度</h2><label>目标平台<div className="ux-pill-choice">{["抖音","小红书","视频号","公众号"].map((item) => <button className={platform === item ? "active" : ""} onClick={() => setPlatform(item)} key={item}>{item}</button>)}</div></label><label>内容角度<div className="ux-angle-grid">{["认知反差","痛点拆解","实操清单","案例复盘"].map((item) => <button className={angle === item ? "active" : ""} onClick={() => setAngle(item)} key={item}><b>{item}</b><small>{item === "认知反差" ? "用意外观点打断惯性" : item === "痛点拆解" ? "从具体困境展开" : item === "实操清单" ? "给出可执行步骤" : "用结果建立信任"}</small></button>)}</div></label><aside className="ux-honest-note"><b>当前生成方式</b><p>先使用可编辑的本地结构模板打通产品流程；通用 AI 模型通道尚未接入，因此不会伪装成模型生成结果。</p></aside><footer><button className="back" onClick={() => setStep(0)}>← 返回</button><button onClick={buildDraft}>整理成脚本草稿 →</button></footer></>}
        {step === 2 && <><span className="ux-overline">STEP 03 · SCRIPT</span><h2>逐句确认这版口播脚本</h2><div className="ux-script-meta"><span>{platform}</span><span>{angle}</span><span>预计 {Math.max(15, Math.round(script.length / 4.2))} 秒</span></div><label>脚本正文<textarea className="script-editor" value={script} onChange={(event) => setScript(event.target.value)} /></label><div className="ux-disabled-ai"><button disabled>✦ AI 润色</button><span>等待通用模型渠道配置后启用</span></div><footer><button className="back" onClick={() => setStep(1)}>← 调整策略</button><button disabled={!script.trim() || saving} onClick={() => void confirmScript()}>{saving ? "保存项目中…" : "保存并确认脚本 →"}</button></footer></>}
        {step === 3 && <><span className="ux-overline">STEP 04 · PRODUCTION</span><h2>选择这版脚本的交付形态</h2><div className="ux-delivery-types"><button className="active" disabled={saving} onClick={() => void startProduction()}><span>▶</span><div><b>数字人口播视频</b><small>进入 Agent 的可恢复视频生产链</small></div><i>已接通</i></button><button disabled><span>图</span><div><b>小红书图文</b><small>4 张统一风格图与发布文案</small></div><i>待接入</i></button><button disabled><span>文</span><div><b>公众号文章</b><small>扩写、排版、封面与摘要</small></div><i>待接入</i></button><button disabled><span>片</span><div><b>素材讲解视频</b><small>动态字幕、素材和数字人小窗</small></div><i>待接入</i></button></div><footer><button className="back" onClick={() => setStep(2)}>← 返回脚本</button><button disabled={saving} onClick={() => void startProduction()}>{saving ? "更新项目中…" : "交给 Agent 制作 →"}</button></footer></>}
      </section>
    </div>
  );
}

type SessionAsset = { id: string; name: string; type: string; size: number; url: string };

function AssetCenter({ onNotify }: { onNotify: (message: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [assets, setAssets] = useState<SessionAsset[]>([]);
  const [filter, setFilter] = useState("全部");

  async function upload() {
    if (!file) return;
    setUploading(true);
    try {
      const result = await uploadAsset(file);
      setAssets((items) => [{ id: result.asset_id, name: result.file_name, type: file.type.startsWith("video") ? "视频" : file.type.startsWith("audio") ? "音频" : "图片", size: file.size, url: result.download_url }, ...items]);
      setFile(null);
      onNotify("素材已上传并可用于数字人任务");
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "素材上传失败");
    } finally {
      setUploading(false);
    }
  }

  const visibleAssets = filter === "全部" ? assets : assets.filter((asset) => asset.type === filter);
  return <div className="ux-module-page"><section className="ux-module-lead"><div><span className="ux-overline">REUSABLE ASSETS</span><h2>把每次创作沉淀成可复用资产。</h2><p>素材、声音、数字人形象、模板和授权应该被项目共同引用，而不是重复上传。</p></div><div className="ux-upload-inline"><input aria-label="选择素材" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><button disabled={!file || uploading} onClick={() => void upload()}>{uploading ? "上传中…" : "上传素材"}</button></div></section><div className="ux-asset-toolbar"><div>{["全部","视频","音频","图片"].map((item) => <button className={filter === item ? "active" : ""} onClick={() => setFilter(item)} key={item}>{item}</button>)}</div><span>{assets.length} 项当前会话资产</span></div>{visibleAssets.length ? <section className="ux-asset-grid">{visibleAssets.map((asset) => <a href={asset.url} target="_blank" rel="noreferrer" key={asset.id}><span>{asset.type === "视频" ? "▶" : asset.type === "音频" ? "音" : "图"}</span><div><b>{asset.name}</b><small>{asset.type} · {(asset.size / 1024 / 1024).toFixed(2)} MB</small></div><i>打开 ↗</i></a>)}</section> : <section className="ux-empty-state"><span>▣</span><h3>这里还没有真实素材</h3><p>上传一个视频、音频或图片，它会通过后端资产接口保存，并可以直接用于数字人任务。</p></section>}</div>;
}

function DeliveryCenter({ onNotify }: { onNotify: (message: string) => void }) {
  const [items, setItems] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [approved, setApproved] = useState<string[]>([]);
  const refresh = useCallback(async () => { setLoading(true); try { setItems(await listWorkflows()); } catch (error) { onNotify(error instanceof Error ? error.message : "交付物读取失败"); } finally { setLoading(false); } }, [onNotify]);
  useEffect(() => { const timer = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(timer); }, [refresh]);
  const deliverables = useMemo(() => items.filter((item) => item.status === "succeeded"), [items]);

  return <div className="ux-module-page"><section className="ux-module-lead"><div><span className="ux-overline">REVIEW BEFORE PUBLISH</span><h2>先审片，再生成平台发布包。</h2><p>这里只展示真实成功的工作流产物；平台直发尚未接入时，先提供可下载交付。</p></div><button onClick={() => void refresh()}>{loading ? "读取中…" : "刷新交付物"}</button></section>{deliverables.length ? <section className="ux-deliverable-list">{deliverables.map((item) => { const isApproved = approved.includes(item.id); const output = item.output_payload; const href = typeof output?.artifact_path === "string" ? providerAssetUrl(output.artifact_path) : typeof output?.result_url === "string" ? output.result_url : ""; return <article key={item.id}><span className="ux-deliverable-cover">▶</span><div><small>数字人口播成片 · {item.input_payload.quality}</small><h3>{item.input_payload.title || item.input_payload.script.slice(0, 36)}</h3><p>生成于 {new Date(item.updated_at).toLocaleString("zh-CN")}</p></div><b className={isApproved ? "approved" : "pending"}>{isApproved ? "已通过" : "待审核"}</b><div>{href && <a href={href} target="_blank" rel="noreferrer">预览成片</a>}<button onClick={() => setApproved((ids) => isApproved ? ids.filter((id) => id !== item.id) : [...ids, item.id])}>{isApproved ? "撤回审核" : "审核通过"}</button></div></article>; })}</section> : <section className="ux-empty-state"><span>审</span><h3>{loading ? "正在读取真实成片…" : "还没有可审核的成片"}</h3><p>数字人任务成功后会自动出现在这里；不会用演示作品填充发布列表。</p></section>}</div>;
}
