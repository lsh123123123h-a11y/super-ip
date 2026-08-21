# Decision Ledger

## D-001 — 产品独立于 ChatGPT 发布

- Status: approved
- Owner/date: 用户 / 2026-08-20 前已明确
- Question: 产品最终是否依赖 ChatGPT/Codex 作为运行容器？
- Options considered: ChatGPT 内应用；独立 SaaS；纯本地桌面软件。
- AI recommendation/confidence: 独立 SaaS，高。
- User choice: 独立 SaaS，不发布在 ChatGPT。
- Evidence: E-001; E-002
- Strongest objection/counter-evidence: 独立 SaaS 增加认证、运维、计费与合规成本。
- Rationale and trade-offs: 获得自己的用户、商业模式、数据和多端入口；承担完整生产系统责任。
- Rejected alternatives and why: ChatGPT 内应用无法承载目标商业与本地 GPU/发布链；纯桌面不利于租户和商业后台。
- Reversibility: costly
- Validation/kill criterion: 所有核心用户流程均通过自有域名/API；不依赖 ChatGPT 身份或存储。
- Review trigger/date: 产品定义发生根本变化时。

## D-002 — 首个数字人引擎使用 Duix

- Status: approved
- Owner/date: 用户 / 2026-08-20 前已明确
- Question: 首个离线数字人口播 Provider 是什么？
- Options considered: Duix；OpenTalking；云厂商；多引擎同时接入。
- AI recommendation/confidence: Duix 首发，高。
- User choice: Duix。
- Evidence: E-001; E-013; E-014
- Strongest objection/counter-evidence: 本地 Duix 维护成本高，效果/SLA 与商业 API 可能不同。
- Rationale and trade-offs: 已有本地环境和适配器，适合先验证离线口播；通过 Provider 契约保留替换空间。
- Rejected alternatives and why: 当时资料把 OpenTalking 主要视为实时会话框架；最新核验表明其也支持视频创建/克隆，因此该理由已被 D-010 的双引擎 Spike 方案修正。多引擎同等首发仍会扩大验证面。
- Reversibility: reversible
- Validation/kill criterion: H-004；若真实项目端到端成功率低于 75%，停止扩 UI，先替换/补充 Provider。
- Review trigger/date: 完成 10 个真实内容项目后。

## D-003 — 必须具备管理端和云端/本地选择

- Status: superseded
- Owner/date: 用户 / 2026-08-20
- Question: 产品是否需要运营管理端，以及是否支持云 API 与本地模型？
- Options considered: 无管理端；仅云端；仅本地；统一管理端＋混合模型。
- AI recommendation/confidence: 统一管理端＋混合模型，高。
- User choice: 最初要求管理端及云端 API/本地模型可选；随后澄清为通用 AI 主要走云 API，数字人视频允许本地/自托管执行。
- Evidence: E-001; E-004; E-005; E-010; E-015; E-016
- Strongest objection/counter-evidence: 混合部署增加节点运维、安全和支持复杂度。
- Rationale and trade-offs: 支持成本、隐私、质量和供应风险策略；必须用分阶段能力控制复杂度。
- Rejected alternatives and why: 单一渠道会锁定供应商且无法满足本地隐私/成本目标。
- Reversibility: costly
- Validation/kill criterion: H-003、H-005。
- Review trigger/date: 已由 D-008 取代；管理端边界由 D-007 承接。

## D-004 — 自有 Capability Gateway，New API 作为可选通用中继

- Status: approved
- Owner/date: 用户 / 2026-08-20
- Question: New API 应处于系统哪一层？
- Options considered: 直接作为业务后端；直接作为所有能力网关；置于自有能力网关之后；完全自研替代。
- AI recommendation/confidence: 自有业务编排与 Capability Gateway；New API 仅负责标准云模型渠道，数字人和视频使用专用异步 Adapter，高。
- User choice: 强调 New API 边界并要求把编排层做好。
- Evidence: E-001; E-002; E-010; E-013; E-023; E-028; E-029; C-008; C-009; C-023; C-032
- Strongest objection/counter-evidence: 多一层网关增加部署与追踪复杂度；New API 已覆盖部分多媒体任务。
- Rationale and trade-offs: 业务只依赖稳定能力合同；New API 快速接通用云渠道；数字人本地/云执行位置由编排层屏蔽，不丢素材、进度、成本和产物语义。
- Rejected alternatives and why: New API 直接做业务层无法表达 IP、作品、素材依赖和人工复核；全自研会重复渠道/计费工程。
- Reversibility: costly
- Validation/kill criterion: H-003；若双层网关显著增加失败且不能实现无业务改动切换，则合并边界。
- Review trigger/date: 首个 Duix/OpenTalking 双适配回归完成后。

## D-005 — 用“营销活动”统领内容，而不是复制智能体商店

- Status: approved
- Owner/date: 用户 / 2026-08-20
- Question: 用户端主信息架构是工具/智能体优先，还是 IP/活动/项目优先？
- Options considered: 30+ 智能体商店；轻语式单条视频向导；营销活动驱动的内容操作系统。
- AI recommendation/confidence: 营销活动驱动，中高。
- User choice: 接受此前交互逻辑与功能板块方向，不再展开异议。
- Evidence: E-001; E-003; E-004; E-005; C-006; C-007; C-024
- Strongest objection/counter-evidence: 早期用户可能只想快速生成一条视频，不理解“活动”对象。
- Rationale and trade-offs: 让内容、渠道、成本和效果围绕同一目标闭环；同时保留“一键快速成片”快捷入口。
- Rejected alternatives and why: 智能体商店容易碎片化；纯单视频向导难形成营销复盘和团队协作。
- Reversibility: costly
- Validation/kill criterion: H-001；活动流原型不得降低首次任务完成率。
- Review trigger/date: 原型测试完成后。

## D-006 — 首版发布采用官方能力优先＋受控手动交付

- Status: proposed
- Owner/date: 待用户确认
- Question: 首版是否做全平台无人值守自动发布？
- Options considered: 浏览器自动化全平台；全部手动；抖音官方 API＋其他平台导出/分享；延后发布。
- AI recommendation/confidence: 抖音官方 API，其他平台先做合规导出包/调起发布，中高。
- User choice: pending
- Evidence: E-004; E-005; E-019; E-020; C-015; C-016
- Strongest objection/counter-evidence: 手动一步会削弱“一键闭环”的营销卖点。
- Rationale and trade-offs: 降低账号风控和持续维护成本，用真实完成率而非按钮数量衡量价值。
- Rejected alternatives and why: 未经官方能力支持的无人值守自动化风险高；完全延后发布会切断闭环。
- Reversibility: reversible
- Validation/kill criterion: H-006。
- Review trigger/date: 获得更多平台正式发布权限时。

## D-007 — 用户端与运营管理端分离

- Status: approved
- Owner/date: 用户 / 2026-08-20
- Question: 管理能力放在同一导航还是独立 Admin？
- Options considered: 同一应用混合；独立路由/子域管理端；完全独立代码库。
- AI recommendation/confidence: 独立 Admin 应用边界，早期可同仓，中高。
- User choice: 明确产品应有管理端，并认可此前功能板块方向。
- Evidence: E-004; E-010; E-017; E-018; C-020
- Strongest objection/counter-evidence: 早期维护两个前端增加开发量。
- Rationale and trade-offs: 权限、审计和操作风险边界清晰；共享设计系统/API 类型降低重复。
- Rejected alternatives and why: 在用户端暴露高风险配置会增加误操作和安全面。
- Reversibility: reversible
- Validation/kill criterion: Admin 路由必须有独立 RBAC 与审计；若同仓无法保证边界则拆仓。
- Review trigger/date: 首个非创始人运营账号加入前。

## D-008 — 通用 AI 云优先，数字人视频允许混合执行

- Status: approved
- Owner/date: 用户 / 2026-08-20
- Question: 哪些能力需要云端/本地双路径？
- Options considered: 全能力纯云；所有能力云/本地都做；通用 AI 云优先＋数字人/媒体渲染混合执行。
- AI recommendation/confidence: 通用 AI 云优先，数字人视频支持本地、自托管和云 API Worker，高。
- User choice: 不是所有模型都要求纯云；数字人视频可以走本地，并评估 Duix、OpenTalking。
- Evidence: E-001; E-005; E-010; E-013; E-028; E-029; C-031; C-032
- Strongest objection/counter-evidence: 本地/自托管媒体 Worker 会增加 GPU、版本、素材传输和故障支持成本。
- Rationale and trade-offs: 将复杂混合部署限制在高成本、长耗时、可自托管的数字人/媒体能力，避免把通用 LLM 也扩成多套本地运维。
- Rejected alternatives and why: 全能力纯云减少选择和成本控制；全能力混合会让产品过早成为模型运维平台。
- Reversibility: costly
- Validation/kill criterion: 同一 avatar.render 合同至少通过一个 Duix 路径和一个 OpenTalking 路径；执行位置切换不改业务对象和前端流程。
- Review trigger/date: 双引擎技术 Spike 完成后。

## D-009 — 以轻语 IP 全能力做功能等价目标

- Status: approved
- Owner/date: 用户 / 2026-08-20
- Question: 轻语 IP 对标到何种深度？
- Options considered: 只学交互；复刻少数核心能力；实现全能力功能等价；逐像素/逐代码复制。
- AI recommendation/confidence: 全能力功能等价、分阶段交付；不复制代码、品牌素材或独特界面表达，高。
- User choice: 轻语 IP 所具有的所有能力可以完全复刻。
- Evidence: E-001; E-005; E-026; E-027; C-005; C-021; C-022; C-033
- Strongest objection/counter-evidence: 一次性全做会重演功能很多但不可生产的问题，并扩大发布、售后、合规与供应商成本。
- Rationale and trade-offs: 把“完全复刻”定义为用户结果和业务闭环等价；通过 Phase 1–3 建设，不把所有能力塞进首版。
- Rejected alternatives and why: 只做少数能力不足以形成目标闭环；逐像素/代码复制有权属风险且不会形成差异化。
- Reversibility: costly
- Validation/kill criterion: 建立能力对照矩阵；每项能力必须有真实输入、任务状态、可用产物、成本与失败恢复，不以静态页面计入完成。
- Review trigger/date: 每个 Phase 验收时更新差距矩阵。

## D-010 — Duix 主生产、OpenTalking 第二引擎和扩展框架

- Status: approved
- Owner/date: 用户 / 2026-08-20
- Question: Duix 与 OpenTalking 在数字人视频编排中的角色如何分工？
- Options considered: 只用 Duix；双引擎同等首发；Duix 主生产＋OpenTalking 技术 Spike/第二引擎；只用 OpenTalking。
- AI recommendation/confidence: Duix 继续承担首个生产闭环；OpenTalking 同期做合同级 Spike，验证视频创建/克隆后作为第二引擎，中高。
- User choice: A——Duix 主生产，OpenTalking 同期做合同级技术验证，通过后作为第二引擎。
- Evidence: E-001; E-013; E-028; E-029; C-026; C-027; C-032
- Strongest objection/counter-evidence: OpenTalking 已覆盖视频创建/克隆，若其目标场景效果或成本明显更优，Duix 主引擎顺序可能不成立。
- Rationale and trade-offs: 保住已有 Duix 适配资产，同时不再把 OpenTalking误判为仅实时会话；用统一合同和样片基准做数据化选择。
- Rejected alternatives and why: 双引擎同等首发扩大故障面；只用一个引擎削弱容灾和场景覆盖。
- Reversibility: reversible
- Validation/kill criterion: 用同一组 10 个素材/音频完成质量、耗时、成本、失败率和授权边界对照；落后路径只保留可验证的差异场景。
- Review trigger/date: 双引擎 Spike 与供应商商务资料齐备后。
