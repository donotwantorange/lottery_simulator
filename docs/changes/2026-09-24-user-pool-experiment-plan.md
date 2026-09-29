# 用户、角色池与实验配置：React＋Django API实施计划

> **执行者要求：**逐任务使用 `superpowers:executing-plans`；若用户明确选择子代理执行，则使用 `superpowers:subagent-driven-development`。未获执行确认前仅审阅计划，不开始实现。

**目标：**保留模拟核心，将网页迁移为具备本地账号、用户隔离和配置管理的React＋Django应用。

**架构：**React/TypeScript/Vite同域访问Django/DRF，使用数据库Cookie会话。SQLite保存用户、配置及历史，模拟继续在单独进程执行，全站单模拟，不引入任务队列。

**技术栈：**Django 5.2 LTS安全补丁、兼容DRF、React、TypeScript、Vite、React Router、Altair/Vega-Lite、SQLite、Gunicorn。实施任务1时锁定准确版本及Node要求，不在本计划猜测补丁号。

**设计依据：**[已确认设计](2026-09-24-user-pool-experiment-design.md)。执行者必须同时阅读设计与计划。

**状态（2026-09-29）：**任务1—15已完成并本地合并至master；本地集中验收、真实v5库切换和小型模拟验收已完成。未推送、未做公网部署。具体证据和验证边界见[实施记录](2026-09-24-user-pool-experiment.md)。

**阅读说明：**下文保留原实施步骤、验收清单及执行时要求，未勾选框不代表当前任务未完成；最新进度以实施记录为准。日常操作见[本地使用手册](../local-usage.md)和[网页页面指南](../dashboard-guide.md)，无需重新执行本计划或再次清理数据。

## 一、统一执行规则

后续维护说明：本计划任务1—15的完成状态不包含之后新增的图表修改。2026-09-29响应式图表、悬停和数值表作为独立小修改记录于[图表修改记录](2026-09-29-position-chart-usability.md)，已定向验证但未提交；无需重新执行本计划。

### 统一验证与验收安排

本策略适用于全部实施活动：主执行、子代理、阶段审查、集成和返修。派发子任务时必须携带本策略。不得借默认技能流程重新引入逐任务TDD或反复全套测试。用户后来明确要求的专项验证按新要求执行。

- 测试要求和命令统一列在任务14，代码示例移至附录A；任务1—13仅负责实现交付，不强制逐任务测试。
- 中途仅按需要检查语法/导入、临时空库迁移、首次登录与API最小连通、阻碍后续工作的类型/构建错误，不每任务机械重复。
- 任务14集中验证核心回归、权限拒绝、并发竞争、找回任务、下载撤权、前端和多账号浏览器流程；修复后重跑受影响项与必要关联项，不反复全量测试。
- 路径隔离、认证保护、删除目标核对和进程停止属于安全前置条件，不能延后至真实操作之后；任务15前不触碰真实库。
- 记录区分“已实现、待验收”和“已验证”，延后测试不标通过。不增加无关测试、覆盖率指标或性能框架。

### 全局约束

- 路径相对 `/home/qykj/202607/test/lottery_simulator`；开始实施时创建隔离工作树，保留已有未提交文档，不能把工作树当作无关项目运行。
- 公共池归系统，owner为空；私有池属于用户。复制分配新ID，原作者署名不随改名/删除变化。
- 普通用户仅管理自己的实验配置、历史及任务；管理员可管理全部，不能删除自己或删除/禁用/降级最后一个可用管理员。
- 密码最低6字符；闲置30分钟、绝对12小时；账号5次失败锁15分钟，来源默认15分钟20次失败锁15分钟。参数可配置，生产登录不可关闭。
- 普通限额：每轮1000万主抽、100万轮、主抽乘积1亿、Trace实际100万条、下载1万条；管理员数量上限为None，但保留安全、分页、硬件和单模拟限制。
- 配置2、实验文件1、结果3、任务3、主库5；逐抽2、临时Trace1、Trace导出1、抽样1保持。规则版本仍字符串“2.0”，格式版本严格整数拒绝bool。
- 核心概率、随机消耗和赠送机制不变。新特性仅按设计实现，不增加动画系统、Redis、Celery、JWT、独立下载服务或旧历史兼容。
- 测试使用临时库/临时任务目录，绝不连接真实历史库。真实清理只在任务15进行，已有删除授权不替代目标核对。
- 用户要求中文界面、错误、CLI帮助和操作说明；JSON字段用稳定英文键。
- 阻断性故障先处理，不在失效基础上继续开发；验证安排统一遵循本章，不另设任务级测试门槛。
- 完成每任务更新实施记录：文件、功能、命令、结果、未验范围、Git状态。提交/合并/推送另按用户授权，不自动执行。

## 二、检查重点

1. 换账号后旧请求迟到不能显示上个用户的数据（任务10）。
2. 两管理员并发降级不能留下零个可用管理员；SQLite不能靠select_for_update（任务4）。
3. 提交已被接受但HTTP连接断开不能无提示重复提交（任务7、11）。
4. 用户被禁用/池被隐藏时，正在下载的内容必须停止继续生成/发送（任务9）。
5. 删除账号时工作进程刚完成持久化，不能残留历史或重新导入已删用户结果（任务8）。

## 三、文件职责与共同接口

| 路径 | 职责 |
|---|---|
| `webapp/settings.py`、`urls.py`、`wsgi.py`、`manage.py` | Django入口与环境配置 |
| `dashboard/models.py` | Django ORM模型；原任务dataclass搬到job_models.py |
| `dashboard/job_models.py` | 原RunParameters/JobState及任务JSON转换，不导入ORM模型 |
| `dashboard/auth.py`、`middleware.py` | 会话认证、失效、限流、CSRF相关入口 |
| `dashboard/services/accounts.py`、`pools.py`、`experiments.py`、`runs.py` | 授权后的业务操作，供API与维护命令共用 |
| `dashboard/api/` | serializers、errors、urls及按功能拆分的请求适配器 |
| `dashboard/repository.py` | 历史与批量SQL适配，DDL交给migrations |
| `dashboard/jobs.py`、`worker.py`、`trace_store.py` | 原任务控制与Trace复用，适配归属和接受时策略 |
| `dashboard/downloads.py` | 单应用受控下载，临时文件、分批生成、撤权 |
| `lottery_simulator/config_documents.py` | 无Django依赖的池/实验文件格式、严格JSON解析 |
| `frontend/src/api/`、`auth/`、`pages/`、`components/` | API客户端、身份、五页面、可复用控件 |
| `tests/web/` | Django/DRF集成与并发功能测试 |

新服务统一接收数据库查出的User实例（下称actor），不接受浏览器传入的角色作为授权依据。以下名字作为任务间契约，实施时不各自发明同义接口：

```python
# config_documents.py：普通dataclass，payload为经过验证的字典
load_pool_document(raw: dict) -> PoolDocument
load_experiment_document(raw: dict) -> ExperimentDocument
parse_config_json(data: bytes, max_bytes: int) -> dict
# services：异常由api/errors.py统一转HTTP
visible_pools(actor) -> QuerySet
save_pool(actor, payload: dict, *, pool_id=None, expected_revision=None) -> Pool
copy_pool(actor, pool_id, *, name: str, kind: str) -> Pool
save_experiment(actor, payload: dict, *, config_id=None, expected_revision=None) -> ExperimentConfig
submit_job(actor, payload: dict) -> JobState
get_run_for_actor(actor, run_id) -> SimulationRun
list_my_jobs(actor, page=1, page_size=50) -> dict
delete_account(actor, target_id) -> None  # 未完成清理抛DeleteIncomplete，绝不返回成功
```

PoolDocument字段为format_version/id/name/original_author/rule_name/rarity_labels/pool_config；ExperimentDocument为format_version/name/pool_ref/parameters。错误代码集中枚举：validation_error、unauthenticated、forbidden、not_found、revision_conflict、system_busy、rate_limited、storage_busy、delete_incomplete。测试用例里的辅助fixture在所属测试文件实现，不依赖真实数据。

## 四、任务与依赖

顺序：1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15。

阶段检查点：任务4（身份底座）、任务9（后端闭环）、任务13（前端闭环）、任务14（切换前验收）。前三项只报告进度，不自动暂停或要求完整阶段验收；用户另行要求暂停时遵守。任务14未通过不得切换真实数据。

### 中间阶段运行与数据库隔离

| 阶段 | 允许运行的入口 | 数据和环境 |
|---|---|---|
| 原稳定目录 | 现有Streamlit及原CLI | 保留原虚拟环境、v4库及原任务目录，不安装新依赖、不写入新代码 |
| 新工作树任务1—2 | 已完成的基础模块、配置CLI | 独立虚拟环境，临时数据根目录，不启动旧UI |
| 新工作树任务3—6 | Django迁移、已完成的账号/配置服务 | 临时v5库；历史仓库尚未适配时不可调用，不回退v4 |
| 新工作树任务7—9 | 接通后的模拟/历史/下载API | 同一临时v5库及私有临时任务、导出目录 |
| 新工作树任务10—13 | Vite＋Django本地联调 | 显式临时路径、与旧服务不同端口；按统一策略作必要连通检查 |
| 任务14—15 | 集中验收后才真实切换 | 先验证临时环境，再停旧进程、核对并清理授权目标、切换真实v5 |

任务1记录实际工作树、Python解释器、数据库/任务/导出绝对路径和端口，子进程显式继承新环境。禁止把工作树data链接到真实data，禁止沿用旧LOTTERY_DB_PATH。自动测试发现路径指向真实库应拒绝运行；不靠文件名猜测数据安全。

新分支旧Streamlit代码暂留不代表中间阶段仍受支持。设计第11.4节是此过渡方案依据，新增代码不需要同时兼容v4/v5。未接通的旧测试在记录中标“待迁移/未运行”，不假报通过。

### 任务1：Django基础与旧任务模型解耦

**目标：**建立隔离环境及Django入口，保持任务模型独立。

**依赖：**已确认设计、独立工作树与环境权限。

**文件：**新增manage.py、webapp/{__init__,settings,urls,wsgi}.py、dashboard/apps.py、dashboard/job_models.py、tests/web/{__init__,test_bootstrap}.py；修改requirements.txt、dashboard/models.py以及所有旧models导入。

**接口：**保留RunParameters/JobState原行为，从job_models导出；settings从LOTTERY_DATA_DIR/LOTTERY_DB_PATH解析新库路径。

**实施步骤：**

- [ ] 用rg列出全部`dashboard.models`引用，记录现有基线版本与测试位置（不重复运行全套测试）；将旧dataclass及序列化函数机械搬到job_models，更新调用者而不改逻辑。
- [ ] 建立显式临时路径及独立环境，必要检查确认不会写真实data；生产缺少SECRET_KEY拒绝启动、DEBUG关闭。
- [ ] 建立Django应用，固定依赖版本；本任务不初始化真实数据库，不删除Streamlit。



**交付物：**建立隔离环境及Django入口，保持任务模型独立。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务2：新版配置契约与中文CLI

**目标：**提供新版池/实验文件和中文CLI。

**依赖：**任务1的实现产物；接口依赖见本任务接口说明。

**文件：**新增lottery_simulator/config_documents.py、configs/pools/default.json、configs/experiments/default.json、tests/test_config_documents.py；修改formats.py、rules/pool_config.py、cli.py、tests/test_cli.py。

**接口：**产出共同接口中的文档模型和解析器；PoolConfig仍提供核心概率使用的数据，不包含用户权限。

**实施步骤：**

- [ ] 实现外层版本、池规则绑定与实验pool_ref。保留原名单和奖励默认值；ID使用稳定示例UUID。
- [ ] CLI增加--experiment-config；删除独立--rule覆盖，显式实验参数覆盖文件参数。无ID候选时按设计询问名称；非交互必须要求显式--pool-config，不猜。
- [ ] 所有解析错误中文化，帮助添加可执行示例；analyze及export-trace说明本机权限边界。



**交付物：**提供新版池/实验文件和中文CLI。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务3：ORM与空库迁移

**目标：**完成新库ORM和迁移，隔离尚未改造的旧仓库。

**依赖：**任务2的实现产物；接口依赖见本任务接口说明。

**文件：**新增dashboard/migrations/0001_initial.py、tests/web/test_schema.py；修改dashboard/models.py、webapp/settings.py。

**接口：**User、Pool、ExperimentConfig、SimulationRun、DrawRecord、LoginLimit、AppMeta；表字段、版本和约束以设计第5章为准。

**实施步骤：**

- [ ] 实现AbstractUser自定义UUID用户，AUTH_USER_MODEL首次迁移生效，业务admin仅用is_superuser；不开放原生admin CRUD。
- [ ] 迁移创建主库全部表与逐抽索引/check约束，设置user_version=5。此阶段新入口只经migrations建库；旧HistoryRepository连接前核验版本，遇v5直接拒绝且不执行DDL，禁止新入口调用旧仓库。
- [ ] 配置IMMEDIATE短事务、busy timeout、ATOMIC_REQUESTS=false，保留seed文本精度。



**交付物：**完成新库ORM和迁移，隔离尚未改造的旧仓库。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务4：账号服务、会话与维护入口

**目标：**提供账号、登录、会话及本机维护能力。

**依赖：**任务3的实现产物；接口依赖见本任务接口说明。

**文件：**新增dashboard/services/{__init__,accounts}.py、middleware.py、api/{__init__,auth,errors,urls}.py、management/commands/{init_admin,reset_admin_password,unlock_login,createsuperuser,changepassword}.py、tests/web/test_accounts.py、test_sessions.py；修改auth.py、settings.py、urls.py。

**接口：**`require_actor(request)->User`、`change_password(actor,current,new)`、`update_account(actor,target_id,payload)`；统一auth_version撤销。

**实施步骤：**

- [ ] 使用Django密码API、数据库会话和显式登录csrf_protect；实现30分钟闲置、12小时绝对期限，轮询不更新活动。
- [ ] 实现账号与来源限流、到期/管理员解锁；解锁不启用账号、不清来源桶。可信代理配置拒绝任意来源头。
- [ ] 维护命令getpass双输、初始化原子写默认池和标记；不得重复导入；重置所有会话失效，内置命令不能绕过约束。
- [ ] 实现最后管理员并发保护，禁止用SQLite select_for_update充当锁。禁用/用户名/角色变更都撤销已有会话，旧任务不被误停。



**交付物：**提供账号、登录、会话及本机维护能力。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务5：角色池权限、复制和导入导出

**目标：**实现池权限、复制、署名与导入导出。

**依赖：**任务4的实现产物；接口依赖见本任务接口说明。

**文件：**新增services/pools.py、api/pools.py、api/serializers.py、tests/web/test_pools.py。

**接口：**visible_pools/save_pool/copy_pool；所有者来自actor，创建公共池仅管理员。

**实施步骤：**

- [ ] 实现revision条件更新和名称约束；冲突409不覆盖；类型转换只能copy，新UUID，默认隐藏，保持最初作者文本。
- [ ] 严格导入新建池，忽略文件的权限意图；无署名使用导入者，导入重名需改名。
- [ ] 删除二次确认expected_revision，仅删除有权目标；别人引用置空，不泄露引用详情。



**交付物：**实现池权限、复制、署名与导入导出。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务6：用户实验配置与引用匹配

**目标：**实现用户实验配置及池引用匹配。

**依赖：**任务5的实现产物；接口依赖见本任务接口说明。

**文件：**新增services/experiments.py、api/experiments.py、tests/web/test_experiments.py；修改serializers.py。

**接口：**save_experiment、`resolve_pool_reference(actor, pool_ref)->dict`（状态matched/confirm/select/unavailable与有权候选）。

**实施步骤：**

- [ ] 实现仅本人列表与CRUD、管理员代管；管理员为别人保存时以所有者视角验证池可用。
- [ ] 名称唯一与revision更新，引用失效保留名称提示。确认导入时再次查权限和revision，不能复用过期预览授权。



**交付物：**实现用户实验配置及池引用匹配。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务7：任务归属、限额与历史持久化

**目标：**接通任务归属、限额、持久化和本人任务找回。

**依赖：**任务6的实现产物；接口依赖见本任务接口说明。

**文件：**修改jobs.py、worker.py、job_models.py、limits.py、trace_store.py、repository.py；新增services/runs.py、api/jobs.py、api/runs.py、management/commands/run_job.py、tests/web/test_owned_jobs.py、test_owned_runs.py。

**接口：**submit_job/get_run_for_actor；新增`list_my_jobs(actor, page=1, page_size=50)->dict`供`GET /api/v1/jobs/mine/`使用，排序、字段与权限遵循设计第7章。内部JobManager不暴露给未授权API，worker接受服务端快照和限额策略。

**实施步骤：**

- [ ] 在全站锁内重新核验用户、池revision和参数，冻结owner/池/策略；保持原取消及提交保护。
- [ ] 进程使用Django设置，同事务导入历史与逐抽，保留分批机制；失败结果重存也必须鉴权。此时完成仓库切换并删除旧隐式CREATE TABLE实现，才接通依赖仓库的模拟API；不在任务3提前破坏尚未适配的调用链。
- [ ] 全局busy只有布尔，所有任务/历史/Trace/聚合端点按owner或管理员过滤；种子及大计数API用十进制字符串。
- [ ] 实现mine接口，补accepted_at接受时间快照，按本人分页列出运行中及结束任务，管理员不扩大查询范围。验收覆盖无需ID找回、他人隔离、稳定排序、空列表、分页和任务已结束场景。



**交付物：**接通任务归属、限额、持久化和本人任务找回。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务8：账号删除与竞争处理

**目标：**实现账号删除与任务提交竞争下的一致性。

**依赖：**任务7的实现产物；接口依赖见本任务接口说明。

**文件：**修改services/accounts.py、jobs.py、repository.py；新增api/management.py、tests/web/test_account_deletion.py。

**接口：**delete_account；管理删除未完成返回delete_incomplete，不返回204。

**实施步骤：**

- [ ] deleting标记与撤销先提交，随后释放数据库事务等待任务退出；严格先任务锁后数据库锁。
- [ ] 停止已确认后清任务文件，最后事务删个人数据；失败保留deleting，允许管理员显式重试。



**交付物：**实现账号删除与任务提交竞争下的一致性。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务9：认证下载与大文件

**目标：**提供认证分批下载及撤权清理。

**依赖：**任务8的实现产物；接口依赖见本任务接口说明。

**文件：**新增downloads.py、tests/web/test_downloads.py；修改trace_export.py、api/urls.py、services/runs.py。

**接口：**`download_trace(request,run_id)->StreamingHttpResponse`；生成前和传输期间读取当前session/用户/资源，不依赖缓存request.user。

**实施步骤：**

- [ ] 分批1000条写私有临时文件，64KiB发送；按设计每批/每块撤权校验。资源不存在、会话过期、账号禁用立即停止，不能追加错误文本到数据文件。
- [ ] 小配置导出检查revision，隐藏后不再可导出。生成前失败中文返回，传输后失败中断；finally关闭/清理文件，磁盘不足不损坏历史。
- [ ] 并发槽默认一个，第二个下载暂忙但控制请求仍可响应；断开、隐藏、删除时正确清理，遗留清理不能删除活跃临时文件。



**交付物：**提供认证分批下载及撤权清理。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务10：React基础、API客户端与登录

**目标：**建立React客户端、登录与会话状态。

**依赖：**任务9的实现产物；接口依赖见本任务接口说明。

**文件：**新增frontend/package.json、package-lock.json、tsconfig.json、vite.config.ts、index.html、src/{main,App}.tsx、src/api/{client,types}.ts、src/auth/AuthProvider.tsx、src/pages/Login.tsx、src/api/client.test.ts、src/auth/AuthProvider.test.tsx。

**接口：**`apiRequest<T>(path, options, signal): Promise<T>`、AuthProvider提供当前用户/会话代次/login/logout；API base固定/api/v1/。

**实施步骤：**

- [ ] 建立Vite代理，TypeScript严格模式；测试运行采用Vitest与React Testing Library，固定依赖并提供dev/build/typecheck/test。
- [ ] 实现登录、强制改密、退出、五页路由壳；仅cookie会话，禁存token和密码到localStorage。
- [ ] 服务结果以用户/资源键隔离，AbortController配合会话代次；活动POST只来自用户事件，自动轮询不保活。



**交付物：**建立React客户端、登录与会话状态。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务11：角色池与新建实验页面

**目标：**实现角色池和新建实验页面。

**依赖：**任务10的实现产物；接口依赖见本任务接口说明。

**文件：**新增frontend/src/pages/{Pools,NewExperiment}.tsx、src/components/{PoolEditor,ExperimentForm,ImportDialog}.tsx及同名.test.tsx。

**接口：**使用任务5/6/7 API；表单expected_revision来自加载返回，不自行递增猜测。

**实施步骤：**

- [ ] 实现名单/权重/奖励/名称编辑，公共与私有筛选、复制/删除确认、导入导出；实验仅选池，规则只读。
- [ ] 输入种子和大计数用字符串，禁止Number造成精度丢失；前端校验不代替后端。
- [ ] 提交只在显式用户动作触发，pending禁重复；网络不确定调用mine显示本人最近任务，让用户按时间/参数核对，不自动选择最新项或重试POST。空结果提供再次查询；多标签页同参数情形列入任务14验收。



**交付物：**实现角色池和新建实验页面。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务12：结果、历史、图表与下载交互

**目标：**实现结果、历史、图表筛选及下载交互。

**依赖：**任务11的实现产物；接口依赖见本任务接口说明。

**文件：**新增frontend/src/pages/{Results,History}.tsx、components/{TraceTable,ChartPanel,DownloadForm}.tsx及测试；修改dashboard/charts.py、api/runs.py。

**接口：**结果汇总、Trace分页、图表规格API；图表筛选内部值4/5/6，显示用快照映射。

**实施步骤：**

- [ ] 保持原总览/分类/Trace/按抽次行为，React封装vega-embed并卸载释放；静态资源本地打包，禁止外部数据URL。
- [ ] 活动任务2秒轮询，终态/401/卸载停止；停止按钮走cancel服务。历史重跑差异确认后重新查池revision。
- [ ] 下载用原生CSRF POST及独立标签页，不用巨大Blob。历史删除确认，别人的记录不会出现在列表或查询结果。



**交付物：**实现结果、历史、图表筛选及下载交互。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务13：管理员页面和完整账号流程

**目标：**完成管理员界面及账号生命周期。

**依赖：**任务12的实现产物；接口依赖见本任务接口说明。

**文件：**新增frontend/src/pages/Management.tsx、components/{AccountEditor,DeleteAccountDialog,ChangePassword}.tsx及测试；完善api/management.py。

**接口：**只提交业务role/enabled/name字段，经服务转换，不能直传框架管理字段绕过保护。

**实施步骤：**

- [ ] 实现账号创建/编辑/禁用启用/重置/解锁/删除，全部任务和实验配置管理；角色池与历史管理沿用原页面。
- [ ] 改密和角色修改后所有标签页失效，已启动任务继续；管理员恢复命令能解锁但不启用禁用账号。



**交付物：**完成管理员界面及账号生命周期。记录为“已实现、待集中验收”，不自动暂停；必要基础检查遵循第一章。

### 任务14：集成验收、说明和部署接口

**目标：**在临时环境集中证明完整流程可用，完成说明及切换准备。

**依赖：**任务1—13已实现；未完成模块先补齐，不以缺失模块为由跳过相应验收。

**文件：**修改README.md、docs/local-usage.md、docs/dashboard-guide.md、docs/deployment.md、requirements.txt、scripts/backup_db.py及部署目录实际服务文件；新增tests/web/test_end_to_end.py、前端浏览器验收记录。

**接口：**只更新实际已完成入口的操作说明，不把拟定命令提前当可用。

- [ ] 在临时v5库从migrate→init_admin→登录→配置→模拟→历史→Trace下载跑通，检查完整权限矩阵。
- [ ] 运行纯核心unittest定向全组、Django tests.web全组、前端test/typecheck/build；将旧Streamlit测试覆盖迁移后才移除旧入口/无用依赖。
- [ ] 使用真实浏览器验证CSRF、Cookie、刷新/深链接、第二账号、原生下载、无CDN图表，自动测试不替代浏览器行为。
- [ ] 文档写两个本地开发进程、同域代理、生产静态dist及/api分流、密钥不能放VITE_、Web重启与模拟进程生命周期。部署配置不真实上服务器执行。
- [ ] 备份源库/前缀更新v5并在临时库备份恢复测试；文档说明备份含密码哈希与会话，不公开。
- [ ] 任务14结束先报告验证、缺口和具体真实清理清单；未验收通过不得执行任务15。

验收覆盖对应设计第12章所有行；测试注入的预期错误日志不能冒充测试失败，也不能忽略真正非零退出。

#### 集中验收矩阵

以下用例及命令在本任务组织执行；仅实现示例不能代替真实模块或浏览器验收。命令统一使用隔离工作树的解释器与临时数据库，不使用真实库。修复后只重跑影响范围及必要关联项。

同一次全套运行若已覆盖多个验收组，直接复用其结果，不按组重复运行。下面定向命令用于定位失败或选择覆盖范围，不是要求在总验收之外全部再跑一遍。前端类型检查和构建无相关变更时仅执行一次；所有Python命令使用工作树虚拟环境解释器。

#### 验收组1（对应任务1）

- [ ] 显式临时目录不写真实data，生产缺少SECRET_KEY拒绝启动，DEBUG关闭。
- [ ] 运行`.venv/bin/python manage.py check`及旧任务模型/核心定向测试。预期原行为不变。

#### 验收组2（对应任务2）

- [ ] 测试旧版本/bool版本/重复JSON键/NaN/超5MiB输入拒绝，以及缺省稀有度名称、重名显示名称拒绝。
- [ ] 运行`.venv/bin/python -m unittest tests.test_config_documents tests.test_cli tests.test_pool_config -v`。
该测试置于unittest.TestCase，不新增pytest依赖。

#### 验收组3（对应任务3）

- [ ] 编写空临时库约束测试：公共owner为空、私有owner非空、唯一名称、删除池后配置引用置空、历史池快照不级联。
- [ ] 执行`manage.py test tests.web.test_schema`，另对临时路径运行migrate两次，第二次无重复初始化。检查迁移漂移`makemigrations --check --dry-run`。

#### 验收组4（对应任务4）

- [ ] 两个数据库连接并发尝试降级/禁用最后管理员，至少保留一个可用管理员；不能仅在单连接串行测试。
- [ ] 写测试：密码5字符拒绝/6字符通过、登录匿名POST无CSRF拒绝、用户名不存在/密码错/禁用提示一致、强制改密只能访问允许端点。
- [ ] 执行`manage.py test tests.web.test_accounts tests.web.test_sessions`。

#### 验收组5（对应任务5）

- [ ] 构建两普通用户和一管理员测试集，测试公开/隐藏、他人ID、列表隔离、公共owner为空。
- [ ] 运行`manage.py test tests.web.test_pools`。

#### 验收组6（对应任务6）

- [ ] 测试ID优先、ID不存在时单/多名称候选、无候选、ID无权时不披露详情，不自动创建池。
- [ ] 运行`manage.py test tests.web.test_experiments`。

#### 验收组7（对应任务7）

- [ ] mine接口无需ID找回本人运行中和已结束任务；管理员仍仅查自己，验证分页、稳定排序、空列表及他人隔离。
- [ ] 写普通限额拒绝、管理员None限额通过、赠送计入Trace、两用户同时提交仅一成功测试。
- [ ] 集中验收时模拟提交已接受但响应丢失：调用mine能找回，禁止自动重发；客户端查询过早为空也不能判定失败。登出/禁用/降级不停止已接受任务。
- [ ] 运行`manage.py test tests.web.test_owned_jobs tests.web.test_owned_runs`及核心engine/analysis/bonus定向测试。

#### 验收组8（对应任务8）

- [ ] 写二次确认、自删拒绝、最后管理员拒绝、先停任务后删、公共池/他人历史保留测试。
- [ ] 用测试同步屏障停在worker提交点，触发删账号；允许合法提交先完成，但删除结束必须无该用户历史/可恢复文件。清理权限错误必须可重试而非成功。
- [ ] 运行`manage.py test tests.web.test_account_deletion`。

#### 验收组9（对应任务9）

- [ ] 下载断开、隐藏池、删除记录及会话撤销停止后续读取；临时文件清理不误删活跃导出，磁盘不足不影响原库，控制入口仍可访问。
- [ ] 测试匿名/他人链接拒绝、无CSRF POST拒绝、普通1万边界、管理员超过1万完整导出。
- [ ] 运行`manage.py test tests.web.test_downloads`。

#### 验收组10（对应任务10）

- [ ] 测试CSRF获取、登录后轮换、401清状态、403不当作成功、账号切换后旧响应丢弃。
- [ ] 运行`npm --prefix frontend run test -- --run`、`npm --prefix frontend run typecheck`、`npm --prefix frontend run build`。
另用延迟fetch Promise：A账号请求未返回→退出→B登录→释放A响应，断言页面仍为B且无A的资源文本；AuthProvider卸载须中止请求。该竞态用例为集中验收必需项目，不以单独401测试代替。

#### 验收组11（对应任务11）

- [ ] 测试只读池隐藏编辑按钮、复制新池、导入ID/名称确认、409保留草稿和默认实验不自动保存。
- [ ] 运行前端测试、类型检查及构建；本地登录两个账号验证隔离。

#### 验收组12（对应任务12）

- [ ] 测试折线单选/多选/空选、中文稀有度改名、主池/赠送筛选不重启模拟。
- [ ] 运行前后端图表/Trace测试及前端构建。
组件测试同时断言显示空选提示、未发起模拟POST，不仅测试过滤表达式。

#### 验收组13（对应任务13）

- [ ] 测试删除范围包含公开私有池但不含公共池、署名不变、自删/最后管理员拒绝、deleting失败可重试。
- [ ] 验证普通用户直接访问管理API被拒绝，不以菜单隐藏作为通过证据。
- [ ] 运行管理员后端与前端测试。


**放行条件：**设计第12章必需行为全部有证据，无未解决的阻断问题；记录未验公网范围及清理清单，才允许进入任务15。

### 任务15：授权范围内切换旧历史与最终交付

**执行状态（2026-09-29）：**已完成；本地快进合并至master，真实旧数据已精确清理，v5初始化及真实登录/小型模拟/历史/Trace验收通过。清理清单、验证边界和交付状态见同主题实施记录。未推送、未做公网部署。

**目标：**按授权精确切换真实数据并交付。

**硬性前置：**任务14通过、真实目标核对完成、旧进程确认停止。任一未满足则暂停，不执行删除。

**文件：**仅执行核对后的数据清理，更新docs/changes/2026-09-24-user-pool-experiment.md及README台账；不得清理整个data目录。

- [x] 读取实际环境和运行进程，列明旧数据库、SQLite附属文件、旧任务及临时Trace目标；核对独立备份/新版账号配置不在范围。
- [x] 明确停止旧服务并确认所有模拟/导出进程结束；无法证明停止就暂停，不凭PID文件猜测。
- [x] 按用户已授权的旧历史范围执行精确删除；所需文件系统审批仍正常申请。记录被删目标与是否存在独立备份，不承诺可恢复。
- [x] 切换v5后migrate与初始化按实际状态执行；已有账号不得重建/清空。初始化密码必须由用户交互输入，不代替用户选择或在日志输出密码。
- [x] 做小型本地登录/模拟/历史验收，不使用管理员无限量参数进行压力实验。
- [x] 交付实施记录与中文启动说明，明确未做公网部署、Git提交/合并/推送状态。若用户仅批准执行部分任务，不执行本任务。

## 五、计划自查与执行选择

设计覆盖：第1—2章→任务1/10/14；第3章→2/5/6；第4章→4/5/8/13；第5章→3/7；第6章→4—8；第7章→4—9/10；第8章→10—13；第9章→2/5/6/9/12；第10章→4/7/9/10；第11章→2/4/14/15；第12章→任务14集中验收及任务15切换后最小检查。

推荐分阶段顺序执行，不并行修改核心共享模型和接口。简单文案/表单任务可以在用户选择子代理后交给轻量模型；认证、账号删除、任务竞争、流式下载须保留独立审查。计划审核通过后再由用户选择当前会话逐任务执行或子代理逐任务执行。实现过程中发现设计冲突先报告，不能以“计划已批准”为由自行扩范围。


## 附录A：验收代码示例

以下是任务14验收时参考的最小示例，不是任务1—13的强制TDD步骤。fixture由实际测试实现；表达式示例必须补充真实组件/接口断言，不得以示例通过代替功能验收。

### 示例1：Django基础与旧任务模型解耦

```python
def test_job_parameters_remain_framework_independent():
    from dashboard.job_models import RunParameters
    p = RunParameters('rule1', 2, 1, 0, 42, False)
    assert p.validate().draws == 2
```

### 示例2：新版配置契约与中文CLI

```python
def test_reject_duplicate_json_key(self):
    with self.assertRaises(ValueError):
        parse_config_json(b'{"name":"a","name":"b"}', 1024)
```

### 示例3：ORM与空库迁移

```python
def test_public_pool_has_no_personal_owner(self):
    pool = Pool.objects.create(name='公共', name_key='公共', kind='public',
        visibility='public', owner=None, original_author='作者',
        rule_name='rule1', config_json={}, revision=1)
    self.assertIsNone(pool.owner_id)
```

### 示例4：账号服务、会话与维护入口

```python
def test_anonymous_login_requires_csrf(self):
    client = Client(enforce_csrf_checks=True)
    response = client.post('/api/v1/auth/login/',
        {'username': 'admin', 'password': '123456'}, content_type='application/json')
    self.assertEqual(response.status_code, 403)
```

### 示例5：角色池权限、复制和导入导出

```python
def test_copy_preserves_original_author(self):
    original = self.make_pool(owner=self.user_a, visibility='public', author='原作者')
    copied = copy_pool(self.user_b, original.id, name='副本', kind='private')
    self.assertNotEqual(copied.id, original.id)
    self.assertEqual((copied.owner_id, copied.visibility, copied.original_author),
                     (self.user_b.id, 'hidden', '原作者'))
```

### 示例6：用户实验配置与引用匹配

```python
def test_name_match_requires_confirmation(self):
    pool = self.make_public_pool(name='示例')
    result = resolve_pool_reference(self.user, {'id': str(uuid4()), 'name': '示例'})
    self.assertEqual(result['status'], 'confirm')
    self.assertEqual(result['candidates'][0]['id'], str(pool.id))
```

### 示例7：任务归属、限额与历史持久化

```python
def test_busy_does_not_disclose_other_owner(self):
    self.start_job_as(self.user_a)
    self.client.force_login(self.user_b)
    body = self.client.get('/api/v1/jobs/busy/').json()
    self.assertEqual(body, {'busy': True})
```

### 示例8：账号删除与竞争处理

```python
def test_delete_preserves_system_pool(self):
    pool = self.make_public_pool(author=self.target.username)
    delete_account(self.admin, self.target.id)
    pool.refresh_from_db()
    self.assertIsNone(pool.owner_id)
    self.assertEqual(pool.original_author, self.original_username)
```

### 示例9：认证下载与大文件

```python
def test_revocation_stops_stream(self):
    response = self.open_large_download(self.user)
    stream = iter(response.streaming_content)
    next(stream)
    self.disable_user(self.user)
    with self.assertRaises((StopIteration, PermissionError)):
        next(stream)
    response.close()
```

### 示例10：React基础、API客户端与登录

```typescript
it('未登录响应使用统一错误码', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
    JSON.stringify({error:{code:'unauthenticated',message:'请重新登录',fields:{}}}),
    {status:401, headers:{'Content-Type':'application/json'}})));
  await expect(apiRequest('/auth/me/', {}, undefined))
    .rejects.toMatchObject({code:'unauthenticated'});
  vi.unstubAllGlobals();
});
```

### 示例11：角色池与新建实验页面

```typescript
it('种子保持十进制精度', () => {
  const seed = '900719925474099312345';
  expect(JSON.parse(JSON.stringify({seed})).seed).toBe(seed);
});
```

### 示例12：结果、历史、图表与下载交互

```typescript
it('空星级选择不回退全选', () => {
  const selected: number[] = [];
  expect([4,5,6].filter(r => selected.includes(r))).toEqual([]);
});
```

### 示例13：管理员页面和完整账号流程

```python
def test_regular_user_cannot_manage_accounts(self):
    self.client.force_login(self.user)
    r = self.client.get('/api/v1/management/users/')
    self.assertEqual(r.status_code, 403)
```
