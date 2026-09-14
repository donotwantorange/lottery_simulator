# 交互式网页仪表盘

## 状态

设计已确认；模拟页面、后台任务、认证与结果展示已实现，历史页面与部署集成继续按计划推进。

## 目标

为现有模拟核心增加个人使用的 Streamlit 网页仪表盘，并支持通过公网域名安全部署到 Linux。

## 已确认内容

- Streamlit 单体应用，SQLite 保存历史；
- Trace 开启时保存逐抽记录，否则只保存参数和汇总；
- Trace 仅允许单轮模拟启用；
- 左侧参数、右侧指标与图表的明亮数据工具布局；
- 参数标签使用“假设主池已累计多少抽仍未出6星”；
- 历史使用双运行卡片对比；
- 后台工作进程提供进度和停止能力；
- 公网入口使用 Caddy HTTPS、Streamlit OIDC 和邮箱白名单；
- Docker Compose 部署并持久化数据库与证书。

## 设计文档

`docs/superpowers/specs/2026-09-10-web-dashboard-design.md`

## 验证结果

实现后补充。

## Git 提交

- `5ec945e docs: design secure interactive web dashboard`
- `f2d61e4 docs: clarify dashboard trace and auth boundaries`

## 任务 5：认证与 fail-closed 配置

- ✅ 新增 `dashboard/auth.py`：仅接受 development/production 与 disabled/oidc；生产环境禁止关闭认证，OIDC 必须配置邮箱白名单；邮箱 trim/lower 后精确匹配。
- ✅ `AuthConfig.from_env()` 使用 `APP_ENVIRONMENT`、`APP_AUTH_MODE`、`STREAMLIT_SERVER_ADDRESS`、`ALLOWED_EMAILS`，默认 production/oidc/127.0.0.1/空白名单，因此缺省配置拒绝启动；构造即验证且不可变，访问门禁再次验证传入配置。
- ✅ 开发免登录仅允许 loopback；门禁同时检查 Streamlit 的实际 `server.address`，拒绝 CLI 覆盖环境变量后绑定公网地址。开发启动必须显式绑定，例如 `--server.address=127.0.0.1`。
- ✅ 未登录显示一个登录按钮并停止；白名单外显示“无权访问此应用”、退出按钮并停止；允许的用户返回规范化邮箱。业务代码不读取或暴露 token。
- ✅ 新增 `.streamlit/config.toml`，明亮主题、`client.showErrorDetails="none"`，不固定服务器监听地址；示例 OIDC URL 使用 `.invalid` 绝对 HTTPS 地址，secret 为空且不暴露 token。
- ✅ `.gitignore` 新增 `.streamlit/secrets.toml`、`data/`、`backups/`、`.env`；未读取真实 secrets 文件。

### 验证

- ✅ RED：`.venv/bin/python -m unittest tests.test_auth -v`，预期并实际得到 `ModuleNotFoundError: No module named 'dashboard.auth'`，退出码 1。
- ✅ GREEN：同一 focused 命令，15 tests / OK；全量 `.venv/bin/python -m unittest discover -v`，93 tests / OK。
- ✅ 因果验证：用 apply_patch 临时移除实际监听地址检查，运行 `.venv/bin/python -m unittest tests.test_auth.AccessGateTests.test_disabled_gate_rejects_actual_public_bind -v`，0.0.0.0、::、None 三个子用例均报 `ValueError not raised`；恢复后 focused 15 tests / OK、全量 `.venv/bin/python -m unittest discover -q` 93 tests / OK。
- ✅ 用当前安装的 Streamlit 读取主题/错误展示配置、用 `tomllib` 解析两个示例配置、检查示例 URL 与空 secret；`git check-ignore` 确认四类私密/运行期路径均忽略；`git diff --check` 通过。
- ⚠️ 以上可验证本地配置拒绝规则和访问门禁行为，不能证明真实 OIDC 提供商、HTTPS 回调、反向代理和生产网络部署已联调。全量测试的 `--trace requires --trials 1` stderr 来自既有负例，测试最终通过。

### 任务提交

- ✅ 实现提交：`7984dcf715b5934f24a466a62aa4a51c88572f54 feat: add fail-closed dashboard authentication`；本条在后续纯文档提交补记，避免同一提交自引用。

## 任务 6：图表数据适配与结果展示

- ✅ 新增 `dashboard/charts.py`：概率曲线调用现有 `waiting_time_distribution`、`distribution_stats` 与 `rule.probability()`；数量分布按整数键排序；来源对比只映射主池、赠送、总计三组模拟值与理论值。仪表盘未复制概率规则常量。
- ✅ 新增 `dashboard/views/simulation.py`：展示 15 个指标卡、三张 Streamlit 原生图表、汇总/主池与赠送拆分标签页、Trace 区与 UTF-8 JSON 下载；每张图表后紧邻可展开的数字数据表。
- ✅ Trace dataframe 仅在 `trace_enabled=True` 且记录非空时渲染；其他情况明确显示“本次运行未保存逐抽记录”。即使 payload 意外仍含记录，关闭 Trace 也不会把记录传给 dataframe。
- ✅ 新增 `tests/test_charts.py` 与 `tests/test_simulation_view.py`：字面量验证 Rule1 第 65/80 抽概率、数值键排序、来源映射；recording Streamlit double 只替换展示边界，payload 来自真实模拟器和 `result_payload()`，并验证全部组件标签、三张数字表、Trace 门禁及 UTF-8 下载字节。

### 验证

- ✅ RED 1：`.venv/bin/python -m unittest tests.test_charts -v`，预期并实际得到 `ModuleNotFoundError: No module named 'dashboard.charts'`，退出码 1。
- ✅ GREEN 1：同一 focused 命令，3 tests / OK。
- ✅ RED 2：`.venv/bin/python -m unittest tests.test_simulation_view -v`，预期并实际得到 `ModuleNotFoundError: No module named 'dashboard.views.simulation'`，退出码 1。
- ✅ GREEN：`.venv/bin/python -m unittest tests.test_charts tests.test_simulation_view -v`，5 tests / OK；全量 `.venv/bin/python -m unittest discover -v`，98 tests / OK。
- ✅ 因果验证：用 apply_patch 临时把 `if trace_enabled and records` 改为 `if records`；非 Trace 目标测试按预期失败，得到 `AssertionError: 4 != 3`。恢复门禁后 focused 5 tests / OK。
- ✅ `git diff --check` 通过。
- ⚠️ 这些测试能确认适配数据、展示调用顺序、Trace 数据边界与下载编码，不能替代真实浏览器的响应式布局、颜色对比和辅助技术人工验收。全量测试的 `--trace requires --trials 1` stderr 来自既有负例，测试最终通过。

### 任务提交

- ✅ 实现提交：`b12109553e404b388e405f73246618aac508ffdf feat: add dashboard result visualizations`；本条在后续纯文档提交补记，避免同一提交自引用。

## 任务 7：模拟页面、实时进度与 AppTest

- ✅ 新增可运行的 `dashboard/app.py`：宽屏“抽奖概率实验室”、侧栏参数与主区状态/结果；可见标签精确为“假设主池已累计多少抽仍未出6星”。Trace 在多轮时禁用并解释原因，提交时再次限制为单轮；无效工作量和种子保留控件输入，不创建任务。
- ✅ 完整页面和轮询 fragment 均先执行认证门禁，再访问任务/数据库；沿用既有环境变量。生产环境明确拒绝 `DASHBOARD_SYNC_JOBS=1`，未登录不渲染业务控件、不创建数据文件。
- ✅ 活跃任务每 0.5 秒轮询进度和用时、禁用开始按钮；轮询发现终态时完整 rerun，恢复开始按钮并展示结果。停止按钮只请求 `JobManager.cancel()`，不保存历史。
- ✅ 开发同步模式直接调用 `JobManager.start(..., synchronous=True)`，与后台模式共用参数校验、活跃任务互斥、锁和 queued 文件创建；只在准入结束后同步运行真实 worker。worker 独占完成后的自动保存职责。完成展示 15 个指标和 JSON 下载；取消/失败不保存结果或历史；历史保存失败保留完成结果、下载与安全提示。业务 Session State 仅新增 `current_job_id`，不保存 payload 或 manager。
- ✅ 修复任务 6 展示回归：图表和 dataframe 改用 Streamlit 1.63 支持的 `width="stretch"`；“绝对误差/相对误差”展示绝对值，原始 payload、SQLite 和下载仍保留带符号误差。
- ✅ 修复脚本入口的包解析：Streamlit console 只加入脚本目录时，入口补入项目根，不依赖启动目录或外部 `PYTHONPATH`。

### 验证

- ✅ 首轮 RED：页面缺失、负误差展示和真实渲染的 7 条弃用警告，三项均按预期失败；修复后页面/展示 focused 5 tests / OK。
- ✅ 生命周期 RED：完成、失败、保存故障、活跃禁用、停止、批量 Trace、生产同步拒绝共七项预期失败；最小接入后 AppTest 11 tests / OK。
- ✅ 隔离入口 RED：在临时工作目录以 `.venv/bin/python -I` 执行真实 AppTest，确认 `ModuleNotFoundError: No module named 'dashboard'`；补入项目根后通过。
- ✅ 最终 AppTest 14 项；focused `.venv/bin/python -m unittest tests.test_dashboard_app tests.test_simulation_view tests.test_charts tests.test_auth -v`，34 tests / OK；全量 `.venv/bin/python -m unittest discover -v`，112 tests / OK。
- ✅ 因果验证三组：撤回误差绝对值后出现 `-0.096000 != 0.096000`；将一张 dataframe 改回旧宽度参数后弃用告警测试失败；将 fragment 终态 rerun 改为直接返回后 `0 != 15`（未显示指标）。每组均单独恢复并重跑通过。
- ✅ AppTest 使用真实临时 SQLite、真实模拟和 worker。进度/取消用显式状态文件和同步 worker 推进；终态转换在读文件边界确定性执行 worker，不靠 sleep 或后台进程竞争制造 UI 时序。隔离启动检查是同步执行的独立 AppTest 进程，不是后台模拟任务。
- ⚠️ 测试验证页面组件、状态流、数据保存边界和渲染 API；不能证明浏览器真实 0.5 秒计时、响应式视觉布局、OIDC 提供商回调或公网部署。AppTest 的 bare-mode ScriptRunContext 警告、故意触发的 worker 失败日志以及既有 CLI 负例 stderr 均非 Streamlit 页面异常；全部 AppTest 最终零异常。

### 审查修复 round 1

- ✅ 页面先读取实例级 queued/running 任务，优先将其作为当前任务；新会话和保留旧结果的会话在本轮渲染前禁用开始按钮，显示进度和停止入口。没有活跃任务时仍显示本会话的终态结果。
- ✅ 删除复制准入协议的同步 JobManager 子类；同步与后台任务使用同一个 `start()`，生产进程启动、PID 写入与回收顺序保持不变；同步 worker 在释放准入锁后执行，避免再次获取同一锁造成死锁。生产页面仍禁止同步模式。
- ✅ 新增五项测试，覆盖 queued/running 跨会话控制、旧结果会话切换、UI 不绕过公共准入校验、同步真实 worker/SQLite 保存，以及同步参数无效／已有任务时拒绝创建。
- ✅ RED：跨会话的三个 disabled 断言失败；公共 `start()` 边界注入 `draws=0` 的真实校验拒绝时，旧同步适配器仍完成任务，错误提示断言失败。同步 API 两项测试最初因缺少 `synchronous` 参数报 TypeError。
- ✅ 因果验证：分别撤回实例任务发现逻辑和公共同步启动调用，前者恢复三个 disabled 断言失败，后者恢复“没有预期启动失败提示”；逐项恢复后对应目标测试通过。
- ✅ `.venv/bin/python -m unittest tests.test_dashboard_app tests.test_jobs -q`：34 tests / OK；`.venv/bin/python -m unittest discover -q`：117 tests / OK；`git diff --check` 通过。
- ✅ 三项故障场景的预期 ERROR 日志用 `assertLogs` 收集，不改变生产日志行为。
- ⚠️ 实例状态在页面 rerun 时发现，提交阶段仍由文件锁保证准入互斥；上述测试证明组件行为、文件／SQLite 协议和真实后台 worker 回归，不证明浏览器计时精度或公网认证部署。AppTest bare-mode ScriptRunContext 警告和既有 CLI 负例 stderr 保留。
