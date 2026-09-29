# 用户、角色池与实验配置实施记录

## 当前状态

- 2026-09-28：用户授权完成任务1～3，使用子代理并优先Luna。
- 2026-09-28：用户另行授权完成任务4；本次在同一隔离工作树直接执行。
- 2026-09-28：按已批准计划完成任务11；页面实现状态待任务14集中验收。
- 2026-09-28：按已批准计划完成任务12；结果、历史、图表及下载交互已实现，待任务14集中验收。
- 2026-09-29：按已批准计划完成任务13；管理员账号、配置和任务页面已实现，待任务14集中验收。
- 状态：实施中；主要功能验收集中在任务14。
- 设计：[设计](2026-09-24-user-pool-experiment-design.md)。
- 计划：[计划](2026-09-24-user-pool-experiment-plan.md)。
- 工作树：`/home/qykj/202607/test/lottery_simulator/.worktrees/user-pool-experiment`。
- 分支：`feature/user-pool-experiment`，基线：`e3c9bd8`。
- Git：未提交、未合并、未推送；原目录用户未提交文档保留。

## 范围与执行约束

已实施Django入口、纯任务模型拆分、新版配置与中文CLI、自定义用户ORM、账号会话、配置/模拟API、认证下载及任务10～13前端。
当前任务1～13已实现；任务14集中验收进行中，任务15未执行。本次未清理真实历史。
独立环境和临时数据目录，中途仅必要基础检查；完成实现不等于通过集中验收。

## 进度

| 任务 | 状态 | 实际检查 |
|---|---|---|
| 1 Django基础与模型拆分 | 已实现、待集中验收；代码审查放行 | Django check、模型导入、生产设置保护及路径检查通过 |
| 2 配置契约与中文CLI | 已实现、待集中验收；复审放行 | 语法/导入及2抽×1轮最小CLI连通通过 |
| 3 ORM与空库迁移 | 已实现、待集中验收；复审放行 | 临时空库迁移及二次幂等、迁移无漂移、v5标记与旧仓库拒绝保护通过 |
| 4 账号、会话及维护入口 | 已实现、待集中验收 | 临时测试库账号与会话定向测试12项通过 |
| 5 角色池权限、复制和导入导出 | 已实现、待集中验收 | 本任务仅做Django导入与路由解析检查；池权限、revision、导入导出和删除行为留任务14集中验收 |
| 6 用户实验配置与引用匹配 | 已实现、待集中验收 | Django系统检查通过；实验权限、引用竞争、导入确认等行为留任务14集中验收 |
| 7 任务归属、限额与历史持久化 | 已实现、待集中验收 | `tests.web.test_owned_jobs tests.web.test_owned_runs` 7项通过；并发及完整权限验收留任务14 |
| 8 账号删除与竞争处理 | 已实现、待集中验收 | 定向检查见任务8记录；真实并发竞态留任务14 |
| 9 认证下载与大文件 | 已实现、待集中验收 | 定向检查见任务9记录；大文件和浏览器原生下载留任务14 |
| 10 React基础、API客户端与登录 | 已实现、待集中验收 | Vitest 6项、TypeScript严格检查及Vite生产构建通过；多账号浏览器竞态留任务14 |
| 11 角色池与新建实验页面 | 已实现、待集中验收 | 前端定向测试6项、typecheck/build通过；临时内存库实验导入预览/确认1项通过；完整权限与浏览器流程留任务14 |
| 12 结果、历史、图表与下载交互 | 已实现、待集中验收 | 图表单测15项、前端定向5项、typecheck、Django check、Vite build通过；浏览器/多账号/大文件留任务14 |
| 13 管理员页面和账号生命周期 | 已实现、待集中验收 | 账号/会话/删除/管理API后端21项及前端Vitest 15项通过；typecheck/build通过；完整多账号浏览器流程留任务14 |

## 环境及实施详情

### 任务1

Luna实现任务模型机械搬迁和引用更新、新Django入口及环境配置。
独立解释器：工作树`.venv/bin/python`（Python 3.12.3）。
锁定Django 5.2.17、DRF 3.18.1、Gunicorn 26.2.0、Altair 6.2.2；暂保留原Streamlit依赖。
临时数据根为`/tmp/lottery-user-pool-task1.Q6hy6F/data`，库为其下`history_v5.sqlite3`，任务及导出分别为`jobs_v5`、`exports_v5`。
本任务未迁移建库、未启动服务；预留本地API 8000与Vite 5173端口。

实际检查：显式临时环境下`manage.py check`无问题；生产缺SECRET_KEY拒绝启动，生产DEBUG关闭；新任务模块导入通过；`tests.web.test_bootstrap`一项路径检查通过；旧任务模型引用扫描无遗漏；`git diff --check`通过。
未运行旧UI全套或功能验收，认证及ORM尚未实现，状态不标为整体已验证。

### 任务2

Sol实现新版池/实验文件契约、严格JSON读取、默认池和实验示例、中文CLI。
版本常量改为配置2、实验1、结果3、任务3、主库5；逐抽/临时Trace/导出/抽样版本未变。
最小检查：AST语法、模块导入、Rule1默认池加载与2抽×1轮CLI连通通过；完整边界与旧CLI断言未执行，留任务14集中验收。
关注：旧网页与仓库在过渡期仍不可作为新版入口使用。
审查发现交互提示污染JSON stdout、无关坏文件阻断池ID匹配；已修复，并通过针对性检查及只读复审。

### 任务3

Sol实现自定义UUID用户、池、实验配置、运行、逐抽、登录限流、应用元数据ORM及首次迁移。主库DDL由Django迁移建立，SQLite使用IMMEDIATE事务、20秒busy timeout；实验池关联删除置空，历史池来源为独立快照。
显式临时库`/tmp/lottery-task3-final-9qiVmv/schema.sqlite3`首次迁移成功，第二次无迁移，`makemigrations --check --dry-run`无漂移，数据库`user_version=5`；旧仓库在新工作树任务3～6整体停用，对v5及其他版本均明确拒绝，不能调用旧UI或让旧仓库误建表。原稳定目录未受影响。
审查发现旧仓库读取口一度绕过门禁及版本条件语义不清，均已修复，针对v5/v4临时库定向检查并复审放行。
`models.W045`提示RawSQL逐抽JSON CHECK不参与`full_clean()`预检，SQLite表内约束已生成；非法业务记录拒绝与权限/并发行为待任务14集中验收。

### 任务4

新增账号服务、数据库会话有效性中间件、认证与CSRF API，以及本机初始化、密码恢复和解锁命令。登录失败按账号和来源独立计数；密码、用户名、角色或启用状态变化通过`auth_version`撤销旧会话。SQLite IMMEDIATE写事务内检查最后可用管理员；原生`createsuperuser`和`changepassword`入口已禁用，避免绕过业务约束。

使用隔离工作树解释器与显式`/tmp/lottery-task4-check/auth.sqlite3`配置运行`manage.py test tests.web.test_accounts tests.web.test_sessions`，12项通过。检查覆盖密码边界、初始化幂等、最后管理员串行保护、账号/来源限流、可信来源头默认拒绝、匿名登录CSRF、登录和多会话撤销、轮询不续期、闲置过期及强制改密。Django仍提示任务3已知的`models.W045`，与本任务无关。`git diff --check`通过。

未运行任务14规定的双连接并发管理员保护、多标签页、完整来源代理部署及浏览器Cookie/CSRF验收；任务4状态是已实现、待集中验收。

### 任务5

新增角色池业务服务与API，支持可见池分页、创建/编辑、复制、严格文件导入、带revision检查的导出及二次确认删除。公共池只由管理员创建/编辑/删除；私有池owner来自服务端actor；私有复制默认隐藏、新UUID并保留最初作者；导入文件中的类型/所有权/管理员意图不授予权限；删除将实验引用置空并保留名称提示。revision冲突返回409，SQLite busy映射为storage_busy。

实现文件：`dashboard/services/pools.py`、`dashboard/api/pools.py`、`dashboard/api/serializers.py`、`dashboard/api/urls.py`、`tests/web/test_pools.py`。已编写任务5定向测试但未运行，遵循计划把测试留到任务14集中验收；只进行临时路径下的导入、Django系统检查及URL解析。API行为、权限矩阵、竞争条件和浏览器CSRF尚待任务14验收。

复审后敏感写服务在事务内按请求actor原始`auth_version`重验身份，并拒绝强制改密账号；API测试fixture补齐项目会话字段并关闭强制改密状态。增加撤销版本回归用例，未运行。

### 任务6

新增实验配置服务与API，提供本人列表和CRUD、管理员全量管理、revision条件更新与删除、同用户NFC名称唯一、owner视角池引用校验及配置JSON导出。管理员代管时仍以配置目标所有者的池可见范围验证，不因管理员身份扩大其可运行池。池引用导入拆分为预览与确认：按ID优先返回matched/confirm/select/unavailable及有权候选；确认保存时重新检查请求者版本、目标owner池权限和用户提交的候选revision。池失效时继续保留名称提示；无法构造有效pool_ref时导出明确提示重新选池，不伪造ID。API使用十进制字符串传输大seed，并在池引用不可用时只显示已保存名称提示，不暴露后来隐藏/改名的池名。

实现文件：`dashboard/services/experiments.py`、`dashboard/api/experiments.py`、`dashboard/api/serializers.py`、`dashboard/api/urls.py`、`tests/web/test_experiments.py`。已增加服务及API定向用例，包括管理员代管池权限、引用状态、候选revision复查、大seed及隐藏池改名提示；遵循计划未运行测试。显式设置`PYTHONDONTWRITEBYTECODE=1`运行`.venv/bin/python manage.py check`通过；无错误（0 silenced）。无数据库迁移或模拟运行；真实数据未触碰。

### 任务7

接通模拟任务与v5历史库：任务在全站锁内按当前登录用户、角色池可见性和revision重新校验，并冻结owner、池来源、有效种子及接受时限额；后台管理命令使用相同Django设置运行。历史由Django迁移管理结构，结果与分批Trace在同一事务保存；保存时按任务锁→数据库事务顺序处理，删除中的账号不再导入结果，已接受任务不因退出、禁用或降级而误停。重启核对保留仍在运行的进程。

新增本人任务找回、任务详情/取消/结果/Trace/图表及授权历史接口；管理员可按权限查看历史，但`jobs/mine`始终只列本人。服务端对历史和失败结果重存重新鉴权，API种子及可能超出JavaScript安全范围的计数使用十进制字符串。图表计算保留原始整数，重存操作者在写事务内再次核验。

隔离临时v5库下执行`manage.py test tests.web.test_owned_jobs tests.web.test_owned_runs`：7项通过；`manage.py check`与`git diff --check`通过。检查仅覆盖小规模提交、Trace保存与回滚、归属隔离、本人列表、版本拒绝及重存授权回调；双用户并发、真实浏览器、活进程重启和大规模下载仍待任务14集中验收。未使用真实数据库或任务目录。

任务8、9的草稿在任务7结束时尚未开放入口；后续用户已明确要求继续完成，实施结果见下文。

### 任务8

接通管理员账号列表、创建、修改、重置密码、解锁、删除预览及二次确认删除API。删除服务在任务锁内短事务标记`deleting`并撤销会话，释放数据库写事务后请求/等待目标任务退出；未确认停止不删除，返回`delete_incomplete`并保留删除中状态。已知任务ID持久记录于`AppMeta`，部分文件清理后即使`state.json`丢失，重试仍可定位残留目录。文件与导出清理完成后，同一事务删除个人池、配置、运行/Trace、会话和账号；公共池、作者文本及他人配置引用提示保留。最终数据库清理失败也返回未完成，可重试。

增加管理员删除范围预览，展示私有池、配置、历史、任务目录、导出文件及他人受影响的引用数量；确认时重新检查当前身份与实际状态。定向检查涵盖：最后/自身管理员限制、公共池保留、部分清理重试、任务未确认停止、HTTP二次确认和CSRF。真实双连接删除/提交竞态与活进程停止仍待任务14集中验收。

### 任务9

接通同一Django应用内的认证Trace下载。请求在服务端按运行所有者鉴权并限制普通用户匹配条数；每1000条写入私有临时JSONL时、每64KiB传输时重新读取数据库会话、账号、权限和资源，撤权后停止，不把错误追加到文件。使用单进程有界下载槽、流关闭时清理、跨进程文件锁及有界过期文件清理；活跃文件不会仅凭年龄删除。历史删除先清理非活跃临时导出，再在事务内重查权限并删除，避免清理失败却已删历史。

新版`export-trace`本机维护命令在明确数据库路径后初始化Django，新库实际导出JSONL保持原格式版本；小配置导出继续使用任务5/6的revision及即时权限检查。任务8/9共10项定向测试通过，包含临时物理v5库上的实际模拟、匿名/他人下载拒绝、撤权后流中断及本机导出；账号/会话与任务8/9联合回归22项通过，受影响的历史接口4项通过。旧账号测试夹具已调整为完成首次改密的管理员，确保最后管理员保护用例测试的是正确原因。`manage.py check`和`git diff --check`通过。Django提示既有`models.W045`，SQLite表约束仍生效。大文件、跨进程并发下载、磁盘故障、浏览器原生表单及完整会话生命周期待任务14验收。

### 任务10

新增`frontend/` React＋TypeScript＋Vite工程，Node要求为`>=22.12.0`，锁定npm依赖并使用同源`/api`代理至`127.0.0.1:8000`。API客户端固定使用`/api/v1/`、Cookie同源凭据和内存CSRF令牌；写请求获取并发送`X-CSRFToken`，401清理前端私有会话，403保留为错误。AuthProvider初始化按设计先取CSRF再查`auth/me/`，提供登录、退出、改密、用户信息与会话代次；会话失效和组件卸载会中止活动请求，代次校验丢弃旧账号的响应及迟到CSRF响应。成功登录后重新取轮换后的CSRF令牌；改密后服务端退出并清理本地状态。活动POST只由已登录区域内的用户点击/输入事件触发，按60秒节流，不在加载或轮询中触发。

实现登录页、强制改密界面、账号/角色侧栏、退出入口及`/experiments/new/`、`/pools/`、`/results/`、`/history/`、`/management/`五个后续页面路由壳；管理员路由在前端按角色隐藏/守卫，后端仍为授权依据。未保存密码、token或业务数据到localStorage；未提前实现任务11～13业务页面。依赖、脚本和严格TS配置位于`frontend/package.json`、`package-lock.json`、`tsconfig.json`、`vite.config.ts`；`frontend/.gitignore`忽略本工程的node_modules、dist、Vite缓存和coverage。

Node v24.20.0、npm 11.19.0。默认沙箱网络/写权限下首次npm操作未能完成；按隔离worktree精确范围获批后，`npm install --package-lock-only --ignore-scripts --no-audit --no-fund`成功生成锁文件，`npm ci --no-audit --no-fund`安装167个包。无全局依赖或系统配置修改。`npm run test -- --run`通过（2个文件、6项）；`npm run typecheck`通过；`npm run build`通过（Vite 7.1.7，44模块，产物位于被忽略的`frontend/dist/`）。初次在受限沙箱执行Vitest/Vite时因只读目录失败，申请精确worktree权限后重跑通过；build脚本改为`tsc --noEmit && vite build`以避免生成额外tsbuildinfo缓存。`git check-ignore`确认node_modules与dist已忽略，`git diff --check`及新增文件尾随空白扫描通过。

独立审查指出CSRF GET虽丢弃了旧代次响应，但尚未实际取消请求，旧`Set-Cookie`仍可能迟到；现为CSRF GET单独登记会话级AbortController，换会话时统一abort，调用方signal会联动中止，只有同代次响应才能更新内存令牌。审查另指出退出POST进行期间登录页已可重新提交账号；现增加`logoutPending`禁用登录按钮与同步ref入口保护，退出完成或失败后才解除，失败仍显示服务端未确认提示。新增/扩展定向用例验证CSRF跨会话取消、调用方signal传播及退出进行时拒绝登录；上述6项用例、typecheck和最终build均通过。

账号A慢响应后切换账号B的浏览器完整交互、多标签页、Django真实服务Cookie/CSRF、浏览器刷新/深链接与任务14其它验收均未运行；任务10状态为“已实现、待集中验收”，不代表任务14通过。无真实数据库、任务目录或下载数据操作，未提交、未合并、未推送。

### 任务11

接入`/experiments/new/`与`/pools/`页面，保留现有认证布局和路由守卫。角色池页读取授权可见池，支持公共/我的/他人公开筛选及管理员全部私有筛选、完整分页、名单/UP权重/稀有度/奖励编辑、复制、revision确认删除、JSON导入导出。实验页加载本人可管理配置和有权池，提供明确保存/修改/另存、导入匹配确认、导出以及只读池摘要；模拟提交显式触发、pending期间禁重复，提交网络结果不确定时不重发POST，读取`jobs/mine`多项并允许空列表再次查询。

所有实验API参数的数量和seed在页面状态中保留十进制字符串。配置导出由浏览器直接下载服务端文件，避免JavaScript解析大整数；导入文件原始JSON文本由前端包入`document`请求字段而不经`JSON.parse`。服务端预览把数量和seed统一序列化为十进制字符串，确认导入时在API适配层转回Python整数，再按原文件契约严格验证与保存；池/实验文件格式没有更改。导入池候选仅展示服务端按actor权限返回的匹配结果及当前可用池，确认保存附带所选池revision，服务端二次检查。

新增`PoolEditor.test.tsx`、`ExperimentForm.test.tsx`、`ImportDialog.test.tsx`、`NewExperiment.test.tsx`。前端定向测试6项通过（覆盖编辑值更新、大seed文本精确保留、页面导入raw JSON请求包裹保持原整数、提交不重试/5xx查询本人任务及空列表可再次查询、小数中间态保留至失焦提交）；`npm run typecheck`通过；`npm run build`通过（51模块）。隔离临时环境`LOTTERY_DATA_DIR=/tmp/lottery-task11.gwim7U`运行`tests.web.test_experiments.ExperimentAPITests.test_import_preview_then_confirm_requires_selected_current_pool`，1项通过，含100位seed预览字符串传输与确认往返；测试使用Django内存数据库。保留已知`models.W045` RawSQL提醒。`git diff --check`通过。

审查返修：POST `jobs/` 收到5xx也按结果未确认处理并查询`jobs/mine`；只有明确4xx错误直接显示，任何分支均不重试POST。池编辑的概率、权重和奖励改为局部十进制文本输入，保留`0.`中间态，在失焦时提交有限数值，无效输入恢复原值。返修后前端定向测试6项、typecheck及Vite build均通过；完整集中验收仍留任务14。

未运行全套测试或任务14浏览器验收；池权限矩阵、删除/复制/导入导出完整流程、实验配置多候选选择及多标签页同参任务核对均待任务14。无本机真实数据操作；未提交、未合并、未推送。

### 任务12

新增`Results`、`History`、`TraceTable`、`ChartPanel`、`DownloadForm`，接入现有路由。新建实验接受任务后进入结果页。结果页显示活动任务进度并按可见页面2秒、隐藏页面10秒轮询；终态、401、404及卸载停止，网络或5xx可重试；取消调用服务端接口。概览保留小型汇总JSON下载。分类统计覆盖星级、六星构成、具体角色、奖励、保底，主池/赠送/总计取各自后端数据；稀有度名称、指标、保底标题、完整Trace列说明取结果快照。按抽次图表支持内部4/5/6多选，空选不请求图表，选择只触发图表GET。Vega-Lite规格仅接收受控API内联数据，不接受外部数据URL；`vega-embed@7.0.2`由本地npm锁文件打包，组件卸载调用`finalize`。

逐抽只请求当前50/100/200条分页，支持轮次、来源、稀有度、角色及来源内位置筛选，提供基础列/完整列和匹配条数。Trace下载使用独立标签页的原生POST表单，字段为`csrfmiddlewaretoken`及JSON文本`filters`，不使用浏览器大Blob。历史页支持规则/Trace筛选、分页、查看、确认删除；重跑先展示快照与当前池差异，确认后重新GET检查池revision，再带`expected_revision`提交。重跑POST遇网络/5xx时标为结果未确认，查询`jobs/mine`供人工核对，不自动重发。普通用户隔离依赖服务端已有actor授权。

本任务执行：`frontend/npm run typecheck`通过；`frontend/npm run test -- --run src/components/DownloadForm.test.tsx src/pages/Results.test.tsx src/pages/NewExperiment.test.tsx`通过（3文件、5项，验证点击时先打开下载标签页、原生CSRF字段、404停止轮询及任务提交未确认）；`.venv/bin/python -m unittest tests.test_charts -q`通过（15项，含五类/三来源/快照显示名称）；显式`LOTTERY_DATA_DIR`、`LOTTERY_DB_PATH`指向`/tmp/lottery-task12-chart-check`的`manage.py shell`定向调用真实`_summary_charts(source=total)`，断言五类规格键及改名映射，通过且未创建数据库；`.venv/bin/python manage.py check`无问题；`frontend/npm run build`通过（677模块，Vega相关主包约1.15 MB，Vite仅提示超500 KB）；`git diff --check`通过。旧图表测试夹具的配置格式版本从1更新为当前2，原先3项版本不兼容错误随之消除。首次在受限沙箱build遇`node_modules/.vite-temp`只读，按精确隔离工作树目录申请权限后复跑通过。

未运行任务14集中矩阵：真实浏览器多账号隔离、下载中撤权/大文件传输、折线交互全组合、完整Trace与历史删除/重跑端到端均待验收。未连接或改动真实数据；未提交、未合并、未推送。

### 任务13

新增管理员页面及账号编辑、删除范围预览/确认和自助改密组件。管理员可以创建账号、修改用户名/角色/启用状态、重置密码、解锁登录及删除账号；修改账号只PATCH `username`、`role`、`enabled`，不发送`is_superuser`、owner等框架字段。删除账号前显示私有池（包括对其他登录用户公开的私有池）、配置、历史、任务目录、导出文件、受影响引用和保留公共池数量；勾选确认后才POST/DELETE，清理失败提示可重试。页面不显示解锁会启用账号；后端响应和界面均明确“解锁不改变启用状态”。改密复用`auth/change-password/`，成功后由认证状态清除当前会话。

实验配置管理员列表复用`experiment-configs/`的管理员范围与revision接口；编辑跳转到现有新建实验页并按配置ID加载，更新仍以原配置所有者校验池权限。任务列表新增仅管理员授权的`GET /api/v1/management/jobs/`分页接口；每条仅返回任务概要、owner UUID和用户名，不暴露文件路径。任务取消复用原任务授权服务，只对JobState定义的`queued`、`running`状态显示停止操作。普通用户直接调用管理员任务列表返回403。

必要检查：显式隔离环境运行`LOTTERY_DATA_DIR=/tmp/lottery-task13-check-20260929 LOTTERY_DB_PATH=/tmp/lottery-task13-check-20260929/history.sqlite3 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python manage.py test tests.web.test_accounts tests.web.test_sessions tests.web.test_account_deletion tests.web.test_management --verbosity 2`，21项通过；覆盖最后管理员保护、自删拒绝、公共池作者署名保留、删除预览、deleting失败重试、管理员任务列表分页、损坏state跳过及普通用户403。`frontend/npm run test -- --run`通过10个文件、16项，含PATCH业务字段allowlist、配置管理页及删除预览完成和显式确认前不提交；`frontend/npm run typecheck`通过；`frontend/npm run build`通过（681模块）。Django保留已知`models.W045` RawSQL警告；Vite提示压缩前主包约1.16 MB，构建成功。`git diff --check`通过。

未运行任务14规定的真实浏览器多账号/多标签页流程、账号操作完整CSRF UI流程、活跃worker真实停止竞态、并发最后管理员保护或大规模任务分页；不将本任务的定向测试等同于集中验收。无真实库、历史、任务目录或公网操作，未提交、未合并、未推送。

独立审查返修：P1确认删除目标可能错绑。删除对话框现由全屏遮罩阻止背景交互，按账号ID设React key；组件目标改变时清空旧范围/确认/错误，并记录预览目标ID，确认提交再次校验预览目标与当前账号一致。目标切换回归先在旧实现下观察到B账号确认按钮仍启用，修复后验证A的确认不会授权删除B，B须重新读取范围并勾选确认。P2管理员代管配置按所有者而非管理员可见范围筛选池；实验配置API返回`owner_is_admin`仅用于显示策略，普通用户所有者的候选限系统公共池、公开私有池和该owner自己的私有池，管理员owner仍显示全部。服务端保存时原有owner授权检查未变。

返修验证：新增`Management.test.tsx`和`DeleteAccountDialog.test.tsx`目标切换覆盖，以及`NewExperiment.test.tsx`普通owner池范围用例；均先在修复前复现对应失败，再通过。最终`frontend/npm run test -- --run`通过10文件/19项，`frontend/npm run typecheck`通过，`frontend/npm run build`通过（681模块，Vite仍提示主包超500KB）；隔离`/tmp/lottery-task13-reviewfix-20260929`运行`manage.py test tests.web.test_experiments.ExperimentAPITests.test_crud_is_authenticated_and_returns_decimal_seed --verbosity 2`通过（1项，验证owner角色字段）。Django已有`models.W045`提醒；`git diff --check`通过。未扩展至任务14浏览器流程。

后续返修：代管Alice配置时保留“配置绑定角色池”的owner可用池列表，并增加仅管理员代管他人配置时显示的“本次模拟角色池”，默认选配置当前绑定池。管理员可在该独立选择中改用自己可见的隐藏池发起归管理员本人的任务；提交读取模拟池ID及当前revision，不修改Alice配置。普通用户及管理员自己的配置仍只显示一个角色池选择。定向前端用例证明Alice保存选项不含Bob隐藏池、模拟选项含Bob池、任务POST采用Bob池ID/revision，且不发送配置PATCH。`frontend/npm run test -- --run`通过10文件/19项，`frontend/npm run typecheck`及`frontend/npm run build`（681模块）通过；Vite既有主包大小提醒保留。未运行任务14浏览器验收，未提交。

## 本批交付边界

以上为任务13结束时的状态，后续集中验收见下节。未提交、未合并、未推送。

## 任务14：集中验收（已完成）

2026-09-29在原隔离工作树执行。仅使用显式`/tmp`新库、任务和导出目录，未运行真实公网部署、未执行任务15、未提交/合并/推送。

- 核心10模块（rule1、probability、analysis、engine、bonus、pool_config、config_documents、cli、formats、limits）：181项，exit 0，85.116秒。日志`/tmp/lottery-task14-backend-vl6IaP/core-final.log`。
- Django `tests.web`：63项，exit 0，44.382秒。日志`/tmp/lottery-task14-backend-vl6IaP/web-final.log`。覆盖双连接管理员保护、单模拟竞争、删除/提交屏障、已接受任务生命周期、账号与会话、真实CSRF拒绝、配置隔离、大整数、下载1万边界及10001条管理员导出、磁盘故障、生成/发送撤权和活跃文件清理。
- 空临时v5库两次migrate及`makemigrations --check --dry-run`通过，第二次无新增迁移。生产缺密钥拒绝，DEBUG即使请求开启仍关闭。
- 浏览器本地流程与限制见[浏览器验收记录](2026-09-29-user-pool-browser-acceptance.md)。

发现并修复：任务结果池名称未映射；维护命令覆盖顺序导致Django原生命令绕过项目保护；初始化旧请求失败清空新账号；401响应体迟到清新账号会话；镜像导出目录权限、Gunicorn下载线程/超时及Caddy API匹配。两个前端竞态测试均先失败后通过。独立限定复审认为三项安全/部署返修已闭合；生产容器实际运行仍未测。

- 前端最终`npm --prefix frontend run test -- --run`：14文件29项，exit 0；`npm --prefix frontend run build`：TypeScript检查和Vite生产构建exit 0。Vite仅提示单bundle超500KB。测试覆盖认证迟到响应、池只读/复制与409草稿、配置提交未确认、结果停止、历史快照/重跑/删除确认、图表多选/空选和Trace内部星级键。
- `tests.test_charts tests.test_trace_store`补充共享统计与逐抽存储33项，exit 0。
- `manage.py test tests.test_deployment_files`使用显式临时路径执行8项，exit 0，4.269秒：部署静态合同5项，真实临时v5库在线备份/恢复3项。备份核对管理员密码哈希可验证、数据库Session、公共池、运行历史及12条DrawRecord，目标权限0600，源与目标同文件拒绝。未执行真实Docker/Caddy解析/启动或公网HTTPS。

验收分组证据：组1见BootstrapTests；组2见ConfigDocumentsTest/CLI/PoolConfig；组3见SchemaTests；组4见AccountServiceTests/SessionTests及维护命令实际注册；组5—6见Pool/Experiment服务和API测试；组7—9见OwnedJob/OwnedRun/AccountDeletion/Downloads及EndToEndTests。并发删除使用真实worker代码在线程内运行并将存活探测映射到线程，提交竞争只替换进程启动/探测，保留真实文件锁和数据库；不把这些证据等同于生产OS服务管理验收。

裁决：历史快照既有查看/下载权限不因原池后来隐藏而撤销，以设计6.4为准。实际用例确认当前池返回404，但本人历史及下载仍200；计划中的隐藏撤权不能机械套到本人历史。若改变该语义，需要另行修改权限模型。

任务15候选清理范围仅作只读列举：原主目录data下发现`history.sqlite3`、`history_v2.sqlite3`、`history_v3.sqlite3`、`history_v4.sqlite3`及`jobs/`、`jobs_v3/`、`jobs_v4/`旧任务根。未删除任何目标，也未证明旧进程停止；执行任务15前必须再次精确核对SQLite附属文件、每个任务文件、独立备份及实际进程，禁止删除整个data目录。

旧Streamlit覆盖映射及精确清理范围见[专项审计](2026-09-29-legacy-ui-coverage-audit.md)。先前整批移除审批曾拒绝；用户随后明确授权清理旧版本，在核对调用方后删除旧页面/旧认证、页面专用测试和不适用v5的旧仓库/任务夹具测试，去掉`streamlit[auth]`依赖，保留新版仍调用的Altair和共享Trace测试。未删除任何真实历史或原稳定目录文件。

旧入口清理后，显式`/tmp`路径运行`.venv/bin/python manage.py test tests --verbosity 1`，289项全部通过，exit 0，约132.8秒（仅既有RawSQL `models.W045`警告）；前端`npm --prefix frontend run test -- --run`为14文件29项通过，`npm --prefix frontend run build`含TypeScript检查通过，构建仅提示单bundle超过500KB；`git diff --check`通过。任务14本地功能/权限/数据隔离/备份及部署配置接口验收至此闭合。未做真实公网HTTPS、生产容器运行或服务器部署测试（按本次设计仅保留接口）；未执行任务15的旧数据清理/切换。工作树仍未提交、未合并、未推送。

独立清理复核发现旧`test_dashboard_models.py`同时含现用任务载荷契约；补建`tests/test_job_models.py`六项（严格版本、池快照/五星进度、状态控制字段、结果不含逐抽、零理论期望、JSON写入可读及无临时文件），定向运行六项exit 0。上述289项全组运行在该补测写入前，补测没有修改生产代码，故不把两次结果混写为“295项同次全组”。
跨任务核对未发现阻断问题。后续运行迁移或自动测试前仍须核对解析后的`LOTTERY_DB_PATH`及符号链接是否指向真实历史库；目前仅以显式`/tmp`路径操作，不能因此宣称所有未来测试路径都已自动受保护。
