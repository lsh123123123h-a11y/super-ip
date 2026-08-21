"use client";

import { useState } from "react";
import styles from "./prototype.module.css";

type View = "project" | "create" | "studio" | "insight" | "assets" | "workflow" | "publish" | "admin";

const menu: Array<[View, string, string]> = [
  ["project", "⌂", "首页"],
  ["create", "✎", "创作"],
  ["insight", "◉", "洞察"],
  ["assets", "▣", "素材"],
  ["workflow", "✣", "工作流"],
  ["publish", "♧", "发布"],
  ["admin", "▥", "数据"],
];

export default function PrototypeClient({ initialView }: { initialView: View }) {
  const [view, setView] = useState<View>(initialView);
  const [projectTab, setProjectTab] = useState("概览");
  const [studioTab, setStudioTab] = useState("数字人工作室");

  const changeView = (next: View) => {
    setView(next);
    window.history.replaceState({}, "", next === "project" ? "/prototype" : `/prototype?view=${next}`);
  };

  return (
    <main className={styles.app}>
      <GlobalSidebar view={view} onChange={changeView} />
      <section className={styles.content}>
        <TopSearch />
        {view === "project" && <ProjectOverview tab={projectTab} onTab={setProjectTab} onChange={changeView} />}
        {view === "create" && <CreationCenter onChange={changeView} />}
        {view === "studio" && <VideoStudio tab={studioTab} onTab={setStudioTab} />}
        {view === "insight" && <PlaceholderPage title="内容洞察" subtitle="趋势、对标与选题机会将在第二阶段接入。" />}
        {view === "assets" && <AssetLibrary />}
        {view === "workflow" && <WorkflowCenter onChange={changeView} />}
        {view === "publish" && <PublishCenter />}
        {view === "admin" && <PlatformData />}
      </section>
    </main>
  );
}

function GlobalSidebar({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  return <aside className={styles.globalNav}>
    <button className={styles.logo} onClick={() => onChange("project")}><span>S</span><b>SUPER IP</b></button>
    <nav>
      <button className={view === "project" ? styles.navActive : ""} onClick={() => onChange("project")}><i>⌂</i>首页</button>
      <button className={view === "project" ? styles.navSoft : ""} onClick={() => onChange("project")}><i>▤</i>项目</button>
      {menu.slice(1).map(([id, icon, label]) => <button key={id} className={view === id || (view === "studio" && id === "create") ? styles.navActive : ""} onClick={() => onChange(id)}><i>{icon}</i>{label}</button>)}
    </nav>
    <div className={styles.navBottom}>
      <button><i>☑</i>任务中心 <em>5</em></button>
      <button><i>♙</i>团队空间</button>
      <button><i>◉</i>用量 / 套餐</button>
      <button><i>⚙</i>设置</button>
      <div className={styles.user}><span>雷</span><p><b>天雷</b><small>专业版</small></p><i>⌄</i></div>
    </div>
  </aside>;
}

function TopSearch() {
  return <header className={styles.topSearch}><div className={styles.search}><span>⌕</span><input aria-label="全局搜索" placeholder="搜索项目、内容、素材…" /><kbd>⌘ K</kbd></div><button className={styles.bell}>♢<em>8</em></button><button className={styles.bot}>●</button></header>;
}

function ProjectOverview({ tab, onTab, onChange }: { tab: string; onTab: (tab: string) => void; onChange: (view: View) => void }) {
  return <div className={styles.pageGrid}>
    <aside className={styles.projectRail}>
      <div className={styles.projectCover}><div className={styles.campScene}><i /><span /></div></div>
      <div className={styles.projectName}><h2>个人 IP · AI 效率系列</h2><button>✎</button></div>
      <span className={styles.statusPill}>进行中 ›</span>
      <div className={styles.railProgress}><header><span>本月进度</span><b>65%</b></header><i><em /></i></div>
      <p className={styles.railLabel}>项目导航</p>
      {["项目概览","生产设置","协作成员","自动化规则","素材库","内容数据","版本管理"].map((item,index) => <button key={item} className={index === 0 ? styles.railActive : ""}><i>{["⌂","⚙","♙","✣","▣","▤","▦"][index]}</i>{item}</button>)}
      <section className={styles.members}><h3>项目成员 <span>4</span></h3><div><i>雷</i><i>策</i><i>剪</i><i>运</i><button>＋</button></div><button>邀请成员</button></section>
      <footer><small>项目 ID：PRJ-20260821-01</small><small>创建时间：2026-08-21</small></footer>
    </aside>

    <section className={styles.projectMain}>
      <header className={styles.projectHeader}>
        <div><span className={styles.breadcrumb}>项目 / 个人 IP · AI 效率系列</span><h1>个人 IP · AI 效率系列 <em>★</em></h1><p>围绕 AI 工具、内容效率与个人工作流，持续生产短视频和图文内容。</p></div>
        <div className={styles.projectMeta}><dl><div><dt>目标平台</dt><dd><i>抖</i><i>视</i><i>书</i></dd></div><div><dt>负责人</dt><dd><span>雷</span>天雷</dd></div><div><dt>周期</dt><dd>08.21 — 09.30</dd></div></dl></div>
      </header>
      <div className={styles.primaryActions}><button className={styles.gradientButton} onClick={() => onChange("create")}>✧ 继续创作</button><button onClick={() => onChange("studio")}>▻ 进入视频工作室</button><button>♧ 审核与交付</button><button>更多操作⌄</button></div>
      <nav className={styles.projectTabs}>{["概览","内容方案","脚本","声音","素材","数字人","视频","发布","复盘"].map(item => <button key={item} className={tab === item ? styles.tabActive : ""} onClick={() => onTab(item)}>{item}</button>)}</nav>

      <div className={styles.dashboardGrid}>
        <section className={styles.card}>
          <CardHead title="项目里程碑" action="查看全部" />
          <ol className={styles.milestones}><li className={styles.complete}><span>✓</span><b>IP 信息与表达规则</b><em>已完成</em></li><li className={styles.complete}><span>✓</span><b>本月内容方向</b><em>已完成</em></li><li className={styles.current}><span>3</span><b>脚本与成片生产</b><em>进行中 · 65%</em></li><li><span>4</span><b>审核与发布</b><em>待开始</em></li><li><span>5</span><b>数据复盘</b><em>待开始</em></li></ol>
        </section>
        <section className={styles.card}>
          <CardHead title="内容规模" action="查看计划" />
          <div className={styles.platformStats}>{[["抖音","12","7","5"],["视频号","8","5","3"],["小红书","6","4","2"],["公众号","2","1","1"]].map(row => <article key={row[0]}><i>{row[0].slice(0,1)}</i><b>{row[0]}</b><span>{row[1]}<small>计划</small></span><span>{row[2]}<small>完成</small></span><span>{row[3]}<small>进行中</small></span></article>)}</div>
        </section>
        <section className={styles.card}>
          <CardHead title="当前生产" action="全部生产单" />
          <div className={styles.taskRows}>{[["为什么 AI 工具越多，效率反而越低","数字人成片","72%"],["做个人 IP，先别急着每天更新","脚本","60%"],["一套能重复使用的内容工作流","包装","38%"],["知识型 IP 如何避免说教感","方案","20%"]].map((row,index)=><button key={row[0]} onClick={() => index===0 && onChange("studio")}><span>{index+1}</span><p><b>{row[0]}</b><small>{row[1]}</small></p><em>{row[2]}</em></button>)}</div>
        </section>
        <section className={styles.cardWide}>
          <CardHead title="最新产出" action="查看全部" />
          <div className={styles.outputCards}><article><div className={styles.thumbA}><i>▶</i><span>00:58</span></div><b>真正拖垮效率的不是工具少</b><small>数字人口播 · 今天 10:24</small></article><article><div className={styles.thumbB}><i>▶</i><span>01:06</span></div><b>先搭流程，再选择 AI 工具</b><small>数字人口播 · 今天 09:15</small></article><article><div className={styles.thumbC}><i>文</i></div><b>AI 效率工作流清单</b><small>发布文案 · 昨天 17:20</small></article></div>
        </section>
        <section className={styles.card}>
          <CardHead title="脚本摘要" action="打开脚本" />
          <div className={styles.scriptSummary}><small>目标平台：抖音 / 视频号 · 约 58 秒</small><h3>核心观点</h3><p>工具数量不会自动带来效率；稳定的输入、处理和交付流程才是可复制的生产力。</p><ol><li>反常识开场</li><li>解释工具切换成本</li><li>给出三段式工作流</li><li>用行动建议收束</li></ol></div>
        </section>
        <section className={styles.card}>
          <CardHead title="待审核内容" action="查看全部 3 项" />
          <div className={styles.reviewRows}><button><span className={styles.miniThumbA} /><p><b>AI 工具效率陷阱</b><small>成片 · 系统提交于 10 分钟前</small></p><em>去审核</em></button><button><span className={styles.miniThumbB} /><p><b>内容工作流 3 步法</b><small>脚本 · 系统提交于 2 小时前</small></p><em>去审核</em></button></div>
        </section>
      </div>
    </section>

    <aside className={styles.aiRail}>
      <header><span className={styles.aiIcon}>●</span><h2>AI 项目助手</h2><button>收起 ›</button></header>
      <Advice title="智能建议" action="生成选题建议"><p>本月“AI 效率”方向表现稳定，建议增加 2–3 条带有真实工作流演示的内容。</p></Advice>
      <Advice title="当前提醒" action="去处理"><p>1 条成片等待最终确认；其余生产步骤会继续自动推进。</p></Advice>
      <section className={styles.score}><h3>本批次质量</h3><div><b>91</b><span>/100</span><p><strong>优秀</strong><small>超过同项目 82% 的内容</small></p></div><button>查看评分详情 ›</button></section>
      <section className={styles.nextSteps}><h3>系统下一步</h3><p><i>✓</i><span>生成数字人口播初版</span><button onClick={() => onChange("studio")}>查看</button></p><p><i>✓</i><span>自动检查字幕与口型</span><button>详情</button></p><p><i>○</i><span>等待你确认最终成片</span><button>待办</button></p></section>
      <section className={styles.health}><h3>项目健康度</h3><p><span>进度健康</span><b>65%</b><em>正常</em></p><p><span>内容产出</span><b>18 / 28</b><em>良好</em></p><p><span>人工介入</span><b>1 次</b><em>较少</em></p></section>
    </aside>
  </div>;
}

function CreationCenter({ onChange }: { onChange: (view: View) => void }) {
  return <div className={styles.creationPage}>
    <header className={styles.pageTitle}><div><h1>创作中心</h1><p>从一个模糊想法或已有素材开始，系统自动形成可执行生产单。</p></div></header>
    <div className={styles.creationLayout}>
      <section className={styles.creationMain}>
        <section className={styles.ideaHero}>
          <div><span>AI CONTENT STUDIO</span><h2>把想法和素材交给系统，<br />其余步骤由它继续推进。</h2><p>无需整理 Prompt，也无需逐步聊天。</p></div>
          <div className={styles.ideaBox}><textarea aria-label="创作想法" defaultValue="我想讲一下，为什么很多人学了越来越多 AI 工具，效率反而没有提高。希望有观点，但不要太说教。" /><button onClick={() => onChange("studio")}>→</button></div>
          <div className={styles.ideaTools}><button>＋ 上传音频 / 视频 / 文档</button><button>▣ 引用项目素材</button><button>◇ 选择数字人形象</button><button>⌄ 更多输入</button></div>
        </section>
        <section className={styles.quickCreate}><CardHead title="开始创作" action="全部工具 ›" /><div>{[["▶","数字人口播","想法或音频直接生成包装成片"],["稿","脚本策划","生成选题、角度和口播脚本"],["图","图文内容","生成小红书图文与发布文案"],["剪","智能剪辑","从已有素材生成短视频"],["文","公众号文章","扩写、排版、摘要与封面"],["批","批量生产","一份策略生成多平台内容"]].map((item,index)=><button key={item[1]} className={index===0?styles.quickActive:""} onClick={() => index===0 && onChange("studio")}><i>{item[0]}</i><b>{item[1]}</b><small>{item[2]}</small><span>{index===0?"开始创作":"使用"}</span></button>)}</div></section>
        <div className={styles.creationSections}>
          <section className={styles.card}><CardHead title="最近项目" action="全部项目 ›" /><div className={styles.recentList}><button><span className={styles.miniThumbA}/><p><b>个人 IP · AI 效率系列</b><small>6 条内容生产中 · 65%</small></p><em>继续</em></button><button><span className={styles.miniThumbB}/><p><b>超级 IP 产品介绍</b><small>2 条内容待审核</small></p><em>继续</em></button></div></section>
          <section className={styles.card}><CardHead title="系统推荐的创作路径" action="换一批 ↻" /><div className={styles.pathList}><button><i>新</i><p><b>观点短视频</b><small>想法 → 脚本 → 数字人 → 包装</small></p><em>→</em></button><button><i>音</i><p><b>音频直接成片</b><small>音频 → 数字人 → 字幕 → 成片</small></p><em>→</em></button><button><i>改</i><p><b>对标内容原创改写</b><small>参考内容 → 结构分析 → 原创生产</small></p><em>→</em></button></div></section>
        </div>
      </section>
      <aside className={styles.suggestionRail}><h2>创作建议</h2><Advice title="适合从音频开始" action="使用音频"><p>你最近上传了 3 段观点音频，其中 2 段可直接转成数字人口播。</p></Advice><Advice title="本周内容缺口" action="生成建议"><p>“实际工作流演示”类型还缺 2 条，补齐后内容结构更均衡。</p></Advice><Advice title="复用表现好的结构" action="使用模板"><p>“反常识开场 + 三步方法”在你的历史内容里通过率最高。</p></Advice><section className={styles.activeTasks}><h3>活跃生产单</h3>{[["AI 工具效率陷阱","72%"],["先搭流程再选工具","38%"],["知识型 IP 不说教","20%"]].map(row=><p key={row[0]}><span>{row[0]}</span><i><em style={{width:row[1]}}/></i><b>{row[1]}</b></p>)}</section></aside>
    </div>
  </div>;
}

function VideoStudio({ tab, onTab }: { tab: string; onTab: (tab: string) => void }) {
  return <div className={styles.studioPage}>
    <header className={styles.studioHeader}><div><h1>视频工作室</h1><span>专业版</span><small>✓ 已保存 14:36</small></div><div><button>↶</button><button>↷</button><button>预览</button><button className={styles.export}>⇩ 导出</button><button>•••</button></div></header>
    <nav className={styles.studioTabs}>{["视频工作室","数字人工作室","图文工作室"].map(item=><button key={item} className={tab===item?styles.studioTabActive:""} onClick={()=>onTab(item)}>{item}</button>)}</nav>
    <div className={styles.studioGrid}>
      <aside className={styles.assetPanel}><header><h2>项目素材</h2><button>＋ 上传</button></header><div className={styles.assetSearch}>⌕ 搜索素材、标签…</div><nav><button className={styles.assetTab}>全部</button><button>视频</button><button>图片</button><button>音频</button></nav><div className={styles.assetThumbs}>{[["scene1","观点音频"],["scene2","数字人形象"],["scene3","品牌背景"],["scene4","B-roll 素材"],["scene5","封面参考"],["scene6","产品画面"]].map((item,index)=><article key={item[1]}><div className={styles[item[0]]}><i>{index===1?"人":index===0?"♫":"＋"}</i><span>{index===0?"03:42":index===1?"00:18":"4K"}</span></div><b>{item[1]}</b><small>{index<2?"已用于本项目":"可用素材"}</small></article>)}</div></aside>
      <section className={styles.editor}>
        <div className={styles.editorToolbar}><span>9:16⌄</span><span>缩放 75%⌄</span><i/><button>↶</button><button>↷</button><button>☷</button></div>
        <div className={styles.stagePreview}><div className={styles.person}><i/><span/></div><h2>AI 工具越多<br/>效率反而越低？</h2><p>真正拖慢你的，不是工具不够强</p><small>安全区</small></div>
        <div className={styles.playbar}><span>00:36 / 00:58</span><button>◀</button><button className={styles.play}>▶</button><button>▶|</button><i><em/></i><span>1.0×⌄</span></div>
        <div className={styles.timelineTools}><button>↶ 撤销</button><button>✂ 分割</button><button>▣ 删除</button><button>▦ 复制</button><button>♫ 静音</button><span>−</span><i><em/></i><span>＋</span></div>
        <Timeline />
      </section>
      <aside className={styles.studioAI}><header><span className={styles.aiIcon}>●</span><h2>AI 导演建议</h2><button>收起⌃</button></header><section className={styles.studioScore}><div><b>91</b><span>/100</span></div><p><strong>优秀</strong><small>口型、节奏和画面均达标</small></p></section><div className={styles.scoreMetrics}><span>内容质量<b>94</b></span><span>节奏表现<b>88</b></span><span>画面表现<b>91</b></span><span>吸引力<b>89</b></span></div><section className={styles.detected}><h3>检测到的问题</h3><p><i className={styles.warnDot}/>00:31–00:35 字幕停留偏短 <button>修复</button></p><p><i/>00:42 口型有轻微偏差 <button>重做片段</button></p></section><section className={styles.oneClick}><h3>一键优化</h3><div><button>自动匹配 B-roll</button><button>智能字幕强调</button><button>优化停顿节奏</button><button>生成封面</button></div></section><section className={styles.finalDecision}><h3>系统建议</h3><p>当前版本已达到发布标准。建议先修复字幕停留，再生成最终交付包。</p><button>应用建议并生成 V2</button></section></aside>
    </div>
  </div>;
}

function Timeline(){
  const tracks=[["视频轨","scene1","scene2","scene3"],["数字人","avatarClip","avatarClip","avatarClip"],["字幕轨","captionClip","captionClip","captionClip"],["包装轨","effectClip","effectClip","effectClip"],["配音轨","audioClip","audioClip","audioClip"],["背景音乐","musicClip","musicClip","musicClip"]];
  return <div className={styles.timeline}><header><span/><div>{["00:00","00:10","00:20","00:30","00:40","00:50"].map(t=><i key={t}>{t}</i>)}</div></header><div className={styles.playhead}/>{tracks.map((track,index)=><div className={styles.track} key={track[0]}><span><i>{["◎","人","T","✦","♫","♬"][index]}</i>{track[0]}</span><div>{track.slice(1).map((clip,i)=><b className={styles[clip]} key={i} style={{width:`${28+i*4}%`}}>{index===2?["AI 工具越多","效率反而越低","先固定工作流"][i]:""}</b>)}</div></div>)}</div>
}

function AssetLibrary(){
  return <div className={styles.simplePage}><header className={styles.pageTitle}><div><h1>素材</h1><p>项目素材、数字人形象、声音和品牌资产统一管理。</p></div><button className={styles.gradientButton}>＋ 上传素材</button></header><div className={styles.assetFilter}><button>类型⌄</button><button>项目⌄</button><button>人物⌄</button><button>来源⌄</button><button>版权⌄</button><button>是否 AI 生成⌄</button></div><section className={styles.libraryGrid}>{Array.from({length:10}).map((_,i)=><article key={i}><div className={styles[`libraryVisual${i%5}`]}><span>{i%3===0?"视频":i%3===1?"图片":"音频"}</span><i>{i%3===2?"♫":"▶"}</i></div><h3>{["AI 效率与未来","自然风光 B-roll","观点音频 0821","数字人正面形象","品牌蓝色背景"][i%5]}</h3><p>个人 IP · AI 效率系列</p><footer><span>质量 {91+i%6}%</span><b>⋯</b></footer></article>)}</section></div>
}

function WorkflowCenter({ onChange }: { onChange: (view: View) => void }){
  return <div className={styles.simplePage}><header className={styles.pageTitle}><div><h1>工作流</h1><p>用户选择生产模板和自动程度；内部能力由平台自动编排。</p></div></header><div className={styles.workflowCards}>{[["爆款短视频生产","热点/想法 → 方案 → 脚本 → 数字人 → 包装","15–25 分钟"],["音频直接成片","音频 → 脚本对齐 → 数字人 → 字幕 → 成片","10–18 分钟"],["矩阵内容生产","主题 → 多平台变体 → 批量制作 → 审核","30–60 分钟"],["公众号文章","素材 → 提纲 → 文章 → 排版 → 封面","8–15 分钟"]].map((row,index)=><article key={row[0]}><i>{["▶","音","批","文"][index]}</i><h2>{row[0]}</h2><p>{row[1]}</p><small>预计 {row[2]}</small><button onClick={()=>index===0&&onChange("create")}>使用模板</button></article>)}</div></div>
}

function PublishCenter(){
  return <div className={styles.simplePage}><header className={styles.pageTitle}><div><h1>发布 / 数据</h1><p>统一审核、排期、发布记录与效果回流。</p></div><button className={styles.gradientButton}>＋ 新建发布</button></header><section className={styles.publishStats}>{[["待审核","12"],["已排期","28"],["发布中","4"],["已发布","36"]].map(row=><article key={row[0]}><span>{row[0]}</span><b>{row[1]}</b><small>较昨日 +3</small></article>)}</section><section className={styles.publishTable}><header><span>内容标题</span><span>平台</span><span>发布时间</span><span>状态</span><span>操作</span></header>{[["AI 工具越多，效率反而越低","抖音","今天 18:00","待审核"],["真正拖垮效率的不是工具少","视频号","明天 10:00","已排期"],["先搭流程，再选 AI 工具","小红书","08/23 20:00","发布中"],["知识型 IP 不说教的 3 个方法","抖音","08/20 18:00","已发布"]].map(row=><div key={row[0]}>{row.map(cell=><span key={cell}>{cell}</span>)}<button>查看</button></div>)}</section></div>
}

function PlatformData(){
  return <div className={styles.simplePage}><header className={styles.pageTitle}><div><h1>平台数据</h1><p>这是开发与运营控制面，不向客户展示云服务和跨租户信息。</p></div><button>进入平台管理端 →</button></header><section className={styles.platformMetrics}>{[["活跃租户","128","本周 +12"],["今日生产单","486","成功率 96.8%"],["异常任务","7","2 项需人工"],["今日能力成本","¥1,842","单成片 ¥4.16"]].map(row=><article key={row[0]}><span>{row[0]}</span><b>{row[1]}</b><small>{row[2]}</small></article>)}</section><section className={styles.controlTable}><CardHead title="云端能力与路由" action="接入新的云服务" /><header><span>业务能力</span><span>主通道</span><span>健康</span><span>今日任务</span><span>成功率</span><span>单位成本</span></header>{[["内容策划与脚本","通用模型通道 A","正常","312","98.4%","¥0.18"],["数字人口播生成","数字人云通道 A","正常","164","95.7%","¥3.26"],["声音清理与合成","语音云通道 A","正常","201","99.1%","¥0.42"],["视频包装与转码","媒体处理集群","繁忙","148","96.2%","¥0.31"]].map(row=><div key={row[0]}>{row.map((cell,i)=><span key={cell} className={i===2?(cell==="正常"?styles.ok:styles.busy):""}>{cell}</span>)}</div>)}</section></div>
}

function PlaceholderPage({title,subtitle}:{title:string;subtitle:string}){return <div className={styles.simplePage}><header className={styles.pageTitle}><div><h1>{title}</h1><p>{subtitle}</p></div></header><section className={styles.placeholder}><span>✦</span><h2>已纳入产品信息架构</h2><p>首期先完成 IP 内容策划、数字人口播生产和后期包装闭环。</p></section></div>}

function CardHead({ title, action }: { title: string; action: string }) { return <header className={styles.cardHead}><h2>{title}</h2><button>{action} ›</button></header>; }
function Advice({ title, action, children }: { title: string; action: string; children: React.ReactNode }) { return <section className={styles.advice}><h3>{title}</h3>{children}<button>{action} ›</button></section>; }
