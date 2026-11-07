# TravelGuard 前端（成员 C）

TravelGuard（旅途智盾）华为 ICT 大赛赛题 2 的 React 前端。

当前版本（2026-11-06）已完成 **「实时智能体控制台」重设计落地**：双主题（深色值班 / 浅色日间）、任务脊柱 + 智能体工作台 + 决策坞结构、移动端单列布局；业务层仍通过开发代理调用 B 的 FastAPI（`/api/trips…`），保留纯内存 mock（`?mode=mock`）用于无后端演示。设计依据见仓库根 `.impeccable.md` 与 `handover/11-前端重设计-Brief-2026-10-30.md`。

## 快速开始

### 1. 启动 B 端（FastAPI）

```powershell
# 在仓库根目录；使用 B 的 hsh/backend 分支（或对应 worktree）
$env:TRAVELGUARD_TOOL_API_KEY = 'dev-secret'
$env:TRAVELGUARD_DB_PATH = 'D:\project\audit\backend-dev.sqlite3'
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

（没有 `backend/.venv` 时先按 B 的 `backend/README.md` 建 Python 3.11 虚拟环境并安装 `requirements-dev.txt`。）

### 2. 启动前端

```powershell
cd frontend
npm install
$env:TRAVELGUARD_TOOL_KEY = 'dev-secret'             # 必须与 B 的 TRAVELGUARD_TOOL_API_KEY 一致
$env:TRAVELGUARD_API_BASE = 'http://127.0.0.1:8000'  # 可选，默认就是它
npm run dev
```

打开 <http://localhost:5173/>。浏览器只请求同源 `/api/...`，由 Vite 开发代理在服务端注入 `X-Tool-Key`；**密钥不会进入浏览器包**。

### 3. 模式切换

| 模式 | 打开方式 | 说明 |
| --- | --- | --- |
| 真实后端（默认） | `npm run dev` / `http://localhost:5173/` | 写操作、核验、版本都来自 B 的 FastAPI；刷新/分享链接可按 `?trip=` 恢复 |
| 本地模拟 | `http://localhost:5173/?mode=mock`，或设置 `VITE_TRAVELGUARD_MODE=mock` | 纯内存 mock，接口形状/状态机/错误码按 B 实现近似，不访问后端；刷新无法恢复 |

页面右上角有模式切换链接和主题切换；切换模式会重置当前演示状态。

## 界面结构

```
任务简报 Setup      /                      左：产品说明 + Runbook；右：简报表单
运行台 Console      创建后                  MissionBar（版本/事件修订/Agent 状态）
                                           BudgetRail（预算分段 + 约束 chips）
                                           RouteSpine（任务脊柱：活动 + 异常信号 + 候选差异预览）
                                           AgentRail（控制器→工具→候选的演示轨迹）
决策坞 DecisionDock  有 pending 候选时      固定底部；多候选并排、核验明细、确认（PASS 才可用）
异常上报 SignalSheet 上报异常               晚点 / 闭馆两种模拟场景 + 影响预览
版本档案 HistoryDrawer 版本档案              只读版本历史与确认记录
```

- 双主题：`data-theme="dark|light"`，默认深色；偏好存 `localStorage['tg-theme']`。
- 设计 token：`src/styles/tokens.css`（OKLCH 色板、4pt 间距、字体与动效变量）；`src/styles/app.css`。
- 字体：Chakra Petch（拉丁/数字，`@fontsource` 本地打包）+ Noto Sans SC / Microsoft YaHei UI（中文）。
- URL 恢复：真实模式下 `?trip=<trip_id>` 会重新 `GET /trips /drafts /versions`；mock 模式不支持刷新恢复。
- 响应式：≥1120 双栏（脊柱 + 工作台）；≤1120 工作台折叠；≤720 单列 + 底部决策坞 + 全屏 sheet。
- 无真实 AgentArts trace：AgentRail 显示「本地演示轨迹」并标注模拟，接入 A 后替换 `services/agentTrace.ts` 即可。

## 脚本

```powershell
npm run dev      # 开发服务器
npm run build    # tsc -b + vite build（必须通过）
npm run lint     # oxlint（当前 0 warning / 0 error）
npm run test     # vitest：金额/时间、本地核验、规划器、mock 状态机
npm run e2e      # 端到端：B 后端 8000 + 本前端 dev 5173 + 本机 Edge
```

`npm run e2e` 用本机 Edge（playwright-core，无需下载浏览器）跑真实页面：
创建 V1 → 上报晚点 → 决策坞 → 确认 V2 → 上报闭馆 → 决策坞 → 确认 V3 → 版本档案 → 深/浅主题 → 移动端 → mock 模式。
截图默认写到 `D:\project\audit\screens-redesign\`，可用 `E2E_URL`、`E2E_SHOTS`、`EDGE_PATH` 覆盖。

## 目录结构

```
frontend/src/
  types.ts                  B 契约数据模型（TripView/VersionView/DraftView/EventView/TravelPlan…）
  styles/
    tokens.css              双主题 token、字体、间距、动效、基础 reset
    app.css                 控制台布局与全部组件样式
  hooks/useTheme.ts         深/浅主题 + localStorage
  lib/
    labels.ts               check 名称/状态 tone
    url.ts                  ?trip= 恢复与 URL 同步
  services/
    client.ts               TravelGuardApi 接口 + real/mock 模式选择
    httpApi.ts              真实 HTTP 客户端（fetch /api/...，统一错误解析）
    mockApi.ts              纯内存 mock（同接口、同错误码）
    apiError.ts             统一 ApiError + 用户可读错误
    planner.ts              前端演示规划器（初始 V1、异常后候选、草案请求）
    localValidation.ts      mock 模式下的本地核验（按 B 的 travel_validation 规则实现）
    agentTrace.ts           前端演示轨迹（A 未接入前的只读时序；替换点）
    dataset.ts              读取仓库根 data/ 三件套（POI/规则/证据）
    money.ts                金额：十进制字符串 ↔ 整数分
    time.ts                 Asia/Shanghai 时间格式化与 ISO 运算
  components/
    MissionBar / BudgetRail / RouteSpine / AgentRail / DecisionDock /
    SignalSheet / HistoryDrawer / SetupScreen / ui
  App.tsx                   状态机：创建 → 异常 → 候选 → 确认 → 版本恢复
```

## 与 B 契约的对应关系

- 所有金额字段为 JSON 字符串（如 `"300.00"`）；前端内部用整数分运算（`money.ts`），不依赖浮点累加。
- 服务生成时间为 UTC，展示统一 `Intl.DateTimeFormat('Asia/Shanghai')`；用户输入为 `+08:00`。
- 写操作全部带 `request_id`；幂等作用域是同一 `trip_id`。
- 上报异常：先 `GET /api/trips/{id}` 取最新 `event_revision`，再 `PUT /events/{event_id}`（乐观锁），随后生成新草案。
- 一个草案 = 一份完整 `TravelPlan`；对比通过 `GET /drafts` 多草案并排，不传 `options[]`。
- 确认按钮仅当 `draft.status==='pending' && validation.overall==='PASS'` 可用；`confirm` 带三修订号 + `user_confirmed:true`。
- 409 / 422 统一处理：`revision_conflict` 等冲突自动刷新状态；`verification_blocked` 展示 B 的核验明细。
- 不使用 `/plan`、`/replan`（B 未提供）：演示方案由前端本地生成并显式标注「模拟」，真实规划入口待 A 提供。

## 数据与证据

`data/wuhan_pois.json`、`data/wuhan_rules.json`、`data/evidence_registry.json` 是 C 维护的数据三件套，**全部为人工构造的模拟数据**（`data_type=simulated`、`verification_status=unverified`；`amap_id` 待补）。它们仅用于本地演示，不构成现实开放、预约或付款事实；页面所有证据引用都标注了「模拟，未核实」。

## 环境变量

| 变量 | 用途 | 是否进浏览器 |
| --- | --- | --- |
| `TRAVELGUARD_TOOL_KEY` | Vite 开发代理注入的 `X-Tool-Key` | 否（只在 dev 代理服务端） |
| `TRAVELGUARD_API_BASE` | 代理目标，默认 `http://127.0.0.1:8000` | 否 |
| `VITE_TRAVELGUARD_MODE` | 可选，`mock` 时默认本地模拟 | 是（非密钥） |

见 `.env.example`。**不要把任何密钥写进 `VITE_` 变量。**

## 未决事项

1. A 的规划/重规划入口、真实 trace 与 `TravelPlan` 输出格式（当前前端演示规划器 + 演示轨迹）。
2. 首次创建是否必须 PASS（当前按 B 严格版实现；演示数据已补齐模拟证据）。
3. 返程完成语义（A「完整返程完成严格早于截止」vs B「到达返程车站 ≤ 截止」）——在统一前页面不展示“返程可行”。
4. weather 事件（B 不支持，页面已不提供该按钮）。
5. 固定活动/预约改签授权格式（B 没有改签能力，页面不展示“已改签”）。
6. 适配器结果如何到达 C（A 直接返回还是后续 B 包 API）。
7. 评审演示脚本模式（自动播放 60 秒主线）尚未实现。

## 开发约束

- 只在个人分支（`cmx/…`）开发，不直接改 `main`；不修改 B 的 `backend/` 或 A 的目录。
- 不提交 `node_modules`、`dist`、数据库、`.env` 或任何密钥。
- 提交前必须：`npm run build`、`npm run lint`、`npm run test` 通过；涉及页面流程时跑 `npm run e2e`。
