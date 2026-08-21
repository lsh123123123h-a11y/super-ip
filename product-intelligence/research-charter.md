# Research Charter — 超级 IP 营销智能体：竞品、管理端与模型网关研究

- As of: 2026-08-20
- Mode: deep
- Decision to unlock: 确定生产级超级IP营销SaaS的产品骨架、管理端范围，以及云端API/本地模型统一路由架构
- Geography: 中国市场
- Target users/buyers/non-users: 初始研究对象为管理一个或多个个人 IP 的内容运营者、获客团队和代运营机构；买方是老板/营销负责人，日常操作者是策划、文案、剪辑和投放人员，受益者是 IP 主理人及其业务团队；不以纯娱乐型虚拟偶像和只需要单次视频生成的消费者为首发对象。
- Time horizon: 未来 12 个月的产品骨架与 90 天可落地的第一阶段。
- Constraints: 独立 SaaS；首个本地数字人引擎为 Duix；必须同时容纳云端 API 与本地模型；现有 Next.js + FastAPI + PostgreSQL + Redis 基础保留；中国内容平台与合规环境优先。
- Success criteria: 形成可追溯的竞品模块/交互矩阵、推荐产品骨架、用户端/管理端信息架构、统一模型能力网关方案、明确的阶段边界和不做清单，足以支持下一轮 PRD 决策。
- Explicit non-goals: 不复制竞品代码或品牌；不在本轮执行付费生成、发布、账号改动；不在产品方向审批前扩建业务功能；不把 New API 直接等同于业务编排层。
- Research stop conditions: 三个本地竞品均完成可验证的模块与流程拆解；New API 的模型/渠道/令牌/计费/路由机制完成一手资料核验；关键结论有反证或明确证据缺口；剩余不确定性用低成本实验比继续桌面研究更便宜。

## Uncertainty map

| ID | Known / assumption / unknown | Statement | Decision impact | Evidence or test |
|---|---|---|---|---|
| U-001 | known | 当前 ip-ai 只有独立 SaaS 底座与单条 Duix 工作流，尚无完整营销生产闭环和管理端。 | high | 用户直接反馈 + 本地产品检查 |
| U-002 | assumption | 最有价值的切入点是“多 IP 内容与获客运营系统”，而不是更多单点 AI 工具。 | high | 竞品流程对比 + 目标用户访谈/试用 |
| U-003 | unknown | 三个竞品的真实核心对象模型、首个价值时刻和留存环分别是什么。 | high | 本地应用实操与包内资源核验 |
| U-004 | unknown | 管理端首版必须覆盖哪些运营、成本、供应商、风控与审计能力。 | high | New API 机制 + 竞品后台/错误态 + 生产运维需求 |
| U-005 | assumption | 云端和本地模型应通过自有“能力网关”统一，而不是让业务代码直接绑定供应商模型名。 | high | New API 官方资料 + Provider 故障/成本场景 |
| U-006 | unknown | 首发买方应优先是单 IP 老板团队还是多客户代运营机构。 | high | 用户/渠道/付费证据；本轮只能给条件性建议 |
