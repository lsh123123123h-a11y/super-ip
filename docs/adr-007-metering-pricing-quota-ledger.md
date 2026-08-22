# ADR-007：Metering、Pricing、Quota 与 Ledger

## Context

Provider 原始 usage、平台计量、价格和余额是不同事实。仅把 token/cost 塞在调用 JSON 中无法版本化重算、预算预占、退款或审计；把 New API 的上游计费直接当作本平台账单也会混淆技术与商业语义。

## Decision

- `UsageFact` 是标准化、不可变、幂等计量事实；Provider 原始响应保留用于诊断，但不直接成为账本。
- `PriceBook(version)` 与 `PricingRule` 以生效时间和 tenant/global scope 定价，Usage 在发生时固定 price book/rule version。
- 高成本执行可先建立 `UsageReservation`，在调用前检查 tenant hard quota 与 ProductionOrder budget；成功后 settle 为 UsageFact + release + debit，失败/取消显式 release。
- `LedgerEntry` 是 append-only 派生账本，reservation、release、debit、refund、adjustment 均新增记录，不原地更新历史。唯一 idempotency key 保证重复报告/结算不重复计费。
- `UsageReporter` 是 Provider、Brain 与后续 Tool/Workflow 的统一写入边界；现有 AI 调用报告 token，Provider reporter 同时记录平台 request 与标准 usage metrics。

## Alternatives

- 使用 Provider 返回 cost 作为最终账单：拒绝，口径、币种和缺失值不可控。
- 只在订单完成后汇总：拒绝，无法做调用前 hard quota/budget gate。
- 修改旧账本行完成退款：拒绝，失去审计链。
- 本阶段建设支付、发票、税务：拒绝；这是内部计量账本，不冒充财务总账。

## Consequences

执行入口需要提供稳定 idempotency key 和标准 metric/unit。未配置 PriceBook 时仍记录 UsageFact，但金额为零且不会伪造价格。预算/配额需要在关键外部调用前 reserve；本阶段已提供统一服务，新增高成本 Capability 必须接入该入口。

## Invariants

- Usage、PriceBook、PricingRule 与 Ledger append-only；纠错使用新 adjustment/refund。
- Usage 去重和 Ledger exactly-once 由数据库唯一约束保证。
- 价格版本在 reservation/settlement 时固定，历史不被新价格重写。
- hard quota 在已用量 + 预占 + 本次估算超过上限时拒绝。
- Provider usage、平台 usage、价格和账本保持分层；账本不宣称外部支付事实。

## Migration impact

`20260822_0012` 新增 usage facts、versioned price books/rules、tenant quotas、reservations 与 ledger entries，并加入 tenant 索引、幂等唯一约束、RLS 和 append-only trigger。既有 Invocation 记录保持，后续调用同时写标准 UsageFact；历史数据不猜测回填金额。

## Failure / recovery semantics

重复 report/settle 返回已存在事实，不产生第二笔 debit。调用失败或取消必须 release reservation；settle 超出 hard quota/budget 时拒绝且 reservation 保留供显式 release/retry。Pricing 缺失不阻断事实采集。退款引用原 LedgerEntry 并新增负向记录；人工调整必须带操作者与原因。数据库事务失败不会部分提交 usage 与 ledger。
