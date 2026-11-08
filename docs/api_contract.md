# TravelGuard B 端 API 契约草案（第四阶段）

状态：**供 A、B、C 联调确认的草案**，尚未经 A、C 共同确认，不作为已冻结的稳定版本。以本分支实际 `/openapi.json` 及 `backend/app/*schemas.py` 为字段定义；本文解释业务语义。保留既有预算、校验与旅行状态接口，不开发 A 的工作流或 C 的页面。

第五阶段的 WF_Replan 离线适配与评估原型见 [适配说明](wf_replan_adapter_notes.md)，属于独立开发工具，不新增正式公开 API，不改变本文既有 schema v2、草案、锁定或 PASS 确认语义；AgentArts 平台接口尚未接入。

## 1. 调用与认证

- 本机服务示例：`http://127.0.0.1:8000`，JSON UTF-8。`GET /health` 为存活检查，不证明外部服务已配置。
- 除健康检查和现有 OpenAPI 文档外，下列接口均要求 `X-Tool-Key` 请求头。服务端从 `TRAVELGUARD_TOOL_API_KEY` 读取共享密钥；未配置返回 503，缺失或不匹配返回 401。
- A 在 AgentArts 的安全凭据配置中传递工具密钥；高德、和风的密钥只留在 B 端环境变量，绝不进入工具参数、响应、前端或源码。
- C 的 React 使用同源 `/api/...` 调用，经**本机开发服务代理**在服务端注入 `X-Tool-Key`。C 负责配置代理，勿用 `VITE_` 环境变量把任何密钥打入浏览器包。当前 B 端没有生产用户登录、多租户隔离或公开跨域授权；共享工具密钥及 `confirmed_by` 不能证明真实用户身份。不可直接公开当前服务。
- `.env.example` 只展示变量；服务启动时读取 `backend/.env`，进程环境优先。配置、数据库和密钥均不提交；不打印带高德 `key` 查询参数的完整请求 URL。

## 2. 标识、时间、费用与状态

| 字段 | 约定 |
| --- | --- |
| `trip_id` | 调用方生成的旅行 ID，旅行内保存完整约束、正式版本和异常 |
| `poi_id` | 地点 ID；新高德搜索返回 `amap:<高德原始ID>`，知识库使用同一个完整 ID。既有 `WH01` 等 ID 继续有效，无自动别名/迁移 |
| 活动 `id` / `activity_id` | 某次访问/交通活动的稳定 ID；同一地点可有多个活动，不能用地点 ID 代替活动 ID |
| `event_id` | 旅行内稳定异常 ID，PUT 同 ID 更新/解除；`handled_event_ids` 必须恰好覆盖全部 active 异常 |
| `draft_id` | 调用方生成的候选草案 ID；草案不能覆盖，重新生成需新 ID |
| 费用 `id` | 同一完整快照内支出和退款共享唯一命名空间；同一事实跨版本保留原 ID，不能每次生成新 ID 重复计费 |
| `request_id` | 同一旅行内写操作的幂等键，覆盖创建旅行、事件、草案、确认、锁定；外部只读工具无需此字段 |
| `version` / `current_version` | 正式版本从 1 递增；草案 `base_version` 引用生成时的正式版本 |
| `event_revision` | 当前异常集合的修订号，从 0 开始，异常新增/变更/解除后递增 |
| `history_revision` | 历史锁定修订号，从 0 开始，新增历史锁定后递增 |

旅行持久化及新增工具的 ID 长度为 1–128，不允许空白、`/`、`\`。原无状态预算/校验工具继续接受原有 ID 规则（非空字符串）。同一旅行的活动 ID 不重复。

时间为带时区的 ISO 8601，例如 `2026-10-21T10:00:00+08:00`；拒绝无时区时间。服务生成时间使用 UTC（`Z`/`+00:00`）。旅行时间按实际时刻比较，不按字符串排序。地点规则必须覆盖**完整访问时段**；跨日/午休应拆成准确有效时段，不能把“白天开放”泛化为整日开放。

天气 `on_date` 是 `YYYY-MM-DD`，当前仅按 `Asia/Shanghai` 日历查询今天起 7 日内预报。路线使用 GCJ-02，经纬度按**经度、纬度**传递；和风天气支持显式 `GCJ-02` 或兼容原有 `WGS84` 输入，默认仍为 `WGS84`。大陆 GCJ-02 直接传递；大陆 WGS84 会转换到 GCJ-02 用于天气网格查询，URL 按每日预报文档保留两位小数；其他地区保留 WGS84。路线字段为秒/米，输入既有行程时长仍为分钟，换算应使用 `ceil(seconds / 60)`，`null` 不能转为 0。

所有 `*_cny` 为人民币元，输入推荐十进制字符串，最多两位小数；响应为 JSON 字符串，不能依赖 JavaScript 浮点累加。费用快照是**全量账本，不是增量**：只取当前正式版本计算，不累加历史版本。预算公式：`paid + planned - received`；`pending` 退款独立展示，绝不抵扣。

| 枚举 | 语义 |
| --- | --- |
| `PASS` | 针对当前输入/指定检查通过；不代表外部事实已经独立核实或真实交易已经执行 |
| `FAIL` | 已知违反检查条件；优先于 UNKNOWN |
| `UNKNOWN` | 缺数据、缺证据或无法核实；必须补充信息，不能降级为 PASS |
| `NOT_APPLICABLE` | 该检查不适用，不能用来覆盖其他 UNKNOWN/FAIL |
| 草案 `pending/stale/committed` | 待确认/绑定状态过时/已形成正式版本。pending 仍可能是 FAIL 或 UNKNOWN |
| 支出 `paid/planned` | 已支付事实/尚在计划的费用 |
| 退款 `received/pending` | 已到账事实/待到账退款 |
| 活动开放 `confirmed_open/confirmed_closed/unknown` | 输入声明的开放/关闭/未核实 |
| 预约 `confirmed/not_confirmed/unknown` | 输入声明的已确认/未确认/未知，仅对 `booking_required:true` 执行预约检查 |

## 3. React 与 AgentArts 共用的业务 API

| 方法与路径 | 请求模型 | 成功响应 |
| --- | --- | --- |
| POST `/api/trips` | `CreateTrip` | 201 `TripView`，只接受核验 PASS 的 V1 |
| GET `/api/trips/{trip_id}` | 无 | 200 `TripView` |
| GET `/api/trips/{trip_id}/versions` | 无 | 200 `VersionView[]`，按 version 升序 |
| PUT `/api/trips/{trip_id}/events/{event_id}` | `PutEvent` | 200 `EventView` |
| POST `/api/trips/{trip_id}/drafts` | `CreateDraft` | 201 `DraftView`，可保存 FAIL/UNKNOWN 供比较 |
| GET `/api/trips/{trip_id}/drafts` | 无 | 200 `DraftView[]` |
| GET `/api/trips/{trip_id}/drafts/{draft_id}` | 无 | 200 `DraftView` 当前状态 |
| POST `/api/trips/{trip_id}/drafts/{draft_id}/confirm` | `ConfirmDraft` | 200 `VersionView` |
| POST `/api/trips/{trip_id}/locks` | `LockActivities` | 200 `TripView` |

`TravelPlan` 必含 `activities`（至少一个）。可选字段：`charges:[]`、`refunds:[]`、`arrival_at_return_station:null`、`activity_evidence:{}`、`financial_evidence:{}`。活动必含 `id/poi_id/start_at/end_at`；其余字段及默认值见下例。多活动间需交通耗时，配置步行限制后还需步行耗时，否则 UNKNOWN。预约要求缺失默认 false 是**兼容旧接口的行为**，不能据此推断外部真实地点无需预约；A 应先取得预约规则。

`activity_evidence[活动ID]` 保存已声明开放/完成预约的证据引用；`financial_evidence[流水ID]` 保存 paid/received 的证据引用。引用不能为空，必须属于当前快照。后端保存引用但不会联网验证引用内容；模拟引用只用于模拟案例。初始事实由可信调用方明确提供，不能把外部 UNKNOWN 转成 `confirmed_open`。

### 3.1 创建和读取示例

#### 旅行基础信息与偏好（P6）

以下字段位于 `CreateTrip` 请求和 `TripView` 响应顶层，POST 创建成功和 GET 读取均返回；版本、草案、异常和费用快照结构不变。

| 字段 | JSON 类型 | 创建时必填 | 校验与缺省值 |
| --- | --- | --- | --- |
| `city` | string 或 null | 否（兼容旧请求） | 去除首尾空白后非空；缺省/null 表示未知 |
| `party_size` | integer 或 null | 否（兼容旧请求） | 1～10；拒绝布尔值、字符串及小数；缺省/null 表示未知 |
| `start_date` | string 或 null | 否（兼容旧请求） | 真实日历日期，严格 `YYYY-MM-DD`；缺省/null 表示未知 |
| `end_date` | string 或 null | 否（兼容旧请求） | 同上；两日期均有值时，结束日期不得早于开始日期（允许同一天） |
| `preferences` | object | 否 | 缺省返回 `{"stay_together":null}`，对象本身不接受 null |
| `preferences.stay_together` | boolean 或 null | 否 | 仅接受 JSON true/false/null；缺省/null 表示未知，不自动设为 true |

为兼容历史调用，四个基础字段可分别省略；只提供一个日期时另一个仍为 null，不推断日期。C 的新建表单应发送完整基础信息。日期不带时间和时区；活动和返程截止仍须带时区。当前只校验基础字段自身及日期先后，尚未增加活动所属城市、活动是否落在旅行日期范围内的核验。

`preferences` 保存旅行意愿，与 `constraints` 中已有预算、单段步行和返程硬约束分开。**当前没有按成员划分的路线或多人全程同行校验算法**，`stay_together:true` 不产生同行检查 PASS，也不因该偏好未知而阻止旧请求创建；方案整体 PASS 不能解释为已验证全程同行。`party_size` 不自动乘入费用，`budget_cny` 仍是整趟旅行总预算。正式 V1 与后续确认仍要求全部现有必要核验 PASS。

P6 与 `origin/cmx/frontend@1eaae97` 的只读核对结果如下（前端尚未接入真实 API，以下映射由 C 接入时实现）：

| C 端现有字段 | B 端创建请求 | B 端读取响应 |
| --- | --- | --- |
| 表单 `city` / Trip `city` | `city` | `city` |
| 表单 `partySize` / Trip `party_size` | 数值整数 `party_size` | `party_size` |
| 表单 `startDate/endDate` / Trip `dates[0]/dates[1]` | `start_date/end_date` | `start_date/end_date`，C 可转回 dates 数组 |
| 表单 `budget` / Trip `budget_cny` | 十进制金额 `budget_cny` | `constraints.budget_cny`（JSON 字符串） |
| 表单 `walkingLimit` | `max_walking_minutes_per_leg` | `constraints.max_walking_minutes_per_leg` |
| 模拟 Trip `constraints.stay_together`（当前固定 true） | `preferences.stay_together` | `preferences.stay_together` |
| 表单 `endDate + returnTime` | 带目的地时区的 `return_deadline` | `constraints.return_deadline` |

武汉示例的返程时区为 `+08:00`，不能直接使用浏览器所在时区。C 须处理旧数据的 null，不能把未知城市、人数或日期替换成虚构默认值；现有前端必填类型也需在接入适配时处理未知值。B 不接受 `dates`、`startDate/endDate`、顶层 `stay_together` 或创建请求中的嵌套 `constraints` 别名；这些不是此前支持的后端请求格式。

#### 完整基础信息创建与读取

下列行程、来源与金额全部为模拟例子，不代表地点真实规则。

`POST /api/trips`：

```json
{
  "request_id": "create-1", "trip_id": "demo-trip", "title": "模拟行程",
  "city": "武汉", "party_size": 3,
  "start_date": "2026-10-21", "end_date": "2026-10-21",
  "preferences": {"stay_together": true},
  "budget_cny": "300.00", "max_walking_minutes_per_leg": 20,
  "return_deadline": "2026-10-21T18:00:00+08:00", "locked_activity_ids": [],
  "plan": {
    "activities": [{
      "id": "visit-1", "poi_id": "amap:B-demo",
      "start_at": "2026-10-21T10:00:00+08:00", "end_at": "2026-10-21T11:00:00+08:00",
      "opening_status": "confirmed_open", "booking_required": false, "booking_status": "unknown"
    }],
    "charges": [{"id": "ticket-1", "amount_cny": "50.00", "status": "paid"}],
    "refunds": [], "activity_evidence": {"visit-1": "simulation:opening"},
    "financial_evidence": {"ticket-1": "simulation:paid"},
    "arrival_at_return_station": "2026-10-21T17:00:00+08:00"
  }
}
```

201 和后续 GET 的顶层结构如下；`current_plan.plan` 是上述完整方案（含默认字段），核验 `checks` 为检查数组：

```json
{
  "trip_id": "demo-trip", "title": "模拟行程", "current_version": 1,
  "city": "武汉", "party_size": 3,
  "start_date": "2026-10-21", "end_date": "2026-10-21",
  "preferences": {"stay_together": true},
  "event_revision": 0, "history_revision": 0,
  "constraints": {"budget_cny": "300.00", "max_walking_minutes_per_leg": 20,
                  "return_deadline": "2026-10-21T18:00:00+08:00"},
  "locked_activity_ids": [], "events": []
}
```

上例为**顶层响应摘录**，另有必返字段 `current_plan: VersionView`：

| 模型 | 完整响应字段 |
| --- | --- |
| `VersionView` | `trip_id, version, event_revision, history_revision, source_draft_id, plan, budget, validation, confirmation, created_at` |
| `budget` | `budget_cny, paid_cny, planned_cny, received_refunds_cny, pending_refunds_cny, conservative_total_cny, remaining_cny, within_budget` |
| `validation` | `overall, checks:[{name,status,detail}], note` |
| `confirmation` | V1 为 null；确认后为 `{request_id, confirmed_by, confirmed_at}` |
| `DraftView` | `trip_id, draft_id, base_version, event_revision, history_revision, handled_event_ids, status, committed_version, plan, validation, created_at` |
| `EventView` | `event_id, revision` 加以下 `PutEvent` 的事实字段，不含 request_id/expected_event_revision |

`current_plan.validation` 是生成该版本时的核验快照；之后发生异常时不会改写旧版本，前端必须同时读取当前 `events/event_revision`，不可只看旧 PASS 就认为异常已解决。

#### 旧请求和 SQLite 兼容

旧格式请求仍有效，例如：

```json
{
  "request_id": "legacy-create-1", "trip_id": "legacy-trip", "title": "旧格式行程",
  "budget_cny": "300.00",
  "plan": {
    "activities": [{
      "id": "visit-1", "poi_id": "amap:B-demo",
      "start_at": "2026-10-21T10:00:00+08:00", "end_at": "2026-10-21T11:00:00+08:00",
      "opening_status": "confirmed_open"
    }],
    "activity_evidence": {"visit-1": "simulation:opening"}
  }
}
```

其响应的新增字段如下（仅摘录新增字段，完整 `TripView` 仍含正式版本、约束等）：

```json
{
  "city": null, "party_size": null, "start_date": null, "end_date": null,
  "preferences": {"stay_together": null}
}
```

服务启动使用 `BEGIN IMMEDIATE` 事务，将已知 schema 0/1 升至 2：只向 `trips` 增加可空的 `city TEXT`、`party_size INTEGER`、`start_date TEXT`、`end_date TEXT`、`preferences_json TEXT`，并更新 `PRAGMA user_version`。新库经过同一流程创建为 2；已为 2 时重复初始化不重复迁移。旧行的新列保持 SQL NULL，响应中映射为未知，**不从标题、活动日期或人数估算信息**。

迁移不删除/重建旧表，不重写既有约束、正式版本、草案、异常、费用或幂等回执；失败时新增列和版本号一同回滚。未知 schema 版本拒绝启动。未提供新信息的旧创建请求仍匹配原幂等指纹；旧回执由响应模型补齐新增 null 字段，不改变历史结果。向同一 request_id 添加已知基础信息或偏好是不同请求，返回 409，不能借重试回填旧旅行。本阶段未提供旅行基础信息编辑/回填接口。

迁移在服务启动时生效，本次自动化测试仅操作临时库，未对真实业务库执行升级。实际运行前应停用旧服务并保留数据库备份；旧二进制不支持 schema 2，回退代码时不能直接沿用升级后的库，应使用升级前备份并核对升级后新增数据。现有正式方案及全部费用语义保持不变。

### 3.2 异常、候选与用户确认

`PUT /api/trips/demo-trip/events/E1`（模拟关闭）：

```json
{
  "request_id": "event-1", "expected_event_revision": 0,
  "kind": "poi_closed", "active": true, "poi_id": "amap:B-demo",
  "effective_at": "2026-10-21T09:00:00+08:00",
  "source": "simulation", "evidence_ref": "simulation:closure", "verification_status": "verified"
}
```

响应同一组事实并增加 `event_id:"E1", revision:1`，可空的 `activity_id/earliest_start_at` 返回 null。`train_delay` 则必传 `activity_id, earliest_start_at`，不能携带景区关闭字段；关闭事件不能携带晚点字段。`source` 仅有 `simulation/reported`，`verification_status` 为 `verified/unverified`（默认 unverified）。模拟 verified 表示模拟场景内已确定，不是现实核实。解除异常用同一路径、完整事实、`active:false` 和最新 expected_event_revision。

`POST /api/trips/demo-trip/drafts`（覆盖该关闭事件）：

```json
{
  "request_id": "draft-1", "draft_id": "D1", "base_version": 1,
  "event_revision": 1, "history_revision": 0, "handled_event_ids": ["E1"],
  "plan": {
    "activities": [{"id": "visit-2", "poi_id": "local:alternative",
                    "start_at": "2026-10-21T10:00:00+08:00", "end_at": "2026-10-21T11:00:00+08:00",
                    "opening_status": "confirmed_open"}],
    "charges": [{"id": "ticket-1", "amount_cny": "50.00", "status": "paid"}],
    "refunds": [{"id": "refund-1", "amount_cny": "50.00", "status": "pending"}],
    "activity_evidence": {"visit-2": "simulation:alternative"},
    "financial_evidence": {"ticket-1": "simulation:paid"},
    "arrival_at_return_station": "2026-10-21T17:00:00+08:00"
  }
}
```

201 响应 `DraftView` 绑定 V1/异常修订1/历史修订0，`status:"pending", committed_version:null`。不改变正式版本或扣费。`validation.overall` 必须 PASS 才能提交。

`POST /api/trips/demo-trip/drafts/D1/confirm`：

```json
{"request_id":"confirm-1","base_version":1,"event_revision":1,"history_revision":0,
 "user_confirmed":true,"confirmed_by":"demo-user"}
```

只接受 JSON 布尔 true，不接受 1 或字符串。C 在用户明确确认后才允许触发；A 不能代替用户自动确认。成功返回 V2 `VersionView`，`source_draft_id:"D1"`、确认记录及预算 `conservative_total_cny:"50.00", pending_refunds_cny:"50.00"`（预算摘录）。重复确认返回同一正式版本，不产生新费用/新版本。

提交在 `BEGIN IMMEDIATE` 事务内重新核验版本、全部有效异常、历史锁定及完整草案。版本写入、当前指针、草案状态、其他草案失效、幂等回执要么全部提交，要么回滚。事件/锁定发生变化、其他草案先确认时，旧候选不能继续提交。活动历史只能追加锁定；已支付/已到账事实及证据不能由草案增删改，已知地点预约要求不能通过移除一次访问后重新加入来抹除，草案不能宣称新预约或改期已经完成。

`POST /api/trips/demo-trip/locks`（在 V2 下）：

```json
{"request_id":"lock-1","base_version":2,"history_revision":0,"activity_ids":["visit-2"]}
```

返回完整 TripView，`history_revision:1, locked_activity_ids:["visit-2"]`。不能解锁；同一键精确重试返回当时结果。

## 4. AgentArts 工具目录

| AgentArts 名称 | POST 路径 | 状态与副作用 |
| --- | --- | --- |
| `calculate_budget` | `/api/tools/calculate-budget` | 原确定性费用计算，无持久化 |
| `validate_plan` | `/api/tools/validate-plan` | 原硬约束核验，无持久化；增加返程时间与活动结束一致性检查 |
| `search_places` | `/api/tools/search-places` | 高德候选地点，只读 |
| `get_place_rules` | `/api/tools/get-place-rules` | 本地可追溯规则，只读 |
| `get_route_options` | `/api/tools/get-route-options` | 高德路线参考，只读 |
| `get_weather_risk` | `/api/tools/get-weather-risk` | 和风预报及本地阈值，只读 |

新增四个工具的 OpenAPI operationId 与上表下划线名称相同，A 可从 OpenAPI 导入；原两个工具的 operationId 保持原状，A 可显式映射名称。工具不创建旅行、执行预约、处理支付或自动确认。

### 4.1 原预算与校验

预算请求与完整响应示例：

```json
{"budget_cny":"200.00","charges":[{"id":"t1","amount_cny":"120.00","status":"paid"},
 {"id":"t2","amount_cny":"135.00","status":"planned"}],
 "refunds":[{"id":"r1","amount_cny":"120.00","status":"pending"}]}
```

```json
{"budget_cny":"200.00","paid_cny":"120.00","planned_cny":"135.00",
 "received_refunds_cny":"0.00","pending_refunds_cny":"120.00","conservative_total_cny":"255.00",
 "remaining_cny":"-55.00","within_budget":false}
```

校验请求：

```json
{"activities":[{"id":"a1","poi_id":"local:demo","start_at":"2026-10-21T10:00:00+08:00",
                 "end_at":"2026-10-21T11:00:00+08:00","opening_status":"unknown"}],
 "budget":{"budget_cny":"200.00"},"max_walking_minutes_per_leg":20}
```

响应 `overall:"UNKNOWN"`，`checks` 中 `opening_check` 为 UNKNOWN。完整检查名：`time_check/opening_check/booking_check/budget_check/walking_check/return_check/state_check`，传入到站时间时另有 `return_timeline_check`。可选输入包括 `return_deadline/arrival_at_return_station/locked_activities`。结果仅核验输入，工具本身不查外部来源。持久化接口还增加证据、财务事实、预约事实和异常检查；不能通过只调用无状态校验代替正式提交。

### 4.2 外部数据通用信封

除路线分模式返回外，结构统一为 `{status,code,message,evidence,data}`。`status` 只有 PASS/UNKNOWN，表示**取得本工具数据的完整性**，不是方案可行性。天气 `data.risk_check` 另表示阈值筛选结果，故取得高风险天气可以 `status:PASS, risk_check:FAIL`。

`evidence` 字段：

| 字段 | 语义 |
| --- | --- |
| `source` | `amap/qweather/local_rules` |
| `source_ref` | 不带密钥的接口地址或规则来源引用；无来源时 null，绝不输出本机规则文件路径 |
| `fetched_at` | 本次获取/尝试时间，非数据生成时间 |
| `source_updated_at` | 规则的来源采集时间；外部 API 未提供时 null，不用 fetched_at 冒充更新时间 |
| `data_type` | `real` 来源实际数据；`simulated` 注入的测试/模拟数据；`unknown` 没有可用数据 |
| `verification_status` | `source_reported` 外部服务报告（未独立核实）；`verified` 本地规则由维护方标记已核实；`unverified` 未核实或模拟 |
| `attributions` | 和风要求展示的归属信息；C 展示天气时一并保留 |

没有生产“自动 Mock”开关。测试使用 HTTP MockTransport 并显式标记 simulated；即使 Mock 结果 PASS，也不能作为现实开放、个人预约或付款凭证。UNKNOWN 的 `data` 为 null，不能补成空对象/免费/不需预约/零耗时/晴天。POI 空结果为 PASS+`[]`（本次搜索无匹配），不代表城市没有地点。路线某模式失败时保留其他模式结果，顶层仍为 UNKNOWN。

### 4.3 `search_places`

请求：`keywords/city` 为去空白非空字符串（至多200字），`limit` 为1–25，默认10；当前仅取首屏且限定城市，不做全量抓取。

```json
{"keywords":"公园","city":"武汉","limit":5}
```

模拟响应示例：

```json
{"status":"PASS","code":"ok","message":"候选地点仅供选择；开放、票价和预约需另查规则",
 "evidence":{"source":"amap","source_ref":"https://restapi.amap.com/v3/place/text",
             "fetched_at":"2026-10-21T02:00:00Z","source_updated_at":null,"data_type":"simulated",
             "verification_status":"unverified","attributions":[]},
 "data":[{"poi_id":"amap:B-demo","name":"模拟公园","address":null,
          "location":{"longitude":114.3,"latitude":30.5},"coordinate_system":"GCJ-02"}]}
```

地址/坐标缺失时返回 null，不推测位置。POI 不含个人预约状态、开放结论或真实票价。

### 4.4 `get_place_rules`

```json
{"poi_id":"amap:B-demo","visit_start_at":"2026-10-21T10:00:00+08:00",
 "visit_end_at":"2026-10-21T11:00:00+08:00"}
```

`TRAVELGUARD_RULES_PATH` 指向维护方提供的 UTF-8 JSON，根对象是 `{"records":[...]}`。本仓库不添加真实地点规则，不修改 C 的 `data/`。以下是**模拟结构样例**，使用时仍返回 UNKNOWN，不代表真规则：

```json
{"records":[{
 "poi_id":"amap:B-demo","opening_status":"confirmed_open","booking_required":true,
 "booking_note":"模拟：需提前预约，依据见source_ref","ticket_price_cny":"20.00",
 "valid_from":"2026-10-21T09:00:00+08:00","valid_until":"2026-10-21T17:00:00+08:00",
 "source_ref":"simulation:rule-source","retrieved_at":"2026-10-21T02:00:00Z",
 "data_type":"simulated","verification_status":"unverified"
}]}
```

对应响应：

```json
{"status":"UNKNOWN","code":"unverified_rules","message":"模拟或未经核实的规则不能作为真实开放/预约依据",
 "evidence":{"source":"local_rules","source_ref":"simulation:rule-source","fetched_at":"2026-10-21T02:00:00Z",
             "source_updated_at":"2026-10-21T02:00:00Z","data_type":"simulated",
             "verification_status":"unverified","attributions":[]},"data":null}
```

可用规则需要：唯一记录覆盖完整访问时段；采集不超过7日，不能晚于当前时间5分钟以上；真实且核实的来源；开放不为 unknown、预约要求不为 null、票价不为 null，需预约时必须有 booking_note。票价0只有明确依据时填写，不知道则 null。重叠规则不擅自选一条，返回冲突 UNKNOWN。

通过时 data 为该记录的 `poi_id/opening_status/booking_required/booking_note/ticket_price_cny/valid_from/valid_until`；来源放 evidence。关闭也可能取得完整规则，此时工具 status PASS、opening_status confirmed_closed，行程校验仍必须 FAIL。无论何时都不返回个人 `booking_status:confirmed`。规则的 verified 是维护方声明，B 不抓网页复核真实性；A、C 须核对权威来源及具体票种/预约条件，当前单票价不支持优惠票种矩阵。

### 4.5 `get_route_options`

```json
{"origin":{"longitude":114.3,"latitude":30.5},"destination":{"longitude":114.31,"latitude":30.51},
 "coordinate_system":"GCJ-02","modes":["walking"],"city":"武汉"}
```

工具接口默认 modes 仍为 walking/transit/driving，新增可选 bicycling；不能为空或重复，最多4种。公交必须有 `city`，跨城由调用方另传 `destination_city`。每模式最多3个候选，每路段最多4次上游查询。

```json
{"status":"PASS","results":[{"mode":"walking","status":"PASS","code":"ok",
 "message":"查询时刻的路线估算；不保证未来班次和耗时",
 "evidence":{"source":"amap","source_ref":"https://restapi.amap.com/v3/direction/walking",
             "fetched_at":"2026-10-21T02:00:00Z","source_updated_at":null,"data_type":"simulated",
             "verification_status":"unverified","attributions":[]},
 "data":[{"duration_seconds":900,"distance_meters":1000,"walking_seconds":900,"cost_cny":null}]}]}
```

公交 `walking_seconds` 仅在各段步行耗时齐备时求和，否则 null；驾车不假定步行段为0。公交费用可能有来源估算；驾车费用暂为 null（不擅自把过路费当作完整用车费用）。新增可选 `departure_at`（必须带时区），公交请求转换到中国时区后传入高德的 date/time，按旅行时段筛选；缺省仍按旧接口行为查询。驾车、步行和骑行不虚构未来路况或班次，也不承诺未来票价固定。

### 4.6 `get_weather_risk`

```json
{"location":{"longitude":114.3,"latitude":30.5},"coordinate_system":"WGS84",
 "on_date":"2026-10-21","timezone":"Asia/Shanghai","activity_type":"outdoor"}
```

成功模拟响应：

```json
{"status":"PASS","code":"ok","message":"已取得逐日预报；活动风险为本地阈值推导",
 "evidence":{"source":"qweather","source_ref":"https://example.qweatherapi.com/weather/v1/daily/30.500000/114.300000",
             "fetched_at":"2026-10-21T02:00:00Z","source_updated_at":null,"data_type":"simulated",
             "verification_status":"unverified","attributions":["https://developer.qweather.com/attribution.html"]},
 "data":{"on_date":"2026-10-21","forecast_start_at":"2026-10-21T00:00:00+08:00",
         "forecast_end_at":"2026-10-22T00:00:00+08:00","temperature_max_c":36,"temperature_min_c":20,
         "precipitation_mm":0,"max_wind_speed_mps":2,"conditions":["模拟晴","模拟晴"],
         "risk_check":"FAIL","risk_factors":["high_temperature"],"risk_policy":"outdoor-v1",
         "note":"逐日预报与本地阈值仅供活动筛选；未查询气象预警，不代表安全保证。"}}
```

`outdoor-v1` 是项目演示筛选阈值：最高温≥35°C、最低温≤0°C、昼夜累计降水≥10mm、昼夜最大平均风速≥10.8m/s、雷暴代码302/303/304或雪类4xx，命中任意项为 risk_check FAIL；其余完整输入为 PASS，仅表示未触发这些阈值。室内为 NOT_APPLICABLE，仍保留天气因素。风险是 B 的确定性推导，非和风发布的预警结论；尚未覆盖全部灾害、阵风、空气质量与逐小时活动适宜性。

当前按7日窗口取逐日数据，目标日期缺失、重复、字段/单位异常、未知天气或请求失败均 UNKNOWN，不沿用其他日期。天气代码按官方 v1 已知枚举核验，未来新增代码在适配前保持 UNKNOWN；昼间必须对应目标日07:00–19:00，夜间对应19:00–次日07:00（中国时区），总逐日区间须为24小时并覆盖昼间起点。外部 HTTP 每次请求5秒超时，无重试、重定向或本地旧缓存兜底；来源提供的 HTTP Age≥3600秒时拒绝。v1 未提供生成时间时 source_updated_at 为 null，不能宣称已核实来源生成时间或实际天气。客户端传入的日期窗口不是来源一定有数据的承诺。

## 5. 错误、幂等与冲突

| HTTP | 结构与处理 |
| --- | --- |
| 401 | `{"detail":"工具认证失败"}`，检查可信服务调用凭据 |
| 503 | `{"detail":"工具服务尚未配置认证密钥"}`，后端配置缺失；勿与外部服务 UNKNOWN 混淆 |
| 422 请求校验 | FastAPI `{"detail":[{"loc":...,"type":...,"msg":...,"input":...}]}`；新增持久化/外部请求拒绝额外字段，原两个工具保持兼容行为 |
| 422 业务核验 | `detail:{code:"verification_blocked",message,validation}`；初始创建和确认均阻止 FAIL/UNKNOWN |
| 422 目标非法 | `detail:{code:"invalid_event_target"或"invalid_lock",message}` |
| 404 | `detail:{code:"trip_not_found"或"draft_not_found"或"version_not_found",message}` |
| 409 | `detail:{code,message}`，见下表；重新读取状态，不覆盖远端状态 |
| 500 | 未分类服务/存储故障；不能当作提交成功。网络中断/服务故障后用同一 request_id 和完全相同请求重试，以幂等回执确认结果 |

409 code：`idempotency_conflict`（键已用于其他内容/操作）、`trip_exists/draft_exists`（资源ID占用）、`revision_conflict`（当前版本/修订变化）、`draft_token_conflict`（确认参数与草案不符）、`draft_stale`、`event_set_conflict`、`confirmation_conflict`（更改已保存的确认人）。多个条件冲突时服务先命中的 code 可能不同，不依赖特定检查顺序。

幂等作用域是同一旅行：相同操作路径、相同 request_id、相同经过模型规范化的请求重放**原始响应**，不会变成最新 TripView/DraftView；重试后通过 GET 读取当前状态。改内容或跨操作复用键是409。失败事务不占用键。不要对409盲目换键重复确认；已 committed 草案按相同绑定修订号及确认人返回原正式版本，即使使用不同 request_id 也不重复提交。

外部服务问题通常仍返回 HTTP200 的 UNKNOWN 信封（路线在 results 内各自给 code），使 A 能区分“未知事实”和“请求非法”。code 包括：

- `missing_credentials/invalid_configuration`：配置缺失或域名格式不安全。
- `provider_timeout/provider_unavailable/provider_error/invalid_provider_data/stale_data`：超时、不可用、来源拒绝、结构错误、已知缓存过期。
- `no_route/forecast_out_of_range/forecast_missing`：无路线、超出当前工具日期窗口、来源无目标日唯一预报。
- `missing_rules_source/rules_unavailable/invalid_rules_data/rules_not_found/rules_conflict/stale_rules/unverified_rules/incomplete_rules`：规则来源、完整性、有效期或核实不足。

## 6. A、C 联调待确认事项与能力边界

- P6 的 B 端基础信息、SQLite 升级和响应已补齐；C 的字段适配和真实 FastAPI 接入尚未完成，不能把本草案称为已确认冻结的前后端契约。`stay_together` 为已持久化偏好，是否及如何实现多人同行核验待 A、C 协商。
- C 现有模拟协议还有待适配差异：`formal_version` 对应 B 的 `current_version`，平铺活动对应 `current_plan.plan.activities`；`transport_delay/place_closure` 对应 `train_delay/poi_closed`，B 暂不支持 weather 异常；`awaiting_confirmation/superseded/confirmed` 对应 `pending/stale/committed`。C 的 `options[]` 与 B 的一草案一完整 `plan` 不能直接互传，接入方案及 AgentArts 规划/重规划入口待 A、C 确认，不由本阶段改动；确认时仍须通过 B 的 PASS 核验并携带三种版本/修订号。
- A 确认六个工具映射及超时预算（路线最多3次各5秒），按 status、data_type、verification_status 和风险字段分别分支。UNKNOWN 应请求补充依据/人工核实，不生成假事实。候选只用 `/drafts`，正式变更必须经过 C 的用户确认和 `/confirm`。
- C 确认同源开发代理的服务端鉴权、带时区时间、金额字符串、空值展示、三种草案状态及409后的刷新流程；不要把旧快照 PASS 当作当前异常已经处理。
- A、C 确认地点 ID 对照与坐标来源。C 的地点资料应提供高德 ID 与 WGS84 坐标或可核实映射，不以名称猜测地点。C 继续维护自己的数据文件，B 仅消费经双方约定的规则 JSON 来源。
- 规则来源的真实票种、开放时段、预约渠道、采集时间及核实标记需 C 提供并与 A 确认；没有依据保持 UNKNOWN。个人预约完成证据不能由“需要预约”规则推导。
- 外部调用实现与离线 Mock 测试已具备；尚无真实密钥调用证据、AgentArts 云端导入联调、React 代理配置、真实权威地点规则库或生产认证。本阶段不部署、不执行付款/预约/改签/退款，也没有记录资金状态变化的真实交易入口。

适配依据（核对日期 2026-10-21）：[高德POI](https://lbs.amap.com/api/webservice/guide/api-advanced/search)、[高德路径规划](https://lbs.amap.com/api/webservice/guide/api/direction)、[和风Daily Forecast v1](https://dev.qweather.com/en/docs/api/weather/weather-daily-forecast/)、[和风API配置及密钥头](https://dev.qweather.com/en/docs/configuration/api-config/)。接口实现有意限制范围，未承诺上述服务的全部能力。

## 规则推荐（集成分支）

新增两个只读 POST，均复用现有适配器且要求 `X-Tool-Key`：

- `/api/recommendations`：初始路线候选，不创建正式旅行。
- `/api/trips/{trip_id}/recommendations`：基于正式版本与所有 active 异常生成调整候选，校对城市、日期、预算、步行和返程约束，不允许借输入改写服务端硬约束。

请求示例（日期必须按真实旅行输入；天气范围之外仍返回 UNKNOWN）：

```json
{"origin_city":"上海","city":"杭州","arrival_station":"杭州站","return_station":"杭州站",
 "keywords":"公园","start_date":"2026-11-10","end_date":"2026-11-11","party_size":2,
 "budget_cny":"1000.00","max_walking_minutes_per_leg":20,"arrival_time":"09:00","return_time":"17:00",
 "stay_together":true,"other_costs_cny":"200.00"}
```

`other_costs_cny` 为地图/票价以外的整团费用估算，null 表示未知，不能自动当作0。市内游览从目的地抵达点及用户约定时间开始；不查询或虚构跨城车票与住宿订单。日期支持连续1至7日，均衡/室内候选每日默认两项90分钟游览，轻松候选每日一项；下午安排留出用餐间隔，游览18:00前结束；缺少足够地点时明确标注日期覆盖不足。

响应包括 `generator: rules-v1`、`agentarts_connected: false`、原始 `input`、真实搜索的 `places/searches`、抵达/返程点候选、`candidates` 及用于既有创建接口的 `trip_request` 公共字段。每个候选包含完整 `TravelPlan`、逐活动的地点/天气/规则、全部路段三种方式的结果、已知费用小计/费用完整性/预算余量、排序原因/取舍/待核实事项及核验结果。费用未知不置0，步行/交通总时长不完整时为 null。票价及交通费用按人数计算，其他费用输入按整团计算。

排序先比较必要核验状态，再比较共同评分：步行分钟×0.7 + 交通分钟×0.2 + 已知人民币费用×0.03 + 每处户外天气风险30分。候选生成与交通方式选择分别偏向均衡、减少游览负担及室内推断；先排除已知步行超限和未允许方式，再按真实路段估算搜索附近景点组合。仅在实际总步行严格更少时使用“少步行”标签，相同行程与交通合并，不能凑数。有限方案排序不构成全局最优证明；室内分类推断不能当作核实的安全保证。

推荐不修改数据库。前端仅在推荐必要核验 PASS 后调用既有创建/草案接口，再由 B 在正式确认事务内重新校验版本、异常、历史锁定、资金及预约事实。用户上报默认未核实，不能确认；不得由推荐模块虚构核实记录。旧费用只允许替换标记为 `rules-v1:aggregate-estimate` 的本引擎 planned 聚合估算，其余原流水/退款/证据保留；覆盖关系无法对账时 UNKNOWN 阻止确认。标记不表示实际支付。

地图使用高德 GCJ-02；和风支持控制台合法多级 `*.qweatherapi.com` 专属域名，也接受无路径/用户信息/端口的 HTTPS 根地址。主机格式和坐标处理参考 [和风 API Host](https://dev.qweather.com/docs/configuration/api-host/)、[每日预报](https://dev.qweather.com/docs/api/weather/weather-daily-forecast/)、[坐标约定](https://dev.qweather.com/docs/resource/glossary/)。7日预报范围不因供应商扩展而自动放宽。

### 攻略与交通偏好（本轮集成）

推荐输入新增 `allowed_modes`，默认 `["transit","walking"]`，可多选 `transit/walking/bicycling/driving`。空数组、重复方式不合法；不会自动补选用户未允许的交通。路线缓存按起终点与出发时段区分；公交使用旅行日期/估计出发时间，次日活动不无条件顺延。骑行调用高德官方 HTTPS `/v4/direction/bicycling`，成功判断数值 `errcode:0`，解析 `data.paths` 的秒/米；超时、空路线或错误继续 UNKNOWN。骑行不证明共享单车车源，缺失租金不置0；驾车不提供出租车报价、停车费或取车接驳保证。

响应 `format_version:2`。候选增加 `feasibility:feasible/unverified/infeasible`、`warnings`、`paid_cny/estimated_cny/missing_costs` 和 `available_balance_cny`（费用未齐时 null）。`known_cost_cny/remaining_cny` 保留兼容，不能把不完整费用下的 remaining 当成可用余额。没有完整路段或存在硬冲突时 `recommended:false`；不可行候选可供调整，不得展示为最佳可行路线。相同候选合并时 `distinct_shortfall` 明确数量不足。正式确认仍要求推荐必要核验及 B 端核验 PASS，schema v2 和事务机制未改变。

### 周边住宿与美食

`POST /api/guide/nearby` 同样要求 `X-Tool-Key`，仅只读查询。请求为 `city/on_date/visits`（1至6个带GCJ-02坐标的地点）、`hotel_keyword`（默认酒店）、`food_keyword`（默认地方小吃）、允许方式及步行限制；可提供 `next_day_first/next_day_date` 来查询次日酒店出发参考。

复用 `/api/tools/search-places` 的新增可选字段：`location`、`radius_meters`（100至10000米）和 `types`。有 location 时使用高德 `/v3/place/around`，无 location 保持原关键词搜索。酒店半径3公里、餐饮1.5公里；结果是有限候选，不声称完整覆盖或距离最优。返回按当天景点分布推导的住宿区域、酒店候选、首个候选的往返路线，以及午餐/晚餐附近地点和可取得的路段。价格、评分、营业状态及房态未取得时保持 null/unknown。用餐时段是建议，未自动写成正式活动。

用户选择酒店后，推荐请求同时提供 `lodging_poi_id/lodging_name`；服务重新搜索核对ID并加入住宿活动，重算晚间返回与次日出发，不沿用景点间旧耗时。房态和入住条件未确认，不能因此伪造预约或开放 PASS。当前一处选定住宿作为多日往返点；不支持分夜订单、预订或付款。

普通页面保留必要来源及和风署名，完整坐标、路段结果、评分和核验置于“查看详细依据”。旧攻略缓存只复用输入并提示手动重新查询，正式版本从 B 恢复，不能用缺失金额补零。

小红书、美团、智行仅提供经核实的 HTTPS 官网主页及可复制搜索词，不拼接未经核实的搜索 URL。没有业务合作授权，不调用内部接口，不声称实时价格/优惠/余票/房态接入。美团主页可能引导至 App，小红书可能要求登录。
