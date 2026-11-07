# TravelGuard 仓库约定（AGENTS.md）

本文件供在本仓库工作的 AI/人阅读。补充 `~/.dsh/AGENTS.md` 的通用规则；冲突时以本文件的项目约定为准。

## 项目事实

- TravelGuard（旅途智盾），华为 ICT 大赛赛题 2：面向小团队旅行的多事件约束感知与最小必要重规划 Agent 系统。
- 三人分工：A = AgentArts 智能体与工作流；B = FastAPI 业务/工具后端（分支 `hsh/backend`）；C = React 前端、`data/`、`tests/`（分支 `cmx/frontend`）。
- 公共仓库：https://github.com/user1578/26ict.git；不直接改 `main`，不修改 B/A 的目录。
- 前端：React 19 + TypeScript + Vite，入口 `frontend/`；后端契约以 B 分支 `docs/api_contract.md` 为准（当前第五阶段）。
- 前端命令：`cd frontend; npm run build / npm run lint / npm test / npm run e2e`（e2e 需要 B 后端 8000 + dev 5174 + 本机 Edge）。
- 密钥：`X-Tool-Key` 只由 Vite dev 代理在服务端注入；不写进 `VITE_` 变量，不提交 `.env`。

## 设计上下文（来自 impeccable teach，2026-10-30 与用户确认）

### 用户
- 主要：大赛评审（3–5 分钟投影演示，需要快速看懂多事件、最小必要重规划、AgentArts 真实参与）。
- 次要：真实自由行旅客（行前/行中、手机、被打断时焦虑，需要可信解释与明确决定）。
- 第三：演示者/团队（需要稳定可复现、可讲故事、可回看证据）。

### 品牌人格
警觉（alert）、可靠（reliable）、在运转（in operation）。情绪目标：系统在替用户看住风险；不卖萌、不夸饰，未知就说未知。

### 美学方向
实时智能体控制台（Live Agent Console）：机场运行大屏 / 值班台 / 安全网隐喻；双主题（深色默认主态，浅色日间态）；记忆点 = 任务脊柱（行程时间轴）+ Agent 工作台（意图→工具→证据轨迹）+ 决策坞（候选对比与确认）。
反参考：通用 SaaS 卡片网格、聊天机器人、蓝紫渐变 AI 风、玻璃拟态堆叠。

### 设计原则
1. 决定时刻优先；2. 因果可见；3. 智能体有迹可循且模拟必标注；4. 真实/模拟/估算/未知严格分标，UNKNOWN 不冒充 PASS；5. 信号色只用于状态，主操作单色；6. 密度有节奏，不堆卡片；7. 双主题共享语义 token 与节奏。

## 关键约束

- 金额一律按十进制字符串/整数分处理；B 生成时间为 UTC，展示用 `Asia/Shanghai`。
- 写操作带 `request_id`；上报事件先 GET 最新 `event_revision` 再 PUT；确认必须 `user_confirmed:true` 且 `validation.overall === 'PASS'`。
- 一个草案 = 一份完整 `TravelPlan`（无 `options[]`）；对比用 `GET /drafts` 多草案。
- B 无 `/plan`、`/replan`：真实规划入口由 A 的 AgentArts 提供（未接入前前端演示规划器必须标注“模拟”）。
- 所有 `data/` 数据为 `simulated / unverified`，不得伪装成真实核实事实。
