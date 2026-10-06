# v6回归问题修复实施记录

当前状态（2026-10-06）：任务1—10、12、13完成；任务11本地隔离拓扑/HTTPS通过，可信公网HTTPS待补。修复留在隔离工作树，未提交、合并或部署。最新交付见末节；以下按日期保留历史过程。

## 2026-10-02：修复任务1隔离准备

执行起点为主检出master `9832bc0953bb2e2fe904d4f3afb7dc7273de558f`。主目录已有五份修改文档和两份新设计/计划，全部保留，未提交。旧工作树仍停在`b234ce9`，未用于本轮修复。

新建隔离工作树：`D:\Web_project\lottery_simulator\.worktrees\v6-reliability-fixes`，detached HEAD为上述基准。复制七份最新文档，源码未修改。工作树使用LF；原目录文件字节未改，原使用手册两处规范化换行后的内容一致。

环境只读检查：WSL Ubuntu-24.04的已有解释器Python 3.12.3、Node v22.23.3及`/home/lottery/frontend-deps/node_modules`可用。Windows监听127.0.0.1:8000和18080，WSL监听0.0.0.0:8000，未停止这些服务。Windows和WSL均未发现docker命令；任务11仍需可用的隔离Docker环境，未安装运行时。

独立环境位于仓库外`D:\Web_project\lottery-repair-tests-20261002\preparation-v6`。显式设置DATA_DIR、DB_PATH、JOBS_DIR、EXPORTS_DIR，全部指向该目录；数据库为history_v6.sqlite3，完整迁移已成功。仅创建临时测试账号，must_change_password=false、不可用密码，不涉及真实账号或Session。

准备脚本和日志位于同一证据目录的`prepare.py`、`preparation.log`。执行命令：

```bash
cd /mnt/d/Web_project/lottery_simulator/.worktrees/v6-reliability-fixes
PYTHONPATH=. /home/lottery/.venvs/lottery-simulator/bin/python -B /mnt/d/Web_project/lottery-repair-tests-20261002/prepare.py
```

初次准备脚本遗漏username_key，被既有数据库约束拒绝；随后补齐字段。脚本曾使用默认用户表名断言，已改为项目实际users表。最终迁移、临时账号和目录检查通过。这两项是准备脚本错误，未修改产品代码。

既有失败用例交接如下，原证据目录不复制进Git：

| 修复任务 | 既有证据（D:\Web_project\lottery-tests-20261002下） | 后续归属 |
|---|---|---|
| 2、3 | state-read-api-probe.py / state-read-api-results.json、performance/manager-get-errors.jsonl | 共享读取、API和准入故障断言 |
| 4 | django_probe.py、export_revision_probe.py、RESULTS_EXPORT_REVISION.txt | 分页及三类导出长整数 |
| 5 | frontend-recovery-isolated/src/pages/Results.recovery.test.tsx、results-recovery-vitest.log | 两项恢复失败断言迁入Results现有测试 |
| 7 | phase-order-results.json、cancellation-probes.py、cancellation-results.json | 提交回跳及取消边界 |
| 8 | installer_retry_probe.py | 初始化后拒绝重跑和提示 |
| 9、11 | REPORT.md中的来源桶探针 | 配置信任及真实拓扑分别验证 |
| 10、12 | security-probes.py、performance/performance-summary.json、browser证据 | 权限、八组任务及浏览器验收 |

已重新核对状态错误404→200、两条阶段回跳、5000位转换异常和两项前端恢复失败。长期断言按对应修复任务迁入既有测试，本准备阶段不新增一套重复测试。任务2—13尚未实施；本记录不是产品回归通过证明。

## 2026-10-02：修复任务2—10、12执行与暂停

状态：任务2—10、12已完成；任务11仅完成环境核对，真实Docker/Caddy拓扑及HTTPS仍未验；任务13未开始。用户要求完成当前任务后暂停，现暂停于任务12验收后。代码/业务验收通过，代理拓扑待验证，不能称全范围已验证。

所有产品修复仍位于`.worktrees/v6-reliability-fixes`，基准HEAD为`9832bc0`，尚未提交、合并或部署。主检出源码没有切换，本次仅同步新计划及实施记录；原五份未提交文档保留。按用户既有授权使用gpt-6-luna子代理分别承担查询整数、前端和安装/代理配置，共享状态与事务由主执行者串行整合。

### 已实施内容

| 范围 | 实际修改及验证 |
|---|---|
| R1（2、3） | 新增JobStateUnavailable；识别瞬态读错误最多3次、10/20ms退避；真实缺目录才返回None。规范UUID目录枚举代替state文件glob，损坏/缺状态/权限/危险链接均阻止准入、取消或清理。API固定503/storage_busy，认证先于读取，成功后仍校验所有权。worker保留不可确认状态及输出，已提交历史按冻结快照协调恢复，不重新模拟。账号删除未知状态前不标deleting，中途失败保留清单。 |
| R2（4） | 分页和池/规则/实验导出共享query_integer，非空十进制文本最长1024字符，5000位输入400；默认分页、前导零、404/409和seed契约保持。 |
| R3（5） | Results独立pollError，成功轮询只清轮询错误；取消/结果错误保留，401/403/404停止，5xx/网络GET恢复；空任务选择清旧结果，不重放POST。 |
| R7（6） | 基本信息标题先于实际字段且只出现一次；等级列表上低下高、首尾/单档标记；保底和赠送说明随参数更新，两种大保底模式明确主池抽中目标。大保底括号精确使用用户指定文案，周期赠送仍解释跨档查找。 |
| R4（7） | 保留全局锁和原子事务嵌套；saving进度由实际批次写入后发布，before_commit紧邻事务退出通知committing，再检查取消；幂等分支也走此边界，终态仅在提交成功后发布。 |
| R5（8） | 安装错误提示区分可重跑、已有材料及检查失败的未知状态；不再将所有残留都视为v5迁移。原保护及.env保留，不增加自动续跑/清理。 |
| R6（9） | internal backend和固定Caddy IPv4，app精确信任同一地址，Caddy覆盖XFF；严格IP解析及全IPv4路由表/Docker网络重叠预检，复用须匹配项目、桥、网关与自身路由，读取失败拒绝放行。 |

调用方核对：JobManager.get/get_active/_active_states/start/cancel/get_result/get_trace_reader/reap/reconcile；worker启动、进度、结果、提交、终态及错误恢复；runs详情/本人列表/busy/结果/Trace/取消/重存；管理列表与删除预览；账号删除两阶段；run_job命令。dashboard下不再存在任务state文件glob扫描。原格式校验及版本保持。

浏览器新增发现并闭环：规则表单390px视口曾被撑到493px，池表单曾被撑到837px；修复对应网格最小宽度与选择框收缩，名单仍在table-wrap内滚动，未用overflow hidden掩盖。公共池只读详情因缺少public选项误显示私有池，现显示公共池且保持禁用，新增回归。选择框统一42px高度，宽窄视口复验通过。

### 测试命令与结果

证据根目录：`D:\Web_project\lottery-repair-tests-20261002`。后端均通过仓库外`backend-command.py`显式指定backend-env的数据库/jobs/exports。完整迁移与schema检查也只使用该独立库。Windows创建的worktree元数据路径在WSL Git中不可直接解析，检查时显式设置GIT_DIR和GIT_WORK_TREE，不改真实仓库状态。

```bash
cd /mnt/d/Web_project/lottery_simulator/.worktrees/v6-reliability-fixes
PYTHONPATH=. /home/lottery/.venvs/lottery-simulator/bin/python -B /mnt/d/Web_project/lottery-repair-tests-20261002/backend-command.py test tests --verbosity 1
PYTHONPATH=. /home/lottery/.venvs/lottery-simulator/bin/python -B /mnt/d/Web_project/lottery-repair-tests-20261002/backend-command.py migrate --noinput --verbosity 0
PYTHONPATH=. /home/lottery/.venvs/lottery-simulator/bin/python -B /mnt/d/Web_project/lottery-repair-tests-20261002/backend-command.py makemigrations --check --dry-run
bash -n scripts/install.sh
```

- 后端最终完整回归：271项通过，287.432秒，`backend-final.log`。schema检查No changes detected，Shell语法通过。
- 前端完整回归：16文件、65项通过，`frontend-full-tests.log`。隔离源码副本`frontend-r3-r7-v6/frontend`复用已有Linux依赖；`npm test -- --run`及`npm run build`通过。最后仅追加池表单网格尺寸CSS，重新构建并实际浏览器复验，未重复全测试。最终源码副本与工作树一致，聚合SHA-256 `6cf567be300186fa9188c0383b7d8f7a5c459c7f9a6ec4befee8a182c823590c`。
- 状态读取/管理/删除/准入定向：初轮25项通过；补元数据确认和删除中断后18项定向通过，均纳入最终全套。查询数字定向8项通过。
- 提交/历史/端到端组首轮21项中1项故障注入错误：使用RuntimeError模拟数据库commit，而Django事务处理按数据库异常契约回滚；改用OperationalError后受控边界2项通过，并纳入最终全套。涵盖末批次/通知/提交失败回滚、最后取消检查、同run_id幂等及提交后终态不可读恢复。
- 安装/代理定向unittest最终24项通过；Django受影响部署/安装组27项通过。首轮集中回归在部署文件继续调整时加载旧mock，且WSL Git路径未显式设置，出现6失败/1错误；冻结源码与修正验证环境后最终271项全过。保留首轮日志，不将其计为通过。
- 既有Django RawSQL/full_clean警告及Vite大chunk提示仍存在；本轮没有新增依赖、数据库迁移或格式版本。

### 八组真实任务、竞争和取消

批次`task12-20261002T113012Z`，zmd、seed42、10轮；每根4个任务串行，合计8个唯一job_id/worker PID。每项completed且history_saved，运行中匹配worker数始终1。两根分别为仓库外performance-win及Linux`/tmp/lottery-repair-perf-20261002T113012Z`。

| 数据目录 | 每轮主抽 | Trace关闭耗时（秒） | Trace开启耗时（秒） |
|---|---:|---:|---:|
| Windows挂载 | 240 | 48.583 | 52.534 |
| Windows挂载 | 480 | 52.922 | 67.149 |
| Linux | 240 | 46.760 | 48.543 |
| Linux | 480 | 54.607 | 57.143 |

表中为结果duration_seconds，非性能承诺；额外审计和并发读取存在开销。四组同抽数Trace开关的数值、计数、seed及理论/模拟结果一致。真实并发直读/API detail/busy未观察到None、假404或状态读错误；每根额外注入3次ENODATA，API503后下一请求200，与真实观察分开记录。

8组状态发布审计均记录完整阶段序列，无committing→saving回跳，且提交通知先于历史行可见。4个Trace任务的外部轮询未采到committing，不能称轮询完整捕获；以写入审计及任务7受控事务边界补证。Trace任务均记录saving total/total；无Trace没有事件导入批次，该进度不适用。审计时间戳分段仅作诊断，不能替代任务计时或ETA。

模拟/理论真实异步取消与校验/保存受控取消均成功，延迟分别0.9152/0.0626/0.0681/0.0765秒；无历史/事件/结果/Trace残片。完整证据在performance目录的summary、windows/linux-jobs、state-writes、fault-injection、cancellation文件。首个外置脚本因Session.update调用形式错误在提交任何任务前停止，修正后重新创建临时环境完整运行，无真实服务副作用。

### 浏览器验收及环境缺口

独立WSL后端8002、Windows代理18082，临时账号browser-env，前端仅使用隔离构建。普通用户登录→10抽/1轮/seed42/Trace预览→任务完成→历史→分类图表→10行Trace均通过。实际下载`browser-summary.json`和`browser-trace.jsonl`，汇总计数10/0/10，JSONL为1头部+10事件。下载工具等待较久，Trace采用真实下载文件核对，不以HTTP200替代文件内容。

测试服务器专用GET故障标记触发503，浏览器显示固定错误；移除标记后成功轮询清除旧alert（count=0）并显示完成结果。标记只作用于临时HTTP服务器，未改产品或worker源码。证据`browser-poll-503.jpg`及`browser-poll-recovered.jpg`。

390×844和1280×900验收：基本信息标题在名称字段之前、仅一处；上低下高标记、150抽动态阈值及两种模式说明正确。临时规则创建成功并复制池绑定，引用后添加/重排结构禁用；公共规则详情只读。池大保底目标文案正确，公共池类型真实显示且不能编辑。最终页面加载`index-C_IEEesT.js`与`index-D4WdI3j_.css`；390视口scrollWidth=375，名单表格内部滚动。截图包括browser-rules-wide/narrow/locked、browser-big-pity-narrow/once和browser-pool-target，失败前截图也保留。

Docker及独立Caddy不可用，没有安装运行时，未创建Compose卷/网络，未验证真实peer、重建后地址稳定性、两个真实网络来源或HTTPS证书链；任务11保持待验证。单元配置/来源桶测试不能代替拓扑验收。

本轮浏览器标签关闭、视口恢复；核对命令行后停止仅本轮browser-server.py进程及记录的Windows代理PID7772。临时库/证据保留于仓库外，未提交凭据/产物。结束检查未观察到8002/18082监听；也未观察到最初的8000/18080，未执行停止原服务的命令，不能据此推断其退出原因或声称原服务在线。

差异检查通过：local-usage、依赖清单/锁文件、迁移目录无差异，Git diff --check通过，真实.env/数据未改。实施与验证已结束，按用户要求暂停，不开始任务13或自动提交、合并、推送、部署。

## 2026-10-02：授权补齐环境与任务11实测

用户随后明确授权安装并验证。在WSL Ubuntu-24.04内通过Docker官方APT源安装Engine 29.8.2、containerd 2.3.6、Compose 5.5.1、Buildx 0.37.1，启用docker/containerd服务。没有安装Windows Docker Desktop、修改Windows代理/防火墙/WSL网络模式或授予普通用户docker组权限。PowerShell使用`wsl -d Ubuntu-24.04 -u root -- docker ...`调用。

环境证据根目录为`D:\Web_project\lottery-environment-20261002`。WSL直连Docker Hub超时；使用Windows已配置的回环代理，经原生curl保持系统TLS验证下载官方镜像，校验manifest/config/layer SHA-256及layer diff ID后docker load。hello-world实际运行、Caddy 2.11.4运行与原Caddyfile校验通过。镜像、Linux兼容wheel及安装/版本记录均保留，项目依赖文件未改；本轮不是Docker Hub直连成功证明。

真实Docker新增暴露并修复三个边界：

1. 未限制动态地址时，先启动的app占用`.2`，Caddy固定IP启动冲突；原生probe已实际复现。backend改用独立IPAM动态范围`LOTTERY_PROXY_DYNAMIC_RANGE`（默认172.30.96.128/25），预检要求规范子集、排除Caddy并留有app地址。
2. Docker会根据动态范围自动选择`.128`作为网关；原预检假定`.1`，同项目复用失败。现显式设置`LOTTERY_PROXY_GATEWAY`（默认172.30.96.1），校验范围及与Caddy/网络/广播地址冲突；复用必须同时匹配Subnet/IPRange/Gateway。
3. 内置host/none网络IPAM.Config为null，是正常的无独立IPAM网段状态；预检现正确处理，同时继续检查主机全部IPv4路由，不跳过有网段的网络。

上述修复仅在隔离工作树落地，无主检出切换。部署/安装定向组最终30项通过、21.585秒，证据`ipam-regression-final.log`；此前28/29项是中间版本，不冒充最终结果。新增检查均可运行，原业务/前端代码没有额外修改，本轮未重复上一轮完整271/65测试。

实际拓扑项目`lottery-repair-env-20261002`，外置fixture和脚本位于topology目录。离线验收Dockerfile复用原用户、健康检查、进程配置及固定依赖，额外WSGI包装仅返回测试peer/XFF响应头，不进入产品源码。测试脚本初次遗漏原healthcheck及seed脚本PYTHONPATH，属于验收搭建错误，已修正；配置切换期间旧Caddy动态`.130`的过渡轮不计作最终验证。

最终实测（`topology-run.log`最后一轮）：

| 检查 | 实际结果 |
|---|---|
| 网络预检 | 旧自动网关配置被拒；无旧backend时首次通过；新同项目配置复用通过；172.17.96.0/24与Docker bridge 172.17.0.0/16重叠时明确拒绝，无删除未知资源 |
| 服务网络 | app=172.30.96.128，位于动态范围；Caddy backend=172.30.96.2；app 8000无宿主端口；Caddy仅发布本机127.0.0.1:18083/18443，同时连接internal backend及default网络 |
| 本地HTTPS | 临时lottery-repair.test证书，由临时CA签发；curl显式使用ca.crt，首页/API均HTTP200、verify=0；没有-k、系统信任安装或浏览器警告绕过 |
| 真实来源与伪造头 | 两个同时常驻客户端172.30.97.10/.11发送相同伪造XFF；应用POST响应观察到REMOTE_ADDR=.96.2及各自真实XFF，逐次断言覆盖，未使用只有GET证据的假推断 |
| 来源桶 | A用20个不同用户名失败得到20次401，下一次429；B独立临时账号登录200，证明A来源限额不阻断B |
| Caddy重建 | force-recreate前后backend均.96.2，重建后本地HTTPS/API200、verify=0；B再次登录200，peer/XFF再次核对 |
| 公网出口 | Caddy网络命名空间能解析并连接example.com:443，但收到自签证书，默认CA TLS验证失败；未关闭验证、安装系统根证书或修改Windows网络来放行 |

因此任务11的本地隔离拓扑、临时证书HTTPS、来源分离和重建实测已通过，但可信公网HTTPS仍有环境缺口，不能标全范围已验证。正式域名/公网ACME本就未执行。任务13仍未开始，按原暂停边界不自动提交/合并/部署。

测试结束时app/caddy/client-a/client-b均exited，backend/default网络连接容器数0，保留4个仅本项目卷（lottery_data、lottery_backups、caddy_data、caddy_config）及测试证书、镜像和构建缓存。没有down -v或删除真实数据。Docker报告镜像510.4MB、构建缓存606.2MB，统计可能包含共享层；仓库外镜像档案另占空间。

恢复仅此测试项目：

```powershell
wsl -d Ubuntu-24.04 -u root -- docker compose --project-name lottery-repair-env-20261002 --env-file /mnt/d/Web_project/lottery-environment-20261002/topology/test.env -f /mnt/d/Web_project/lottery_simulator/.worktrees/v6-reliability-fixes/docker-compose.yml -f /mnt/d/Web_project/lottery-environment-20261002/topology/compose.override.yml up -d --no-build
```

该命令不是主项目上线命令，也不自动恢复测试客户端。证书仅有效2天；失效后须重新签发并重建测试Caddy，不绕过校验。后续清理只处理此项目且不加-v，保留卷直到明确核对用途；本轮没有执行最终清理。原本地使用手册、真实库、账号、.env及依赖清单保持不变。

## 2026-10-02：安装临时材料已按用户要求清理

用户明确要求清理此次安装产生的所有临时文件。核对归属后，删除仓库外`D:\Web_project\lottery-environment-20261002`整目录，包括下载镜像档案/解压层、wheel、安装与验收脚本、日志、临时CA/私钥/证书及配置。最初核对时72个文件约453MB；过程中产生的清理脚本和路径清单也随目录删除，没有把原始日志或凭据另存到其它目录。

Docker侧删除本轮4个已停止测试容器、2个空测试网络、4个测试卷（含临时账号库）、验收app镜像及hello-world示例镜像。逐ID清理本轮30条构建缓存，最终Build Cache=0；未使用全局system prune。删除本轮下载的13个APT安装包缓存，保留其它安装历史和缓存；Windows pip仅删除创建时间匹配且SHA-256与本轮wheel一致的2份新缓存及对应元数据。

保留已安装Docker/containerd/Compose/Buildx服务、官方Caddy/Python运行镜像、项目修复源码及已有项目文档。原真实数据库/.env/账号和`docs/local-usage.md`未改，之前任务12的独立测试证据目录不属于本次安装清理范围，保持原样。

前节安装/验证结果仍是历史实测，但原始证据文件和临时证书现已删除，旧测试项目恢复命令不再可直接执行；后续如需重新进行拓扑验收，须重新准备独立配置和证书。可信公网HTTPS验证缺口及任务13暂停状态保持。

## 2026-10-06：任务13文档与最终交付完成

当前汇总：修复任务1—10、12、13完成；任务11本地隔离Docker/Caddy拓扑、来源桶、重建和临时证书HTTPS通过，可信公网HTTPS仍未通过。本轮保持“代码/业务验收通过，公网HTTPS验收待补”，不标为全范围已验证。用户此次授权完成任务13，未执行提交、本地合并、推送、真实服务切换或服务器部署。

### 交付源码及验证范围

主检出为 `D:\Web_project\lottery_simulator` 的master；修复源码在 `D:\Web_project\lottery_simulator\.worktrees\v6-reliability-fixes`（detached HEAD）。2026-10-06重新核对，两处HEAD均为 `9832bc0953bb2e2fe904d4f3afb7dc7273de558f`。主目录产品源码仍是基准版本，不能把隔离工作树已修复等同于当前主目录服务已升级。

| 项目 | 最终交付依据与限制 |
|---|---|
| 状态与权限 | 共享读/枚举有界恢复或固定503；未知状态不放行第二worker、删除或取消；认证先于状态读，成功后校验归属。详见任务2—3记录及最小回归 |
| 查询及轮询 | 查询整数最长1024字符，超长400；成功GET只清轮询错误，5xx/网络失败可恢复，真正401/403/404停止，不自动重放POST |
| 保存与取消 | saving→committing→completed；保持全局锁与原子事务，最终取消检查、幂等及提交后终态故障恢复均有测试 |
| 规则界面 | 基本信息在上、上低下高、机制简短动态说明及目标文案；窄屏溢出和公共池类型误显示已闭环，宽窄浏览器验收通过 |
| 后端完整回归 | 2026-10-02的271项通过，287.432秒；不是2026-10-06重新跑测结果 |
| 前端完整回归 | 16文件65项通过；随后最后一次池表单CSS尺寸调整重新构建及浏览器复验，未重复全套65项 |
| 代理新增边界 | 实机发现动态IP冲突、自动网关及内置null IPAM问题后，部署/安装30项定向通过；未把它们追加冒充完整后端测试数量 |
| 环境与证据 | 任务12日志、八组真实worker/竞争/取消、截图及下载仍在 `D:\Web_project\lottery-repair-tests-20261002`；本次仅核对与整理，无源码改动，不重复已通过的业务测试 |

已有精确业务命令在上文“测试命令与结果”中；日志包括 `backend-final.log`、`frontend-full-tests.log`、`frontend-full-build.log`、`frontend-source-hash.txt`，以及performance目录。八组Linux/Windows×240/480抽×Trace开关均完整保存且数值一致；真实观察与注入503、短阶段审计与外部轮询的证据界限仍保留。

### 缺口与恢复边界

任务11未完成项为可信公网HTTPS：当时Caddy出站网络收到不受信任的自签证书，默认CA验证失败；未降低TLS校验或更改系统信任。正式公网域名/ACME签发及服务器部署不在本轮范围。补验前需核对当时网络问题是否仍存在，再使用独立项目、临时账号与客户端显式信任的临时证书；不直接操作正式服务。

用户要求的安装临时材料清理已经完成。原安装/拓扑原始日志、证书、配置、测试卷与验收镜像不再存在，前文恢复命令仅为历史记录，不能直接执行；30项定向和拓扑验收结果保留为历史摘要，不能称原始证据仍可读取。重新验收必须重建独立fixture与证书。Docker及官方运行镜像保留，不代表镜像仓库直连或公网TLS已通过。

### 文档、差异与Git核对

同步最新设计/计划、修改台账、部署验收状态及Windows临时说明；历史过程段落保留原日期，不将旧阶段记录当作当前状态。任务13四项复选框已完成，任务11公网HTTPS项继续未勾选。

任务13仅修改文档。执行以下检查（均由Windows Git执行，不修改全局换行设置）：

```powershell
git -c core.autocrlf=input -C D:/Web_project/lottery_simulator diff --check
git -c core.autocrlf=input -C D:/Web_project/lottery_simulator/.worktrees/v6-reliability-fixes diff --check
git -c core.autocrlf=input -C D:/Web_project/lottery_simulator status --short
git -c core.autocrlf=input -C D:/Web_project/lottery_simulator/.worktrees/v6-reliability-fixes status --short
```

检查结果与完整文件清单保存在仓库外 `D:\Web_project\lottery-repair-tests-20261002\task13-20261006\final-audit.json`。核对主检出仅文档变更、两处暂存区为空；修复工作树变更限于产品修复、测试和文档。原 `docs/local-usage.md`、configs、任务格式模型、迁移及依赖清单/锁文件对HEAD无差异；无真实.env/数据或测试产物进入待提交清单。本任务前后非文档变更文件的SHA-256一致，未访问或修改真实数据库内容。

新修复文件包括 `dashboard/api/query.py`、`scripts/check_proxy_network.py`、`tests/test_job_state_reading.py`、`tests/web/test_query_numbers.py`；新设计/计划/记录也尚未加入Git暂存区。既有未提交文档全部保留。没有新提交号/合并号；未推送、未fetch复核远端状态，不能用本地origin引用判断GitHub现状。下一阶段若要求本地集成或部署，应另行核对目标、数据与公网HTTPS缺口。
