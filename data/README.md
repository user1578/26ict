# TravelGuard 武汉模拟数据（C 侧维护，`data/`）

> **重要声明：本目录下所有数据均为人工构造的模拟数据（`data_type: "simulated"`），
> 均未核实（`verification_status: "unverified"`），仅用于本地 Demo 演示与前后端契约联调。
> 它们不代表真实的景点开放状态、预约要求、票价或付款事实，不能作为出行依据。**

## 1. 数据用途

- 为 TravelGuard Demo 提供武汉地点目录、访问规则与证据引用，供前端规划器/展示层和后端
  `get_place_rules` 读取（后端通过环境变量 `TRAVELGUARD_RULES_PATH` 指向 `wuhan_rules.json`）。
- 与 B 的 FastAPI 契约（`docs/api_contract.md`，基准 `origin/hsh/backend@cf18e72`）对齐：
  规则文件根对象为 `{"records":[...]}`，字段见 §4.4。
- 前端规划器使用 7 个固定证据 ref 填充行程的 `activity_evidence` / `financial_evidence`，
  以及地点 `poi_id`。

**刻意保持的诚实状态**：由于规则是 `simulated + unverified`，B 的 `get_place_rules`
会返回 `status=UNKNOWN, code=unverified_rules`；这是设计上正确的行为，**不要**为了
让 Demo “看起来通过”而把 `data_type` 改成 `real`、把 `verification_status` 改成 `verified`。

## 2. 文件清单与字段含义

### 2.1 `wuhan_pois.json` —— 地点目录（5 条）

根对象：`format_version`、`city`、`note`、`records`。每条记录字段：

| 字段 | 含义 |
| --- | --- |
| `poi_id` | 本地地点 ID，固定为 `local:wh-*`；前端规划器用它引用地点、关联规则 |
| `name` | 地点中文名 |
| `amap_id` | 高德 POI ID。**当前全部为 `null`**——未调用高德接口，不得编造真实 ID |
| `amap_mapping_status` | 高德映射状态，当前全部 `unverified`（待补真实映射后用真实接口核对） |
| `address` | 模拟的合理中文地址，未与地图服务核对 |
| `coordinates.gcj02` | 模拟 GCJ-02 坐标（高德/腾讯体系） |
| `coordinates.wgs84` | 模拟 WGS84 坐标（GPS/和风天气体系），按经验偏移量近似换算 |
| `coordinate_note` | 坐标说明：模拟近似值，未调用地图接口核验 |
| `category` | 类别：`museum` / `park` / `landmark` / `food_street` |
| `indoor` | 是否室内（影响天气风险判断的输入） |
| `data_type` | 固定 `simulated`（模拟数据） |
| `verification_status` | 固定 `unverified`（未核实） |
| `source_ref` | 来源标记，固定 `hand-authored-simulation`（人工构造） |
| `retrieved_at` | 数据整理时间（UTC，ISO 8601） |

5 个 POI（`poi_id` 不可更改，前端/规则/证据均依赖）：

1. `local:wh-hubei-museum` 湖北省博物馆（museum, indoor）
2. `local:wh-east-lake-greenway` 东湖绿道（park, 室外）
3. `local:wh-yellow-crane-tower` 黄鹤楼（landmark, 室外）
4. `local:wh-hubuxiang` 户部巷（food_street, 室外）
5. `local:wh-xinhai-revolution-museum` 辛亥革命博物院（museum, indoor）

### 2.2 `wuhan_rules.json` —— 访问规则（5 条，契约 §4.4）

根对象**只有** `{"records":[...]}`（B 的 pydantic `RuleBook` 为 `extra="forbid"`，
多写根级字段会导致整份文件被判 `invalid_rules_data`）。每条记录字段：

| 字段 | 含义 |
| --- | --- |
| `poi_id` | 对应 `wuhan_pois.json` 中的地点 ID，5 条一一对应 |
| `opening_status` | 模拟开放状态，全部 `confirmed_open`（模拟声明，未核实） |
| `booking_required` | 是否需要预约：仅湖北省博物馆为 `true`，其余 `false` |
| `booking_note` | 预约说明；不需要预约的为 `null` |
| `ticket_price_cny` | 票价（字符串、两位小数）：黄鹤楼 `"70.00"`，其余 `"0.00"` |
| `valid_from` / `valid_until` | 规则覆盖有效期：`2026-11-01T00:00:00+08:00` ～ `2026-12-31T23:59:59+08:00` |
| `source_ref` | 来源标记，固定 `hand-authored-simulation` |
| `retrieved_at` | 数据整理时间（UTC） |
| `data_type` | 固定 `simulated` |
| `verification_status` | 固定 `unverified` |

说明：B 的规则可用性要求「真实且可核实来源」；本文件刻意保持 `unverified`，因此后端
会返回 UNKNOWN 而不是把模拟值当作真实事实。票价与预约信息仅用于演示规划器的数据流，
不代表现实价格或预约政策。

### 2.3 `evidence_registry.json` —— 证据登记（7 个 ref）

根对象：`format_version`、`note`、`records`（`ref -> 证据对象`）。每条证据字段：

| 字段 | 含义 |
| --- | --- |
| `kind` | 证据类型：`opening`（开放/活动证据）、`booking`（预约证据）、`financial`（付款证据） |
| `poi_id` | 关联地点；`financial` 付款记录可为 `null` |
| `summary` | 中文摘要，明确写“模拟” |
| `data_type` | 固定 `simulated` |
| `verification_status` | 固定 `unverified` |
| `source_ref` | 固定 `hand-authored-simulation` |
| `retrieved_at` | 整理时间（UTC） |

7 个固定 ref：

| ref | kind | poi_id |
| --- | --- | --- |
| `simulation:opening:hubei-museum` | opening | `local:wh-hubei-museum` |
| `simulation:opening:east-lake-greenway` | opening | `local:wh-east-lake-greenway` |
| `simulation:opening:yellow-crane-tower` | opening | `local:wh-yellow-crane-tower` |
| `simulation:opening:hubuxiang` | opening | `local:wh-hubuxiang` |
| `simulation:opening:xinhai-revolution-museum` | opening | `local:wh-xinhai-revolution-museum` |
| `simulation:booking:hubei-museum` | booking | `local:wh-hubei-museum` |
| `simulation:financial:paid-yellow-crane-ticket` | financial | `null` |

## 3. 前端如何引用

- **活动证据**：行程中每个活动的 `activity_evidence[activity_id]` 填对应地点的
  `simulation:opening:<slug>`（前 5 个 opening ref，与 5 个 POI 一一对应）。
- **预约证据**：湖北省博物馆相关活动/预约链路的 `activity_evidence` 上填
  `simulation:booking:hubei-museum`。
- **付款证据**：已支付黄鹤楼门票的费用项 `financial_evidence[charge_id]` 填
  `simulation:financial:paid-yellow-crane-ticket`。
- **地点与票价**：规划器用 `poi_id`（`local:wh-*`）把地点、规则、证据串起来；票价读取
  `wuhan_rules.json` 中同一 `poi_id` 的 `ticket_price_cny`（黄鹤楼 `"70.00"`），不要在前端
  硬编码。若规划器需要展示“模拟/未核实”，直接读各记录的 `data_type` / `verification_status`。
- 引用 ref 必须在上表 7 个之中；证据是“模拟声明”，不构成真实开放/预约/付款凭证。

## 4. 校验方式（交叉引用）

在仓库外（如 `D:\project\audit\`）用临时 Python 脚本检查：

1. 三份 JSON 均可 `json.load`；文件为 **UTF-8 无 BOM**；
2. `rules` 的 `poi_id` 集合 == `pois` 的 `poi_id` 集合（5 个）；
3. `evidence` 包含全部 7 个必需 ref；
4. `evidence` 中 `poi_id` 非 `null` 时必须存在于 `pois`；
5. `rules` 的 `ticket_price_cny` 全部为两位小数字符串（正则 `^\d+\.\d{2}$`）。

## 5. 维护注意事项

1. **不要伪造核实状态**：`data_type` 只能是 `simulated`，`verification_status` 只能是
   `unverified`；在真正完成权威来源核对之前，禁止改成 `real` / `verified`。
2. **不要编造真实高德 ID**：`amap_id` 保持 `null`，`amap_mapping_status` 保持 `unverified`；
   将来通过真实高德接口映射后，再补 ID 并把状态改为真实映射结果。
3. **`poi_id` 与 7 个证据 ref 是前端契约的一部分**，重命名会破坏前端规划器引用。
4. **规则文件根结构不可加字段**（B 侧 `extra="forbid"`），时间必须带时区，票价必须为
   两位小数字符串。
5. 修改数据后更新 `retrieved_at`，并重跑第 4 节交叉校验。
6. `ticket_price_cny` 的 `"0.00"` 仅是模拟占位，不代表现实免费；B 因 `unverified` 不会将其
   当作可用事实输出。
