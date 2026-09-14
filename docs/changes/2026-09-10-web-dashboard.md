# 交互式网页仪表盘

## 状态

✅ 本地功能已实现：模拟页面、后台任务、认证边界、结果展示、历史对比和真实 SQLite 备份/恢复均已验证。✅ 服务器部署接口已实现、静态合同已验证。⚠️ 按用户最新范围，真正服务器部署和测试暂缓；镜像/Compose/Caddy/公网 DNS、HTTPS、OIDC 与浏览器人工验收不在本轮完成声明内，服务器现场未验。

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

✅ 当前全量 `.venv/bin/python -m unittest discover -q`：129 tests / OK；任务 9 focused：41 tests / OK。✅ 本地 Streamlit `/_stcore/health` 返回 `200 ok`，镜像中定义的同一 Python 探针在本地解释器执行退出码 0，临时服务已停止。⚠️ 这些结果证明本地代码、SQLite 与配置合同，不证明镜像构建、容器运行、浏览器视觉或公网认证。

## Git 提交

- `5ec945e docs: design secure interactive web dashboard`
- `f2d61e4 docs: clarify dashboard trace and auth boundaries`
- `77a83bf15f227f571bbc0802bf3e06311b42c23e feat: add deterministic simulation progress hooks`
- `f79675c4e9b63b568fad491a638a07e0a0e8d998 feat: add dashboard data contracts`
- `75bc5d97d51e0d8a934665a1dc2b972285fc5266 fix: complete dashboard result payload`
- `4e8d5aa3bb12e93afe725bc072548ceb6e4c1925 feat: add transactional simulation history`
- `6eab1421d8d83a3dc09036dfba050af8438f3685 feat: add cancellable simulation jobs`
- `7984dcf715b5934f24a466a62aa4a51c88572f54 feat: add fail-closed dashboard authentication`
- `b12109553e404b388e405f73246618aac508ffdf feat: add dashboard result visualizations`
- `ce67c0dacccaf7d4585e4c05db3f54550744e53a feat: add interactive simulation dashboard`
- `a153efc0b3e053b4572e4eb9f515e72d00e5c8c9 fix: share dashboard job admission across sessions and sync mode`
- `a0f4764896b63caae8796c9a265d5fe4849eb7f5 feat: add simulation history comparison`
- `ad37a9c93c54cf0cfe9df458db25c2fc498cda34 feat: add secure Linux dashboard deployment`

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

## 任务 8：历史筛选、双运行对比、参数复用与确认删除

- ✅ 新增历史区：倒序列表展示时间、规则、种子、主池抽数、实验轮数、总六星均值和误差；支持规则、Trace、UTC 起止日期筛选，以及每页 20 条的页码分页。规则下拉提供当前及最近 20 条中的规则，也允许输入更早的已停用规则名。
- ✅ 最多选择两条历史并排展示；超限在控件回调中先明确提示“最多选择两次运行”，再截断并写回选中 ID 列表。规则名称、规则版本或快照 schema_version 不同时提示“统计口径不同”。筛选或翻页会清除不在当前页的选择。
- ✅ 历史卡复用已有结果渲染器，指标、数量分布、来源图、Trace 和 JSON 下载仅消费 SQLite 保存快照；没有保存的概率曲线不重算，明确提示“历史快照未保存概率曲线”。未知旧规则仍可展示历史；历史下载按钮按运行 ID 区分，防止双卡产生重复控件 ID。
- ✅ 复用按钮仅暂存运行 ID 并 rerun；下一轮在侧栏控件实例化前查询参数并写入明确 widget keys，不创建任务、不自动模拟。旧版本复用提示当前版本，已停用规则拒绝复用并保留现有输入。主池抽数默认值从 widget Session State 初始化，避免复用后双重默认值警告。
- ✅ 首次删除点击仅暂存确认 ID；独立“确认删除”才执行 repository 删除，“取消删除”仅退出确认态。确认删除沿用 SQLite 外键级联删除 Trace，随后清理已失效的选择。
- ✅ 认证仍在全部任务/历史访问之前；保留任务 7 的实例活跃任务发现、准入互斥、Trace 提交限制、轮询和终态展示。业务 Session State 仅存当前任务 ID、历史选择 ID、复用/确认 ID 与标量 widget 值；不存结果 payload 或 repository 对象。

### 验证

- ✅ RED：先用真实临时 SQLite seed 三条历史并写 `test_history_workflow`；`.venv/bin/python -m unittest tests.test_dashboard_app.DashboardAppTest.test_history_workflow -v` 得到 `AssertionError: '历史规则' not found in ['规则']`，退出码 1。没有 mock repository。
- ✅ GREEN：完整工作流覆盖倒序、规则/Trace 筛选、两卡、三选显式报错并截断、版本提示、旧规则快照、无自动任务的参数回填、取消删除、确认删除和 Trace 级联。另增日期范围/无效范围、22 条分页/空页、schema 口径不一致、已停用规则复用拒绝与外部删除后选择清理的 AppTest。
- ✅ 复用警告 RED：`assertNoLogs` 捕获 `draws` 的默认值与 Session State 重复赋值 WARNING；改用 Session State 初始化默认值后同一测试通过，未关闭框架告警。
- ✅ 因果验证：仅撤回 `[:2]` 截断，工作流出现“First list contains 1 additional elements”；恢复后 1 test / OK。仅在首次删除点击加入立即删除，出现 `AssertionError: unexpectedly None`；撤回该实验后 1 test / OK。两次实验互相独立且均恢复。
- ✅ focused：`.venv/bin/python -m unittest tests.test_dashboard_app tests.test_repository -v`，32 tests / OK；全量 `.venv/bin/python -m unittest discover -q`，120 tests / OK；`git diff --check` 通过。
- ⚠️ 上述结果验证真实 SQLite、AppTest 组件及状态流，不证明真实浏览器的并排布局、辅助技术可访问性、轮询计时或公网认证部署。旧快照无概率曲线数据，因此不提供历史概率曲线叠加；当前页以外的选择不会跨页保留。AppTest bare-mode 警告和既有 CLI 负例 stderr 保留，不是页面异常。

## 任务 9：本地备份验收与服务器部署接口

### 范围与实现

- ✅ 按用户最新裁定，本轮完成本地功能与验证；服务器功能/测试只保留接口和中文运维步骤，不实际部署。Dockerfile、Compose、Caddyfile、systemd service/timer 接口已实现，静态合同已验证。
- ✅ Dockerfile 固定 `python:3.12.14-slim-trixie`，安装现有 requirements，创建非 root `app`、数据/任务/备份目录，使用 exec-form Streamlit 命令与 Python HTTP health probe。Compose 固定 `APP_ENVIRONMENT=production`、`APP_AUTH_MODE=oidc`；白名单从环境注入，只有 `caddy:2.11.4-alpine` 发布 80/443；数据、备份、证书和 Caddy 配置使用命名卷，secrets 只读挂载。
- ✅ 新增 `scripts/backup_db.py`：路径 resolve、同文件/符号链接/硬链接拒绝、只读 URI 打开源库、SQLite backup API、目标 integrity_check、错误非零退出。它只保护数据库备份边界，不取代数据库业务逻辑或整机容灾。
- ✅ 修正端到端路径不一致：页面和 worker 原先固定 `history.sqlite3`，简报备份固定 `lottery.sqlite3`。经控制器裁定增加 `LOTTERY_DB_PATH` 覆盖，开发默认不变；Compose 固定 `/app/data/lottery.sqlite3`，页面/worker/备份三者一致。未做隐式旧库迁移。
- ✅ `.dockerignore` 排除 secrets、环境文件、数据库、备份和证书；扩展 `.gitignore` 保护根目录 SQLite 快照、私钥、证书与 Caddy 运行目录。未读取真实 secrets、未提交数据或凭据。
- ✅ README 与 `docs/deployment.md` 中文说明本地启动、DNS A/AAAA、端口、OIDC 回调与 secrets、权限、健康/日志、手动/每日备份、systemd 安装与实际 WorkingDirectory、停机恢复、升级、命名 Git 提交回滚，以及未来服务器验收清单。

### RED / GREEN / 因果验证

- ✅ 先写 `tests/test_deployment_files.py` 和数据库覆盖 AppTest，再运行 `.venv/bin/python -m unittest tests.test_deployment_files tests.test_dashboard_app.DashboardAppTest.test_deployment_database_override_is_used_by_page_and_worker -v`：9 tests，9 个预期 FAIL（8 项部署文件缺失、1 项覆盖路径未创建），退出码 1；最小实现后同命令 9 tests / OK。
- ✅ Git 私密文件边界增补 RED：真实 `git check-ignore` 只保护 4/9 路径，断言 `4 != 9`；扩展忽略规则后 9/9 路径被忽略。
- ✅ 真实临时 repository 和模拟 payload 验证：源库保持 WAL 连接时在线备份，备份含两条运行及完整 Trace；删除源记录后备份不变；用脚本恢复到停写的原库，记录/Trace 完整一致且可继续写入；目标 integrity_check 为 `ok`。包含 `#?` 的源路径验证只读 URI 正确转义；不存在源库不会被创建；同路径、符号链接、硬链接均拒绝且原记录保留。
- ✅ 使用真实 SQLite `ignore_check_constraints` 构造违反 CHECK 的行，脚本非零退出并报告 integrity 错误。因果实验只撤回 integrity 拒绝分支，同一测试恢复失败 `AssertionError: 0 == 0`；恢复分支后 1 test / OK。不是依赖 mock 或仅 grep 代码判断行为。
- ✅ Compose 采用不依赖 YAML 包的保守映射/JSON-inline-list 解析器进行静态合同断言；解析后的生产环境值交给真实 `AuthConfig` 验证，空白名单拒绝。Dockerfile 的 exec 参数以 JSON 解析，systemd 用 configparser/shlex 解析。⚠️ 这些不是 Docker/Caddy 官方解析器，不能证明容器网络或服务器运行成功。

### 最终验证与盲区

- ✅ focused：`.venv/bin/python -m unittest tests.test_deployment_files tests.test_dashboard_app tests.test_repository -q`，41 tests / OK；全量 `.venv/bin/python -m unittest discover -q`，129 tests / OK；`git diff --check` 通过。
- ✅ 本地 Streamlit 使用 `.venv/bin/python`、临时数据目录、development/disabled 和显式 loopback 监听；`http://127.0.0.1:8501/_stcore/health` 实测 `200 ok`，Dockerfile 定义的同一 Python 健康检查代码在本地解释器实测退出 0；随后临时服务正常停止（退出码 0）。首轮沙箱禁止 socket，获得仅本地监听的审批后完成。⚠️ health 只证明 HTTP 服务与探针存活，不证明页面渲染或登录；页面/worker/SQLite 由 AppTest 和 repository 回归单独验证。
- ⚠️ Docker 与 docker-compose、caddy 命令均不可用；范围调整前尝试的 `docker compose config`、`docker build -t lottery-simulator-dashboard:test .` 均为 command not found / 127。未安装工具，没有任何镜像/Compose 运行成功声明。范围调整后不再尝试服务器执行。
- ⚠️ 服务器现场未验：Docker 官方配置解析/构建/运行、卷初始化和权限、Caddy 自动证书、DNS/防火墙、真实 OIDC 回调/白名单联调、systemd 定时触发、容器停机恢复。当前无真实域名或 OIDC 凭据，这些保留为未来部署接口验证。
- ⚠️ 浏览器人工验收本轮暂缓，未产生桌面/窄屏布局、逐控件焦点、图表数值表可见性、15 个指标完整性或点击删除二次确认的真实浏览器观察。本执行环境未提供 in-app browser 工具；现有 AppTest 只验证对应组件与删除状态流，不能替代视觉验收。
- ⚠️ 备份仅含 SQLite 历史，不含任务文件、secrets 或证书；同名目标会覆盖，失败目标不可用于恢复。手册要求保留独立 pre-restore/pre-upgrade 备份与异机副本；没有添加自动保留/清理策略。未执行额外 SHA 或镜像摘要核验，Git 提交只用于追踪与回滚。

### 任务 9 审查修复 round 1：证书格式忽略边界

- ✅ 扩展部署合同测试，要求 `.dockerignore` 与实际 Git 忽略同时覆盖 `*.crt`、`*.cer`、`*.p12`、`*.pfx`；基线 RED 时 `git check-ignore` 仅匹配 9/13 个路径。
- ✅ 在 `.gitignore`、`.dockerignore` 补齐四种格式，并在部署文档逐项说明六种证书/密钥格式均不进入提交或镜像。
- ✅ 因果验证：仅撤回 `*.crt` 后 `git check-ignore certificate.crt` 返回非零且合同测试 12/13 失败；恢复后匹配并通过。
- ✅ focused `.venv/bin/python -m unittest tests.test_deployment_files -v`：8 tests / OK；全量 `.venv/bin/python -m unittest discover -q`：129 tests / OK。
- ⚠️ 未进行 Docker 构建或运行；按用户要求未做额外 SHA 核验。
