# TravelGuard 后端（成员 B）

Python 3.11、FastAPI、标准库 SQLite。提供预算与约束工具，以及初始正式行程、连续异常、重规划草案、用户确认和正式版本持久化的单机闭环。本文及 `/docs`、`/openapi.json` 是 B 端当前接口说明，供 A、C 后续联调。

后端接收结构化方案并做确定性核验；AgentArts 推理和 React 交互分别由 A、C 实现。已提供高德地图、和风天气及本地地点规则适配器，真实地图/天气尚未使用密钥联调；没有付款、退款、预约、改签或华为云连接。

跨模块接口契约草案见 [docs/api_contract.md](../docs/api_contract.md)，待 A、C 共同确认后稳定。新增工具为 `search_places`、`get_place_rules`、`get_route_options`、`get_weather_risk`，HTTP 路径采用 `/api/tools/` 下对应连字符名称，且均需 `X-Tool-Key`。原预算、校验和旅行状态字段保持兼容，校验工具补充了返程到站时间不能早于活动结束的检查。

配置示例见 `.env.example`；这些变量必须传入后端进程，本服务不自动加载 `.env`。外部 Key 不得传入 React，开发联调由 C 的本机服务代理在服务端注入工具密钥，不能使用 `VITE_` 变量打包密钥。未配置密钥或本地规则、服务超时/失败、缺字段、规则过期、超出预报日期范围均返回结构化 UNKNOWN；生产代码没有自动模拟数据模式。测试通过注入 MockTransport 标记 `simulated`，不会连接真实付费服务。

规则知识库由 `TRAVELGUARD_RULES_PATH` 指向维护方提供的 JSON；未配置不会读取或改动 C 的 `data/`。规则覆盖完整访问时段、采集时间不超过 7 日且带真实来源和核实标记时才输出可用事实，预约规则永远不代表个人预约成功。路线只返回查询时刻参考；缺少步行时间、费用保持 `null`。天气只查询中国时区今天起 7 日内的逐日预报，使用和风 Daily Forecast v1；风险为本地阈值筛选，未接入气象预警。详情及局限见契约。

## 本地运行

在仓库根目录使用 PowerShell 7，优先复用已有 `backend/.venv`。仅首次缺少环境或依赖时执行前两条：

~~~powershell
py -3.11 -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Set-Location backend
$env:TRAVELGUARD_TOOL_API_KEY = '自行设置本地临时密钥'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
~~~

打开 http://127.0.0.1:8000/docs 查看接口文档。

默认数据库为 `backend/travelguard.local.sqlite3`，不会在模块导入时创建，服务启动时初始化表。可在启动进程前设置 `TRAVELGUARD_DB_PATH` 指向本项目 `backend/` 内的测试数据库文件；重启使用同一路径会读回既有状态。父目录须已存在，不支持 `:memory:`（每次请求使用独立连接）。SQLite 无额外依赖。数据库及本地恢复日志不得提交，后端忽略规则保留这些文件在磁盘上。

数据库 schema 版本为 2：启动时在同一写事务中将已知旧版本 0/1 升级，向旅行表增加可空的基础信息和偏好列，不重置或重写原有业务数据。旧数据的新字段保持未知；迁移失败整体回滚，遇到未知版本会停止启动。SQLite 默认回滚日志和 `foreign_keys=ON`，写操作使用 `BEGIN IMMEDIATE`。实际升级前应停止旧服务并备份数据库；旧二进制不支持 schema 2，不能直接用旧代码打开升级后的库。这是单机方案，尚无多租户隔离、生产认证和迁移运维工具。

本地测试（在backend目录）：

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_cache/state-tests
~~~

测试数据库和测试缓存全部位于 `backend/.pytest_cache/`；pytest 会管理其专用临时目录，请勿把用户数据放入该目录。测试不使用默认业务库，不连接外部服务。

仅运行真实 HTTP 验收（会启动并关闭两个本机 Uvicorn 进程）：

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_travel_state.py::test_real_http_workflow_and_service_restart --basetemp=.pytest_cache/state-tests
~~~

该用例内置武汉两日游模拟数据，实际发起 HTTP 请求完成 `V1 → E1列车晚点 → D1 → E2黄鹤楼关闭 → D1失效 → D2处理E1+E2 → 用户确认V2 → 服务重启读回`，同时检查历史锁定、待到账退款不抵扣、重复确认不产生版本或费用重复。其余测试覆盖并发版本冲突、异常更新/解除、幂等键冲突、证据不足、硬约束和实际 SQLite 故障回滚。

## 认证与已有工具

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | /health | 健康检查 |
| POST | /api/tools/calculate-budget | 预算与付款退款计算 |
| POST | /api/tools/validate-plan | 时间、景点开放、预约、预算、步行、返程和历史活动锁定校验 |

工具及以下所有旅行接口都要求请求头 `X-Tool-Key`，其值与服务端进程环境变量 `TRAVELGUARD_TOOL_API_KEY` 一致；未设置返回 503，错误/缺失返回 401。`/health` 无需认证。本地测试密钥不得公开部署。该共享工具密钥和 `confirmed_by` 字段不构成生产用户身份认证，调用方必须在真实用户确认后才能调用提交接口。

费用单位为人民币元，以十进制计算并作为JSON字符串输出。费用流水ID唯一；未到账退款不抵扣预算。

验证结果：PASS（通过）、FAIL（违反）、UNKNOWN（证据不足）、NOT_APPLICABLE（不适用）。对外部开放状态、真实票价和预约不做联网核实，**仅验证输入提供的事实与条件**；UNKNOWN不可当作PASS。

原有两个工具的字段、状态和响应语义保持不变。新增持久化接口采用严格字段校验，不能在草案中传入预算上限、硬约束或历史锁定来覆盖服务端规则。

## 旅行状态与正式版本 API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/api/trips` | 核验初始方案，创建旅行和正式 V1（201） |
| GET | `/api/trips/{trip_id}` | 读取正式版本、约束、锁定活动、全部当前异常（含已解除异常） |
| GET | `/api/trips/{trip_id}/versions` | 按版本号读取全部正式快照与确认记录 |
| PUT | `/api/trips/{trip_id}/events/{event_id}` | 新增/更新异常；`active:false` 解除异常 |
| POST | `/api/trips/{trip_id}/drafts` | 保存候选草案及核验结果（201），不修改正式版本 |
| GET | `/api/trips/{trip_id}/drafts` | 读取全部草案 |
| GET | `/api/trips/{trip_id}/drafts/{draft_id}` | 读取单个草案的当前状态 |
| POST | `/api/trips/{trip_id}/drafts/{draft_id}/confirm` | 用户明确确认后原子提交正式版本 |
| POST | `/api/trips/{trip_id}/locks` | 追加不可修改的历史活动，不能解锁 |

所有写请求携带 `request_id`。同一旅行内，相同键、相同规范化请求及操作路径返回原始结果；更改请求内容或跨操作复用同一键返回 409。失败事务不占用键，修正后可重试。创建旅行/草案使用调用方提供的唯一 `trip_id` / `draft_id`；已有资源换键重复创建返回 409。ID 长度为 1–128，不能包含空白、`/` 或 `\`；新接口中的活动、POI、费用和路径 ID 使用相同规则。

### 初始旅行与方案

创建请求及旅行响应新增可选的 `city`、`party_size`（JSON 整数 1～10）、`start_date/end_date`（严格 `YYYY-MM-DD`，结束不早于开始），缺省/null 均保持未知以兼容旧请求。同行偏好放在独立的 `preferences.stay_together`（布尔或 null），保存偏好但尚无多人同行核验；整体 PASS 不代表已验证全程同行。日期、人数不改变费用或既有硬约束语义；完整字段映射和迁移边界见接口契约 3.1。

`POST /api/trips` 示例（完整武汉两日游数据见验收测试）：

~~~json
{
  "request_id": "create-1",
  "trip_id": "wuhan",
  "title": "武汉行程",
  "city": "武汉",
  "party_size": 3,
  "start_date": "2026-11-18",
  "end_date": "2026-11-19",
  "preferences": {"stay_together": true},
  "budget_cny": "300.00",
  "max_walking_minutes_per_leg": 20,
  "return_deadline": "2026-11-19T17:00:00+08:00",
  "locked_activity_ids": [],
  "plan": {
    "activities": [{
      "id": "train", "poi_id": "wuhan-station",
      "start_at": "2026-11-18T09:00:00+08:00",
      "end_at": "2026-11-18T10:00:00+08:00",
      "opening_status": "confirmed_open"
    }],
    "charges": [{"id": "train-ticket", "amount_cny": "100.00", "status": "paid"}],
    "refunds": [],
    "activity_evidence": {"train": "simulation:station-open"},
    "financial_evidence": {"train-ticket": "simulation:paid-ticket"},
    "arrival_at_return_station": "2026-11-19T16:00:00+08:00"
  }
}
~~~

仅核验结果为 PASS 时创建 V1。预算上限、步行限制和返程截止时间属于旅行的服务端硬约束，草案不能更改。活动沿用工具接口字段，所有时间须带时区；多活动之间须提供交通耗时，设置步行限制后也须提供步行耗时。

`plan` 是完整方案快照，包含 `activities`、`charges`、`refunds`、到站时间和证据引用。每个已声明核实开放/完成预约的活动须有 `activity_evidence[活动ID]`；已支付/已到账费用须有 `financial_evidence[流水ID]`。初始事实由有权调用方明确提供，后端保存其来源引用，**不会联网确认引用的真实性**。模拟引用（例如 `simulation:...`）只能说明本地案例；PASS 表示输入事实下的确定性核验通过，不表示外部业务操作已完成。

每个版本的费用是完整快照，不是增量账单；不要累加各版本费用。草案只能调整计划费用和待到账退款，必须保留已支付/已到账事实及其证据，不能新增或改写实际付款、到账退款。未到账退款不抵扣预算。同一快照内费用 ID 不得重复。费用始终以十进制人民币元计算，响应使用 JSON 字符串。

### 异常及修订号

E1：`PUT /api/trips/wuhan/events/E1`

~~~json
{
  "request_id": "event-E1", "expected_event_revision": 0,
  "kind": "train_delay", "activity_id": "train",
  "earliest_start_at": "2026-11-18T11:00:00+08:00",
  "source": "simulation", "evidence_ref": "simulation:E1",
  "verification_status": "verified"
}
~~~

E2：`PUT /api/trips/wuhan/events/E2`

~~~json
{
  "request_id": "event-E2", "expected_event_revision": 1,
  "kind": "poi_closed", "poi_id": "yellow-crane-tower",
  "effective_at": "2026-11-18T13:00:00+08:00",
  "source": "simulation", "evidence_ref": "simulation:E2",
  "verification_status": "verified"
}
~~~

支持 `source=simulation|reported`；`verification_status` 默认 `unverified`，有效且未核实的异常使核验至少为 UNKNOWN，无法提交。`verified` 是调用方提供的核验事实，后端不代为联网核实。当前列车模型要求保留目标活动 ID 和 POI，并满足最早开始时间；尚不支持自动推断替代车次及真实改签。景区关闭从 `effective_at` 生效，生效前已完成的活动不受影响。

新增、更新或解除异常会递增旅行 `event_revision` 并将全部未提交草案标为 `stale`；相同事实在当前修订号下重复写入不递增。旧修订请求返回 409（原请求精确重试则重放幂等结果）。所有变化只修改异常事实，不改写既有正式快照。

### 草案、历史事实及确认

草案请求包含 `request_id`、`draft_id`、`base_version`、`event_revision`、`history_revision`、`handled_event_ids` 和完整 `plan`。修订号必须来自最新旅行状态，事件列表必须恰好包含全部有效异常。后端会逐一核验事件是否实际得到处理，不能仅凭声明已处理就通过。允许保存 FAIL/UNKNOWN 草案用于比较，但不能确认提交。

`POST /api/trips/wuhan/locks` 示例：

~~~json
{"request_id":"lock-1","base_version":1,"history_revision":0,"activity_ids":["train"]}
~~~

该接口只追加当前正式活动的历史锁定，递增 `history_revision` 并使旧草案过期。锁定后的活动完整内容及证据不可删除或改写；新草案必须带最新历史修订号。重复追加已有锁定不改变修订号。

确认 D2（假设 V1、E1+E2、无新增历史锁定）：

~~~json
{
  "request_id":"confirm-D2", "base_version":1,
  "event_revision":2, "history_revision":0,
  "user_confirmed":true, "confirmed_by":"local-user"
}
~~~

`user_confirmed` 只接受 JSON 布尔值 `true`。确认事务锁定写入后再次检查草案状态、三个修订号、有效事件集合、全部硬约束、支付事实及锁定历史，重新计算核验结果。只有 PASS 才同时写入正式 V2、当前版本指针、用户确认记录、草案提交状态和幂等回执；其他待提交草案同时过期。任何失败均回滚，不能留下半个版本或占用确认请求键。

同一草案重复确认，即使使用新的 `request_id`，也只返回第一次提交的版本；需保留该草案原始修订参数和同一 `confirmed_by`，不会重复计费或生成 V3。不同草案竞争同一基线时只有一个成功，其余返回 409。幂等重放返回历史操作结果，读取最新状态应使用 GET 接口。

草案不能宣称新预约或改期已完成；已确认预约只能沿用正式基线中相同活动、POI、时间和证据。已知地点的预约要求不能通过换活动 ID、删除后重新加入或清除 `booking_required` 来降低。放弃未来访问不等于取消预约，仍保留历史正式快照和已支付费用。实际支付/退款到账/新预约核验事实更新接口尚未实现；需要这些操作的方案必须等待后续接入，不能在草案中伪造完成状态。

响应中的 `current_plan` / 正式版本含 `plan`、预算结果、核验结果、版本绑定、来源草案、创建时间及 `confirmation`。初始 V1 的 `confirmation=null`，表示显式创建初始行程；后续确认含 `request_id`、`confirmed_by`、`confirmed_at`。草案状态为 `pending|stale|committed`。

常见状态：401/503 认证问题；404 资源不存在；409 幂等键/资源 ID/版本/修订冲突；422 输入错误或核验阻止提交（后者含 `detail.code=verification_blocked` 与完整 `validation`）；存储异常返回 500 并回滚。对外开放前仍需正式用户认证、HTTPS、资源隔离和外部事实核验。
