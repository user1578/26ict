# TravelGuard（旅途智盾）

TravelGuard 是华为 ICT 创新赛项目，面向小团队旅行，探索多 Agent 协作下的行程规划、预算与约束核验，以及面对交通延误、景点关闭等连续异常时的应急重规划。项目技术基线依据《初步计划书华为ict》V1.0：AgentArts 负责智能体编排，统一后端管理业务和数据，Web 前端承载规划、异常处理、方案比较与用户确认。

当前仓库先建立公共目录、开发环境约定和 Git 协作方式；各模块源码与依赖会在后续开发分支中逐步加入。

## 团队分工

| 成员 | 主要职责 | 主要目录 |
| --- | --- | --- |
| A | 华为 AgentArts 多 Agent 控制器与工作流编排、应急重规划；与 B、C 协调接口和联调 | agentarts/ |
| B（hsh） | Python FastAPI 后端、数据库/API 接入、预算计算、约束验证及状态一致性 | backend/ |
| C | React + Vite 前端、行程规划工作流界面、旅游数据整理与测试；规划 Agent 与 A 协作 | frontend/、data/、tests/ |
| 全体 | 公共接口约定、集成和验收 | docs/、tests/ |

AgentArts 中可导出的工作流配置、提示词和工具定义由 A 整理后提交到 agentarts/。不得提交密钥。无法导出的云端配置由 A 后续记录其配置要点和运行证据；仓库文件不代表所有云端设置都能自动还原。

## 统一开发环境

| 工具/组件 | 约定 |
| --- | --- |
| Python | 3.11，版本见 .python-version |
| Node.js | 24 LTS，版本见 .nvmrc |
| npm | 随 Node.js 安装；依赖版本通过各模块的锁文件统一 |
| Git | 2.x |
| 后端初期数据库 | SQLite |
| IDE | 推荐 VS Code，不强制 |
| AI 编程工具 | Codex、Claude Code 等按个人习惯选择 |
| 终端 | Windows PowerShell 5.1 或 PowerShell 7 均可 |

开始开发前，请在本机准备上述工具。此公共框架不安装项目依赖；各模块开始开发后，再通过各自的依赖清单与锁文件安装依赖。不要把 .env、密钥或本机凭据提交到仓库。

## 目录职责

| 路径 | 用途 |
| --- | --- |
| frontend/ | React + Vite 前端 |
| backend/ | FastAPI 后端、业务逻辑、API 适配与 SQLite 数据访问 |
| agentarts/ | AgentArts 工作流材料、提示词及可导出的工具定义 |
| data/ | 旅游地点、规则和来源等项目数据；注意区分可提交测试/公开数据与个人数据 |
| tests/ | 前后端、约束案例和集成测试 |
| docs/ | API 契约、技术说明和实验记录等项目文档 |

目录中的 .gitkeep 仅用于让尚无源码的公共目录进入 Git。

## 克隆仓库

仓库地址：

~~~
git@github.com:user1578/26ict.git
~~~

使用 SSH 克隆到本地 TravelGuard 目录：

~~~
git clone git@github.com:user1578/26ict.git TravelGuard
Set-Location .\TravelGuard
~~~

也可以使用 HTTPS：

~~~
git clone https://github.com/user1578/26ict.git TravelGuard
Set-Location .\TravelGuard
~~~

## 分支开发

- main：稳定集成分支。日常开发不直接向 main 推送。
- A：<成员A缩写>/agentarts。成员 A 的名字缩写确定后，将占位符替换为实际缩写。
- B：hsh/backend。
- C：<成员C缩写>/frontend。成员 C 的名字缩写确定后，将占位符替换为实际缩写。
- 具体功能也可以使用个人前缀分支，例如 hsh/backend-budget，再通过 Pull Request 合并到 main。

首次开始某方向开发时，从最新 main 创建个人方向分支；后续每项工作可继续在该方向分支上推进，也可按功能新建短期分支。A、C 的缩写尚未确定，本文不替成员编造。

以 B 的后端方向为例：

~~~
git switch main
git pull --ff-only origin main
git switch -c hsh/backend
~~~

A、C 分支示例（先替换为成员真实缩写）：

~~~
git switch -c <成员A缩写>/agentarts
git switch -c <成员C缩写>/frontend
~~~

<成员A缩写> 和 <成员C缩写> 是说明用占位符，不要原样作为分支名执行。

## Commit、Push 与 Pull Request

在个人分支完成一项改动后，先检查差异并仅暂存本次相关文件：

~~~
git status
git diff
git add <本次修改的文件或目录>
git diff --cached
git commit -m "简要说明本次改动"
git push -u origin <个人分支名>
~~~

随后在 GitHub 上创建 Pull Request，目标分支选择 main。在 PR 中说明变更、验证结果和相关影响；完成团队评审后再合并。不要直接向 main 推送，也不要用强制推送覆盖他人提交。

若 main 有新提交，在个人分支上先同步并解决冲突，再推送更新：

~~~
git fetch origin
git rebase origin/main
git push
~~~

PR 合并后，更新本地 main：

~~~
git switch main
git pull --ff-only origin main
~~~

提交信息应简洁、说明改动目的。不要提交 .env、访问令牌、API Key、私钥、个人配置、虚拟环境、依赖安装目录或本地运行数据库。