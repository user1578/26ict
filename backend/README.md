# TravelGuard 后端（成员 B）

首批后端基线：Python 3.11、FastAPI，提供健康检查、确定性预算计算和基础行程约束验证。

**尚未实现**数据库、第三方地图/天气API、事件存储、版本提交及AgentArts联调。这些放到后续迭代；当前工具接口不代表最终团队接口契约。

## 本地运行

在仓库根目录执行（PowerShell 7或5.1）：

~~~powershell
py -3.11 -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Set-Location backend
$env:TRAVELGUARD_TOOL_API_KEY = '自行设置本地临时密钥'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
~~~

打开 http://127.0.0.1:8000/docs 查看接口文档。

本地测试（在backend目录）：

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
~~~

## 当前接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | /health | 健康检查 |
| POST | /api/tools/calculate-budget | 预算与付款退款计算 |
| POST | /api/tools/validate-plan | 时间、景点开放、预约、预算、步行、返程和历史活动锁定校验 |

两个工具接口要求请求头X-Tool-Key，其值与服务端环境变量TRAVELGUARD_TOOL_API_KEY一致；未设置服务端密钥时返回503，密钥不正确时返回401。本地测试密钥不得公开部署。

费用单位为人民币元，以十进制计算并作为JSON字符串输出。费用流水ID唯一；未到账退款不抵扣预算。

验证结果：PASS（通过）、FAIL（违反）、UNKNOWN（证据不足）、NOT_APPLICABLE（不适用）。对外部开放状态、真实票价和预约不做联网核实，**仅验证输入提供的事实与条件**；UNKNOWN不可当作PASS。

对外开放服务前还需要HTTPS、正式身份认证、资源隔离和第三方来源核验。涉及输入输出字段变更时，须与A、C对齐。
