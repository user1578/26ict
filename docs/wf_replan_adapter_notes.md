# WF_Replan v0.1.0 本地适配与评估原型

本说明对应 B 端离线原型，**不是已冻结的 AgentArts API**。A 尚未提供正式平台入口、认证、稳定输出、时区/日期和 POI 约定；当前只接受显式 `data_type: "simulation"` 的本地 JSON。没有云调用、真实模型生成、公开路由、自动确认或交易操作。SQLite schema 保持 v2。

## 1. 本地输入边界

入口：`app.replan_adapter.adapt_replan(bundle, measure=False)`，返回可 JSON 序列化的字典，不修改输入、不读写数据库、不访问外部服务。

完整可执行样例见 [wf_replan_simulation.json](../backend/tests/fixtures/wf_replan_simulation.json)。本地 envelope 有四个必需字段：

| 字段 | 来源与内容 |
| --- | --- |
| `data_type` | 固定 `simulation`；不提供真实 AgentArts 运行证明 |
| `workflow_input` | 本次 A 调用绑定：trip_id、formal_version、event_revision、history_revision、constraints、current_plan、active_events |
| `workflow_output` | A 的分析输出：trip_id、base_version、event_ids、draft_id、draft_status、options、warnings、official_version_unchanged |
| `context` | 独立提供的 B 正式状态、全部正式版本、事件绑定和各 option 的完整支持资料；不能把模型自己的声明当作该资料 |

`context.trip` 采用现有 GET `TripView`，`versions` 采用同一旅行的完整 `VersionView[]`（1 到 current_version，每版恰好一次，当前版与 trip.current_plan 一致）。历史版本用于保留曾被省略地点的预约要求，不能只看最近版本。实际接入时这些数据必须从可信 B 读取；本地 JSON 一致性检查不构成认证，也不能证明外部事实真实。

`workflow_input.current_plan.activities` 须完整对应正式基线。每行含 `activity_id/name/start_time/end_time`、可选 JSON 布尔 `fixed`（默认 false）；名称仅作展示。`active_events` 行含 `event_id/event_type/status/verification_status`；本地只接受 status=active，核实状态为 verified/unverified/unknown，可选 severity 字符串、confidence（0～1）、开始/结束时间。后者只保留分析，不转换为 B 异常事实。

本地 `constraints` 可含 `budget_remaining_cny`、`return_deadline`、`return_deadline_hard`、`fixed_activity_ids`、`user_authorizations`、`return_transport_options`。首版明确将 user_authorizations 定义为“获准提出改期建议的活动 ID 数组”，不解释任意自然语言授权或未知对象；平台实际格式须与 A 再确认。额外字段拒绝，而不是静默猜测。

`workflow_output.draft_status` 仅 needs_information/awaiting_confirmation。每个 option 必含 `option_id/feasibility/changed_activity_ids/additional_estimated_cost_cny/warnings/requires_external_actions/proposed_schedule`，feasibility 仅 conditional/feasible；费用允许 null。schedule 行必含 `activity_id/name/start_time/end_time/action/reason`，action 为 keep/reschedule/new_candidate。时间可以 null，但不会因此自动沿用原时间。重复/非法 ID、错误布尔值或未知字段返回结构化原因。

## 2. 字段映射与资料要求

| A / 本地字段 | B / 处理方式 |
| --- | --- |
| formal_version/base_version=`v1` 或正整数 1 | `CreateDraft.base_version=1`；必须等于当前正式版 |
| 调用 event_revision/history_revision | 精确绑定当前修订；输出可不回显，若回显也必须匹配 |
| activity_id | `StoredActivity.id`，稳定 ID，不从名称生成 |
| start_time/end_time | 转为带偏移完整 datetime；必须与独立活动资料中的时段一致 |
| event_ids | 经 context.event_bindings 映射成排序的 handled_event_ids，精确覆盖全部 B active 事件 |
| 一个 option | 一个完整候选 TravelPlan 和独立 CreateDraft 请求；不改变现有一草案一完整方案设计 |
| draft_id + option_id + 基线及候选快照 | SHA-256 内容摘要生成有效 B draft_id/request_id；相同规范化输入稳定，不同候选不共用 ID |
| warnings、requires_external_actions、feasibility、改动声明、name/reason、事件 severity/confidence | 保留在独立 analysis，不写进正式业务模型，不把声明当成核验结论 |
| budget_remaining_cny | 仅分析；不替换 B 整趟旅行 budget_cny，也不乘以人数 |
| additional_estimated_cost_cny | 仅分析；不生成费用流水，不当作 budget_delta，更不创建 paid/received 事实 |

仅有 `11:00` 时，必须明确提供该活动日期（`context.activity_dates` 或该 option 支持资料的 activity_dates）及 `context.timezone_offset`，例如 `+08:00`；不会从旅行开始日期、正式活动时间或数组位置猜日期。完整但无偏移的 ISO 时间也必须有明确 offset。完整带偏移时间可直接使用，日期仍按提供的旅行范围检查。当前只支持固定 UTC 偏移，不负责 IANA 时区、夏令时歧义或跨午夜结束日期推断；跨日请用完整时间。字段缺失/null 不等于零或原值。

`context.event_bindings` 必须逐一明确绑定 A 事件 ID 到**已存在**的 B 有效事件 ID。site_closure、transport_disruption 不自动变为 poi_closed/train_delay；通用中断不意味着列车晚点，地点关闭也不能仅凭名字映射。映射前须由调用方明确收窄为 B 支持的真实业务事实；缺少映射或 B 事实则不能转换。B 的 unverified 事件继续导致 UNKNOWN。

`context.option_support[option_id]` 的严格结构：

- `activities`：按 activity_id 索引的完整 B `StoredActivity`；新增、改期或前一活动 ID 改变的路段必须提供。POI ID、明确时段及开放/预约/交通资料由此输入，不能从名称或模型可行性推导。未变动活动可复用正式属性；路线拓扑改变时不能复用旧路段。
- `activity_dates`：按活动 ID 明确提供的 `YYYY-MM-DD` 日期，供只有时分的 schedule 使用。
- `removed_activity_ids`：必须恰好列出候选省略的原活动。schedule 是完整序列，不按增量补丁解释，防止无意删除活动。
- `charges/refunds`：必须显式提供候选的两份完整费用流水，包括空数组。缺省/null 属于信息不足，不用额外费用估算填补，也不自动将未知成本设为零。
- `arrival_at_return_station`：候选到站时间；B 有截止或既有到站预测时必须重新明确提供，不能自动沿用旧预测，更不能用返程活动结束时间替代。
- `activity_evidence/financial_evidence`：独立事实引用。未变动事实可继承已有引用；活动属性或前序地点变更时移除继承的活动证据，需显式提供对应候选证据。已有 paid/received 对应引用保留；尝试改写付款、到账退款或证据仍会被现有 B 核验拒绝。

每个新活动必须使用新稳定 ID 和 new_candidate；keep/reschedule 只能引用原活动，keep 不能改变原时段或 POI。前序活动 ID 不变但 POI 改变时，也必须重新提供后续路段资料。支持资料本身仍受 B 模型校验：缺失 POI、无时区/非法时段、重复流水等不会被补造。没有关键证据或交通信息时，复用 validate_snapshot 得到 UNKNOWN，不生成可提交请求。模型称 feasible 也可能得到 B FAIL。

## 3. 适配结果与成功/失败示例

顶层及各 option 的内部适配状态为 successfully_adapted / needs_information / rejected，**不替代**数据库 pending/stale/committed。顶层 successfully_adapted 只表示至少一个 option 成功，使用方必须逐项检查，不能提交其他失败项。

成功结果摘录（digest 是固定格式内容摘要，实际完整请求见命令输出）：

```json
{
  "status": "successfully_adapted",
  "option_id": "OPT_A",
  "draft_request": {
    "base_version": 1, "event_revision": 1, "history_revision": 0,
    "handled_event_ids": ["B-E1"]
  },
  "evaluation": {
    "changed_activity_count": 1, "added_activity_count": 0,
    "unchanged_activity_retention_rate": "0.5", "budget_delta_cny": "0.00",
    "candidate_validation_status": "PASS", "adapter_elapsed_ms": null
  }
}
```

实际每项还包含 `analysis/issues/candidate_plan`；draft_request 含真正的 draft_id/request_id 和完整 plan，符合既有 CreateDraft。适配器只返回请求，调用方如需落库仍必须走 B 现有接口，确认仍需用户明确确认并在事务内重新校验。适配成功到提交之间若事件/锁定/版本改变，旧请求或旧草案仍会被拒绝。

只有时分且缺少活动日期的失败结果摘录：

```json
{
  "option_id": "OPT_A", "status": "needs_information", "draft_request": null,
  "issues": [{
    "code": "missing_date", "field": "proposed_schedule.A1.start_time",
    "reason": "只有时分，必须明确提供该活动的日期", "option_id": "OPT_A"
  }]
}
```

结构不完整时 candidate_plan=null，不会强行生成方案；能构成 B 快照但核验 FAIL/UNKNOWN 时保留候选及核验细项供检查，draft_request 仍为 null。全局基线/事件集错误列在顶层 issues，options=[]；各 option 的缺失信息或拒绝原因含对应 option_id，不妨碍其他独立完整 option。options=[] 表示 A 没有安全方案，原样保留，不生成兜底行程。

A 的 needs_information、conditional 或未完成 requires_external_actions 都阻止生成可提交请求，即使 B 在已有输入条件下得到 PASS；两种结论属于不同层次。分析原文独立保留，不为 UNKNOWN 制造 simulation:PASS 引用。本地 fixtures 的 simulation 证据仅测试已有确定性逻辑，不能作为真实预约、付款或开放事实。

## 4. 固定活动及返程未决语义

B 以 locked_activity_ids 标识不可修改历史，不按当前机器时间推断活动“已完成”。这些活动及证据不能被 A 的授权解除。未来固定活动由 A 输入 fixed/fixed_activity_ids 和既有 confirmed 预约识别；未经授权的调整拒绝，即使授权也只报告 fixed_reschedule_unsupported。当前没有取消/重订/改签接口，不把授权当作预约改签已成功。普通可调活动仍须满足原有预约事实与所有硬约束。

**返程冲突未解决**：A 的“完整返程完成严格早于截止”与 B 的“到达返程车站时间 <= 截止”不是同一概念。原型不修改 B 原有 <= 或到站含义。A 输入带 return_deadline，或声明 return_deadline_hard=true 时，各完整候选返回 return_deadline_semantics_unresolved，不生成草案请求，等待 A/B 明确定义，不能把 B 的 PASS 冒充满足 A 的返程要求。

负例测试保留：A3 为 14:00—16:00，固定 A4 为 17:00—18:00，A 只授权 A3，硬性返程完成截止 15:30。适配器不能把它交付为完整可行方案；独立 B return_check 仍可在 B 到站恰等于 B 截止时 PASS，这个结果不能替换 A 的定义。

## 5. 评估指标

独立入口 `app.replan_evaluation.evaluate_replan`，输入 baseline/candidate 完整 B TravelPlan、constraints、events、locked_activity_ids、required_booking_pois（由全部正式历史收集；无预约要求时显式空数组）。不依赖适配器、数据库或 AI，可单独运行。

| 指标 | 确定性口径 |
| --- | --- |
| changed_activity_count | 对基线稳定 ID 逐个比较完整 StoredActivity 属性；删除、改 POI、时间及其他行程属性改变都计数 |
| added_activity_count | 候选中不属于基线的活动数，单独统计 |
| unchanged_activity_retention_rate | 未变原活动数 / 原活动总数；新增活动不进分母，Decimal 28 位精度字符串；name/reason 不属于 B 活动属性 |
| hard_constraint_result | 完整复用 validate_snapshot（内部复用 validate_plan），包含证据、异常、预约、财务和历史检查 |
| budget_delta_cny | 候选 conservative_total - 同一正式基线 conservative_total；十进制人民币元字符串，不累计历史版本；pending 退款不抵扣 |
| locked_activity_violations | 历史锁定活动缺失、完整属性改变或证据引用改变的稳定 ID 列表 |
| candidate_validation_status | B 的 PASS/FAIL/UNKNOWN，不取 A feasibility 值 |
| adapter_elapsed_ms | 默认 null（未测量）；仅 --measure 时实测每个 option 的本地转换、校验及指标计算耗时，不含云网络或 AgentArts 推理 |

缺少候选、完整费用流水或必要校验上下文时，相关评估整体为 UNKNOWN、指标 null，unavailable_reasons 说明原因，不用 0/PASS 替代。金额及比率不采用二进制浮点运算，没有综合评分、随意权重或“最优”结论。

默认不读时钟，相同输入转换与评估 JSON 一致。--measure 是显式附加测量，耗时随运行变化，不参与内容摘要或质量评分；可重复性比较时应排除该观测字段。它不能用于宣称 AgentArts 更快或某种算法性能已改善。

## 6. 本地运行和待协调项

在仓库 backend 目录，复用现有 Python 3.11 虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m app.replan_adapter tests/fixtures/wf_replan_simulation.json
.\.venv\Scripts\python.exe -m app.replan_adapter tests/fixtures/wf_replan_simulation.json --measure
.\.venv\Scripts\python.exe -m app.replan_evaluation tests/fixtures/replan_evaluation_simulation.json
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_cache/state-tests
```

两个 CLI 输出 UTF-8 JSON 到标准输出，不生成报告文件或访问默认业务库。命令正常结束只代表运行完成，必须检查 JSON 内的状态。第三条可独立复现评估，不需要先执行第一条。fixtures 约 17 KB，无需安装新依赖。自动化落库测试只使用 pytest 专用临时 SQLite，验证一次转换后 E2 到来旧草案失效、重适配处理全部异常和用户确认，schema 仍为 v2。

仍需 A 提供：真实调用入口及认证、严格版本化输出、完整日历/时区、真实地点和交通映射、费用与证据来源、事件的可验证收窄规则、授权对象格式、返程完成定义和未来固定预约改期流程。当前不提供通用中断、weather 异常或自动平台重试，不执行付款、退款、改签或预约。

C 仍需将 A options 按 option_id 展示为分析候选，并按每项适配状态决定可用操作；成功项的 B 独立草案 ID 不等于 A 的父 draft_id。不得直接提交 A options 或仅凭 feasible 允许确认。B 端不修改 C 页面或 A 工作流，不新增 /progress、/export 或公开重规划入口。
