# TravelGuard 批量重规划实验框架（本地模拟）

本工具用于可重复的离线适配与指标记录。**当前案例是人工构造的 simulation，不是实测 AgentArts / LLM 规划结果，也不证明真实旅游规则、预约或付款已核实。** 不新增公开 API，不访问业务数据库，不更改 schema v2、历史锁定或 PASS 确认要求。

## 1. 运行方法

在仓库 `backend` 目录使用已有 Python 3.11 虚拟环境，无新增依赖：

```powershell
# 全部场景：新建目录，导出 JSON、CSV、Markdown
.\.venv\Scripts\python.exe -m app.replan_experiments tests/fixtures/replan_experiments_simulation.json --output-dir .experiment_results/phase6-simulation

# 筛选案例；省略 --output-dir 时把完整 JSON 写到标准输出
.\.venv\Scripts\python.exe -m app.replan_experiments tests/fixtures/replan_experiments_simulation.json --case normal --case return_semantics

# 可选：实测逐候选本地适配、核验和指标计算耗时
.\.venv\Scripts\python.exe -m app.replan_experiments tests/fixtures/replan_experiments_simulation.json --measure --output-dir .experiment_results/phase6-timed

# 全量回归
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_cache/state-tests
```

导出目录必须尚不存在，防止覆盖用户已有实验记录。重复实验使用另一个新目录；不会自动清理原结果。输出为 UTF-8：`results.json`、`results.csv`、`summary.md`。本地 `.experiment_results/` 已忽略，生成结果保留在磁盘上，不混入源码提交。默认场景预计输出不足 1 MB。

退出码：0 表示批次正常运行，**不表示候选均可行**；故意触发 rejected/needs_information 的场景也可正常结束。1 表示某案例读入、差异操作或适配执行异常，独立案例继续执行且结果仍导出；2 表示清单/选项错误或导出失败。部分文件写入失败时保留现场，改用新目录重试，不自动删除结果。

## 2. 场景清单

入口 `app.replan_experiments.run_experiment(manifest, case_ids=None, measure=False)` 逐案调用既有 `adapt_replan` **一次**。适配器内部继续调用既有 `evaluate_replan/validate_snapshot`。批量层只汇总实际返回值，不实现另一套活动变化、预算或硬约束算法，也不创建/确认草案。

清单见 [replan_experiments_simulation.json](../backend/tests/fixtures/replan_experiments_simulation.json)，复用第五阶段 [wf_replan_simulation.json](../backend/tests/fixtures/wf_replan_simulation.json)，避免复制多份完整旅行快照。

```json
{
  "format_version": 1,
  "experiment_id": "example-simulation",
  "description": "人工离线模拟，未调用AgentArts",
  "cases": [{
    "case_id": "missing-date",
    "category": "missing_information",
    "data_type": "simulation",
    "origin": "hand_authored_fixture",
    "input_file": "wf_replan_simulation.json",
    "patches": [{
      "op": "replace",
      "path": "/workflow_output/options/0/proposed_schedule/0/start_time",
      "value": "11:00"
    }]
  }]
}
```

`case_id` 唯一，使用字母/数字开头及字母、数字、点、下划线、连字符，最长 128；category 是分类文本。`input_file` 是清单目录内相对 JSON 路径，拒绝绝对路径、目录逃逸、符号链接逃逸和非 JSON 文件。严格 JSON 不接受 NaN/Infinity、指数溢出的非有限数值或无法导出为 UTF-8 的孤立代理字符；坏输入按案例记录错误，不污染后续导出。筛选按清单原顺序执行，未知或空选择报错，不静默丢弃。

`patches` 只支持明确的 JSON Pointer `add/replace/remove` 子集：数组下标从 0 开始，add 的 `-` 表示追加；`~0/~1` 表示键内的 `~/`。replace/remove 目标必须存在，add/replace 必须显式提供 value（可以为 null），不自动创建中间节点。不支持根替换或更改 `/data_type`，无效操作按该案例执行错误记录；不会修改原 fixture 文件。

## 3. 最小案例集

| 案例 | 构造目的及解释 |
| --- | --- |
| normal | 完整费用、时段、交通和 simulation 证据支持的单异常调整 |
| continuous_old | E1 后再发生 E2，原候选仍访问已关闭地点，保留实际 FAIL |
| continuous_repaired | 同时处理 E1/E2，明确删除 A3，新增稳定 ID A5，并提供独立地点、交通和证据资料 |
| no_safe_candidate | A options 为空，不制造兜底行程或虚构候选 UNKNOWN |
| locked_conflict | 调整历史锁定 A1，记录锁定违规及拒绝原因 |
| budget_insufficient | 完整计划费用增加导致超预算；待到账退款仍不抵扣 |
| evidence_missing | 缺少改期活动对应证据，保留 UNKNOWN |
| old_version | A 绑定错误正式版本，记录 revision_conflict，不伪造候选核验结果 |
| missing_date | 只有时分，不从旅行日期推断活动日期 |
| return_semantics | A 的返程完成截止语义仍未与 B 对齐，保留 needs_information，即使 B 已有检查 PASS |
| candidate_id_conflict | 对原有 ID A3 声称 new_candidate，保留 invalid_action/rejected，不擅自重新编号 |

连续异常场景使用明确冻结的模拟输入，**批量入口不运行 SQLite 状态机**；真实草案失效/确认回归仍由已有专用临时库测试覆盖。默认场景没有实测 LLM 或人工“全量重规划”对照组，不提供算法优劣结论。未来若加入人工完整重排对照，应明确 origin=`manual_full_replan_control` 并继续标记 simulation，不得称为真实 LLM 输出。

## 4. 来源分离

每案保留清单声明 `declared_data_type`、原文件 `input_data_type`、实际分组 `data_type` 和 origin。只有**清单和原文件都明确为 simulation**，且 origin 为 hand_authored_fixture / manual_full_replan_control 时才执行。

- `simulation`：本地人工构造实验；只是来源标签，不是外部真实性核验。
- `agentarts_real`：为未来真实运行保留的分类；**当前一律 excluded，不导入适配器，不产生实验指标**。声明该标签不证明平台真的调用过。
- `unknown`：缺少/不认识的标签、来源不明，或模拟声明与原始输入冲突；排除执行，绝不改标签后混入模拟统计。

`source_groups` 分别保留三个分组的案例、执行和指标统计；根 summary 的实际候选统计仅来自已执行的 simulation。排除案例只记录来源、引用、哈希和排除原因，不复制其内容到 resolved_input。坏 JSON、无效差异或程序异常属于 execution error，与业务 rejected/needs_information 分开记录。

## 5. 输出与复现证据

`results.json` 是完整记录：

- 清单路径/原始字节 SHA-256、experiment_id、描述、实际 Python/Pydantic 版本和相关源码文件 SHA-256。
- 每案 case_id、分类、原输入文件引用和原始字节 SHA-256、显式差异列表、解析后完整模拟输入及规范化内容 SHA-256。
- 既有适配器的完整结果，包括原模型分析、各 option 的候选、可提交请求或失败原因、完整评估细项；不另填“预期成功”结果。
- 该批次和每案的 PowerShell 复现命令、backend 工作目录。命令默认输出 JSON；需要三份文件时追加新的 --output-dir。复现须同时保留清单和其引用的 fixture，并核对源码/输入哈希。

CSV 每个实际 option 一行；没有候选或没有执行的案例保留一行案例记录，option 和候选指标留空。JSON null 在 CSV 中留空，0 只表示实际可计算的零。复杂违规、失败原因和不可计算原因用单元格内 JSON 表示。CSV 正确引用逗号、引号和换行；潜在公式前缀的非数值标签加 `'`，原文本仍保存在 JSON，负金额不改变。

Markdown 展示总量、可计算性、逐案执行/适配/候选状态及原因代码。审阅报告时须同时看适配状态与 B 核验状态，不能把 B PASS 数量当作可确认草案数；例如 return_semantics 的 B PASS 与内部 needs_information 会同时保留。

默认无时钟读数和生成时间戳，同一输入、源码、Python/Pydantic 版本和工作路径下，JSON/CSV/Markdown 字节一致。换输出目录不改变文件内容；路径、依赖或源码改变会被记录，所以不承诺跨机器逐字节相同。`--measure` 记录真实本地逐候选耗时，会自然变化；默认耗时为 null，不能填写 0，更不能称为 AgentArts 推理耗时。

## 6. 聚合口径

单候选定义沿用 [第五阶段说明](wf_replan_adapter_notes.md)：稳定活动 ID 与完整属性比较；新增另计、不进入原活动保留率分母；金额用 Decimal，按两个完整快照比较，pending 退款不抵扣。批量层只聚合这些实际值。

| 汇总字段 | 口径 |
| --- | --- |
| case_adapter_status_counts | 每个已执行案例的顶层适配状态计数；有一个成功 option 的案例不代表其余 option 都成功 |
| candidate_validation_counts | 逐实际 option 的 B PASS/FAIL/UNKNOWN；无候选案例不虚构 UNKNOWN，另计 cases_without_candidates |
| changed_activity_count / added_activity_count | 所有可计算候选的数量之和，附 available_count/unavailable_count |
| unchanged_activity_retention_rate | 可计算候选保留率的等权算术平均，Decimal 28 位；不是全案例成功率，也不是按活动数加权 |
| budget_delta_cny | 可计算候选费用变化之和；保留负数，附可计算/不可计算候选数，不累加历史账本 |
| locked_activity_violations | 实际违规 ID 数量之和，另列存在违规的候选数；同一活动出现在不同候选分别计次 |
| adapter_elapsed_ms | 仅聚合 --measure 实测的本地逐候选耗时，未测或无可计算项时为 null |
| adapter_failure_reasons | 顶层及每个 option issues 的原因代码出现次数；同一原因出现在不同字段/候选可计多次 |
| execution_issue_counts | 排除原因及读入/差异/适配异常次数，不伪装成业务核验失败 |

指标汇总包含所有可计算候选，**包括 rejected 以及 B FAIL/UNKNOWN 的候选**，不筛出失败项来美化平均值。没有任何可计算值时 sum/mean/违规总量为 null，而不是 0。不能根据这些人工样本宣称算法最优、比真实 LLM 更快或真实旅游方案可行。

## 7. 未决接口与边界

A 的正式接口、稳定真实输出、授权格式、POI/日期/时区和费用证据来源仍未就绪；当前未接入真实 AgentArts，也不能将预留 agentarts_real 分类当作已支持真实实验。

A“完整返程结束严格早于截止”与 B“到达返程车站 <= 截止”仍不同；原有活动 ID 与 new_candidate 新稳定 ID 的区别也继续执行。不为提高通过率自动替换 ID、忽略返程约束、补造时间/证据或放宽确认门槛。C 的 options 到独立完整草案映射仍需联调；本阶段不修改 A/C 文件或任何业务数据库。
