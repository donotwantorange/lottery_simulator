# 多轮 Trace 与界面重组实施计划

> **For agentic workers:** 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务执行；每项验收通过后继续。

**Goal:** 支持仅开启Trace时保存多轮逐抽结果，提供分页、按抽次分析，并重组实验界面。

**Architecture:** 保持单抽核心与随机顺序；simulate通过sink输出记录，worker分批写任务暂存库，完成后事务导入历史v4。网页将配置、结果、历史分开，明细按需查询。

**Tech Stack:** Python、标准库sqlite3/dataclasses/unittest、现有Streamlit/pandas，不新增依赖。

**Spec:** [详细设计](2026-09-18-multi-trial-trace-ui-design.md)。用户已确认网页Trace100万条、单次下载1万条。✅ 任务1～12及最终审查修复完成，最终全套385项通过；独立Luna复审Approved。2026-09-22已本地合并到`master`，合并后主目录全套385项再次通过。⚠️未在线推送，真实浏览器、现场部署、容量与实际切换清理未完成，详见[实施记录](2026-09-20-multi-trial-trace-ui.md)和[本地合并记录](2026-09-22-multi-trial-trace-ui-local-merge.md)。

## 全局约束

- 项目 `/home/qykj/202607/test/lottery_simulator`；解释器 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python`。执行时工作目录为隔离工作树，不能假定工作树有.venv。
- 先读取项目实际状态及相关指令，保留现有未提交文档。只读建立基线后再实施；不自动提交、合并、推送或提前删除用户旧数据。
- rule_version字符串2.0；配置1、sampling1；记录/结果/任务2；历史数据库4；暂存格式/JSONL格式1。整数版本拒绝bool和缺失值。sampling1必须以随机序列不变为证据。
- 每次模拟只初始化一次rng，跨轮推进；每轮独立保底及赠送状态。Trace关闭不创建记录，sink和查询不消费随机数。
- 默认Trace关闭；网页总实际记录上限1,000,000，下载10,000；写批次1000；页大小50/100/200，默认100；位置图默认200、最多1000个连续位置。
- 不迁移旧历史，不给旧记录补轮次。保持认证、单活动任务锁、UUID路径及进程归属校验。
- 首版无部分结果分析、断点恢复、多任务并发、四五星编辑表、四五星角色批量统计、服务器实测或性能框架。
- 先测试目标行为，再最小实现；验证按风险选择，已有测试只更新新契约，保留原业务断言。每任务记录命令、退出码及验证边界，不重复无变化的全量测试，不做SHA验证。
- 本计划中的测试命令统一前缀为上述绝对解释器，例如 `PY -m unittest tests.test_engine -v` 中PY必须展开为绝对路径，不能使用工作树相对.venv。

## 文件职责与依赖

| 文件 | 职责 |
|---|---|
| lottery_simulator/formats.py、engine.py | 版本、多轮记录与sink |
| rules/base.py、first_thirty_bonus.py | 纯赠送数量预估及接口 |
| 新 dashboard/limits.py | 集中读取限制，不进入随机规则 |
| 新 dashboard/trace_store.py | 记录校验、暂存写入、TraceReader共用分页/聚合 |
| dashboard/repository.py | v4历史、事务导入、删除和备份 |
| dashboard/models.py、jobs.py、worker.py | 任务准入、保存阶段、恢复、结果引用 |
| 新 dashboard/trace_export.py、cli.py | JSONL导出和CLI路由 |
| 新 dashboard/views/new_experiment.py | 草稿、参数、规则预览、启动 |
| app.py、views/simulation.py、views/history.py | 导航、结果四视图、历史列表及汇总比较 |
| charts.py、trace.py | 位置统计图和中文轮次列 |
| 部署文件与当前使用手册 | v4路径、限制、备份与操作说明 |

任务顺序：1→2→3→4→5→6→7→8→9→10→11→12。每项独立审查；不得并行修改共享文件。1～7结束前只声明模块验收，界面全链路在8～12验证。

## 任务1：集中限制与赠送数量预估

**Files:** 新dashboard/limits.py、rules/base.py、rules/first_thirty_bonus.py；新tests/test_limits.py、tests/test_bonus_rule.py。

**Produces:**

```python
@dataclass(frozen=True)
class TraceLimits:
    max_records: int = 1_000_000
    max_download_records: int = 10_000
    batch_size: int = 1000
    @classmethod
    def from_env(cls): ...

# LotterySubRule新增方法；FirstThirtyBonusRule实现
def expected_draws(self, initial_main_draws: int, draws: int) -> int: ...
def expected_bonus_draws(rule, initial_main_draws: int, draws: int) -> int: ...
```

- [x] 测试H=29/D=1→10，H=30/D=1→0，H=0/D=29→0，H=0/D=30→10，无子规则→0；初值/抽数非法拒绝。
- [x] limits只从 `LOTTERY_MAX_TRACE_RECORDS`、`LOTTERY_MAX_TRACE_DOWNLOAD_RECORDS` 读取正整数字符串，未设用默认，空串/负数/小数拒绝。批次为集中常量，不新增无需求配置选项。
- [x] 赠送预估复用子规则的触发位置和事件参数，避免复制30/10常量；未知预估能力明确ValueError。网页/worker后续共用，核心非Trace不因此强制预估。
- [x] 运行 `PY -m unittest tests.test_limits tests.test_bonus_rule -v`。容量测试仅算整数，不为边界测试实际生成百万记录。

## 任务2：多轮记录和sink

**Files:** engine.py、formats.py、tests/test_engine.py、tests/test_formats.py、tests/test_bonus_rule.py。

**Produces:** DrawRecord新增trial_index；SimulationResult新增trace_enabled/record_count；simulate尾部新增record_sink=None，旧参数顺序不变。record/result/job常量2、database4，新增暂存/导出格式1常量。

- [x] 失败测试：3轮、D=2/H=29，36条记录，轮次1/2/3各12条，来源各1主+10赠送+1主，draw_index各1～12，main累计30/31，赠送主状态不变。
- [x] 移除单轮限制，抽样代码不变，用同一输出路径处理主池/赠送记录：

```python
if collect_records:
    record_count += 1
    if record_sink is None:
        records.append(record)
    else:
        record_sink(record)
```

- [x] record只在分支内构造；False配sink拒绝。sink模式records空tuple；赠送source_index使用本轮累计赠送序号，不能按每个event重置。
- [x] 测试内存与sink记录逐条一致，关闭/开启汇总一致（排除trace_enabled/record_count/records这三个有意不同字段）；sink抛错不返回成功。受控rng验证跨轮推进，不用“随机两轮碰巧不同”作断言。
- [x] 运行 `PY -m unittest tests.test_engine tests.test_bonus_rule tests.test_formats -v`；后续消费者版本暂未接入须在记录中注明，不加旧兼容。

## 任务3：暂存库及记录完整性

**Files:** 新dashboard/trace_store.py、新tests/test_trace_store.py；从repository.py迁出记录校验公共逻辑，同步tests/test_repository.py相关引用。

**Produces:**

```python
class TraceWriter:
    def __init__(self, path, *, limits: TraceLimits): ...
    def append(self, record: DrawRecord) -> None: ...
    def finish(self, *, trials: int, draws: int,
               initial_main_draws: int, bonus_per_trial: int) -> None: ...
    def close(self) -> None: ...
def validate_record(record: dict) -> None: ...
```

- [x] 暂存表records含trial_index/draw_index/source/source_index/rarity/character_name/record_json；复合主键(trial_index,draw_index)。单行metadata含format_version、complete、record_count以及finish的四个参数；创建时complete=0。
- [x] append校验record2、所有原嵌套字段、新轮次与整数类型；查询列只能从JSON提取，不接受调用者提供两套不一致值。缓冲最多batch_size条，超max_records先拒绝再写入。
- [x] finish flush尾批，按有序cursor验证轮次1～T、每轮draw_index连续、main/bonus来源序号连续、主抽数D、赠送数B、main累计=H+已见main数，以及主/赠状态语义；不把全表加载内存。成功才complete=1。
- [x] 测试批次2写5条尾部不丢、重复/缺号/缺轮/非法状态拒绝、上限前后、写失败complete仍0，关闭释放连接。SQL CHECK和JSON校验并用，防止bool冒充整数。
- [x] 运行 `PY -m unittest tests.test_trace_store -v`。

## 任务4：历史v4与完整事务导入

**Files:** repository.py、models.py的result_payload、tests/test_repository.py、tests/test_dashboard_models.py、tests/test_deployment_files.py现有fixture。

**Produces:**

```python
def save_run(self, run_id: str, payload: dict, *, trace_path=None,
             cancel_check=None, commit_guard=None) -> str: ...
def get_run(self, id: str) -> dict | None: ...  # 只读汇总
```

- [x] v4运行表增加record_count，记录主键(run_id,trial_index,draw_index)，增加设计指定位置索引；保留级联、seed文本保存和旧库只读拒绝机制。
- [x] result_payload始终排除records，保留trace_enabled/record_count与result2/environment；analyze无随机信息仍保持独立。
- [x] save_run只接受UUID run_id；trace开启要求暂存complete且元数据/配置/数量匹配；关闭要求count0且无暂存路径。单事务插入汇总并fetchmany分批导入，每条重新验证查询列与JSON一致。
- [x] 相同ID重复保存：比较完整持久化汇总/配置/记录数，不同快照报错；相同已完整结果返回原ID，不重复插入。数据库版本检查不因文件名而省略。
- [x] 导入每批检查取消，提交前进入commit_guard上下文并再次检查；无guard时用nullcontext。异常/取消全部rollback，guard作用域由任务6扩展包含最终state发布。
- [x] 故障注入第二批失败→运行和明细均不存在；正常3轮36记录、两次提交只一条历史；不同ID相同配置允许两次实验。get_run禁止include_records，原明细测试改用SQL读取或后续TraceReader，保留业务验证。
- [x] 运行 `PY -m unittest tests.test_repository tests.test_dashboard_models -v`。

## 任务5：共用分页与位置聚合

**Files:** trace_store.py、新tests/test_trace_queries.py、repository.py小型reader工厂。

**Produces:**

```python
@dataclass(frozen=True)
class TraceFilter:
    trial_from: int | None = None
    trial_to: int | None = None
    source: str | None = None
    rarity: int | None = None
    character_name: str | None = None
    unnamed_character: bool = False
    source_from: int | None = None
    source_to: int | None = None

class TraceReader:
    def query_records(self, filters, *, limit=100, offset=0) -> tuple[list[dict], int]: ...
    def iter_records(self, filters, *, batch_size=1000): ...
    def position_counts(self, *, source, trial_from, trial_to,
                        source_from, source_to) -> list[dict]: ...
```

- [x] reader绑定历史path/run_id或已完整暂存path；连接只读，源类型和表名由内部固定选项决定，不能用户字符串拼表名。每次读取检查版本和目标可用性。
- [x] filters正整数/bool/范围校验；角色筛选必须指定rarity，无名单用显式unnamed_character，禁止与name并用。构造SQL绑定参数，按轮次/轮内抽次排序。
- [x] query返回限定页和同条件count；iter用fetchmany；position_counts仅接受来源/轮次/位置范围，不接收rarity/角色过滤，连续范围最多1000。返回source_index、observations、four/five/six_count及对应rate，缺星级补0，空位置不造分母。
- [x] 人工夹具三轮第1主抽为4/5/6→三种count各1/rate各1/3；第2抽为4/4/5→2/1/0；第81位置正常展示；赠送独立。验证注入字符安全、同名不同星级、NULL筛选、页越界空页与正确总数。
- [x] 运行 `PY -m unittest tests.test_trace_queries tests.test_repository -v`。

## 任务6：任务准入、保存发布与恢复

**Files:** models.py、jobs.py、worker.py、tests/test_jobs.py、tests/test_dashboard_models.py；新增tests/test_trace_lifecycle.py。

**Produces:** JobState新增phase(simulating/saving)、history_saved(bool)、run_id(可空)；JobManager.get_trace_reader(job_id)；新任务根由调用方传入jobs_v4。

- [x] RunParameters删除单轮和主抽10万Trace限制；validate_parameters_for_active_rule使用TraceLimits和预估计算T×(D+B)，worker冷启动重新读取当前限制并验证；非Trace原上限不变。
- [x] worker Trace走sink，暂存finish后原子写result.json仅汇总。明确相同seed的参数快照保存实际生成seed；run_id=job_id。
- [x] 分清错误：计算/暂存失败→failed清半成品；历史写失败→completed/persistence_error、保留完整暂存；成功→history_saved、run_id、completed后清暂存。非Trace仍可在保存失败时查看汇总。
- [x] 采用worker提供的commit_guard：获得manager._locked，最后一次检查cancel，yield给repository执行commit，正常返回后在同一锁内发布completed state，再释放锁。state写失败发生在commit之后时不得误报为数据库已回滚；留待恢复按run_id识别。
- [x] cancel在锁内先看历史是否已有该ID，已有则返回已完成并修复state；否则写cancel.request。导入期间不持全程任务锁，保证取消能送达。测试锁顺序无数据库/任务锁反向死锁。
- [x] 最终修复后验证：restart仅处理合法版本新根，确认归属、SIGTERM并等待确认退出；reaper先wait，两者按固定job_id恢复已提交历史。未提交时清result/trace及实际伴随文件；无法确认退出或历史提交状态时保留active及文件，不放行新任务。无效版本不kill；PID非本任务进程不发送信号。
- [x] reader选择：history_saved为true只去历史，缺失返回失效；false且completed且暂存complete才允许暂存reader；运行中/失败不可读。get_result同步检查历史存在，防止删除后显示残留完整结果。
- [x] 按层验证：repository层覆盖批次取消、提交guard及事务回滚；worker/job层覆盖取消、保存失败暂存可读、删除不复活，并新增模拟commit已完成/state未发布后先reaper再restart、退出确认、权限拒绝、proc不可读与半成品清理。原restart案例不代表真实reaper链路，也不声称穷尽commit后state写失败和所有调度窗口；保留原认证/路径/并发/进程测试。
- [x] 运行 `PY -m unittest tests.test_jobs tests.test_dashboard_models tests.test_trace_lifecycle -v`。

## 任务7：多轮CLI及JSONL导出

**Files:** cli.py、新dashboard/trace_export.py、tests/test_cli.py、新tests/test_trace_export.py。

**Produces:** `iter_jsonl(metadata: dict, reader: TraceReader, filters: TraceFilter)` 返回逐行UTF8字符串；`export_trace(database, run_id, output)`本地导出入口。

- [x] simulate --trace移除单轮校验；text每行加轮次且保留双状态和触发列；JSON记录2，汇总trace_enabled/count，CLI内存模式附records。关闭不含records；帮助说明大记录内存与网页落库导出方式。
- [x] JSONL首行为type=metadata、export_format_version=1、run、filters、matched_record_count；后续为type=record、record完整对象。metadata不含records，不把当前页当作整个过滤集。
- [x] 新export-trace子命令参数按design，cli仅在该命令路径延迟导入应用导出模块，普通核心导入无Streamlit依赖。数据库只读，运行不存在/无Trace/版本错明确失败。
- [x] 输出同目录临时文件分批写/fsync；使用os.link(temp,target)原子发布且目标存在即失败，再unlink自己的临时文件，避免“先exists再replace”竞争覆盖。拒绝目标为源库/伴随文件，失败保留原目标。
- [x] 网页入口共用JSONL生成器但先count≤max_download_records再生成；不限制CLI全量导出。测试超限用小limits，不生成万条以验证常量。
- [x] 运行 `PY -m unittest tests.test_cli tests.test_trace_export -v`；真实CLI三轮36记录往返解析，模拟与export互不消费rng。

## 任务8：三页面导航与新建实验

**Files:** app.py、新views/new_experiment.py、views/configuration.py、views/history.py的复用入口；tests/test_dashboard_app.py、tests/test_configuration_view.py。

- [x] app认证与初始化一次后，侧栏导航“新建实验/实验结果/历史记录”，使用radio/selectbox分支只执行当前页；默认新建实验。默认history_v4/jobs_v4，覆盖路径依旧优先。
- [x] 移出app参数表到new_experiment，保留原中文初始保底名称；Trace多轮可用，默认false；奖池编辑器与主池规则预览放主区；启动前显示每轮及实验总抽数/Trace预估。
- [x] 草稿使用独立持久session键，widget临时键与草稿通过回调同步，防止Streamlit未渲染控件自动清理；编辑器仍保留稳定baseline。禁止用每次渲染回填旧值覆盖刚输入的值。
- [x] selected_result=(kind,id)与current_job_id分离；新任务开始才主动选它并跳结果页，轮询不覆盖已选历史。运行中草稿可改，开始按钮禁用。
- [x] AppTest三页往返参数不丢、连续单元格修改一次生效、轮数3启用Trace、25,000×40预估百万、超限启动前拒绝；无身份时不访问库；指定读取默认只在临时目录。
- [x] 运行 `PY -m unittest tests.test_dashboard_app tests.test_configuration_view -v`。

## 任务9：结果四视图与分页明细

**Files:** views/simulation.py、trace.py、新views/trace_details.py、charts.py；tests/test_simulation_view.py、tests/test_trace_view.py、新tests/test_trace_details.py。

- [x] render_result接收汇总payload与可空TraceReader，不访问payload.records；分支选择“实验概览/分类统计/按抽次分析/逐抽明细”，只有当前分支执行查询。
- [x] 概览列每轮及全实验抽数，保持理论期望/均值口径；规则曲线已移新建页。分类统计五个二级选项和主/赠/总来源选择，复用现有图表函数不丢原业务图。
- [x] trace_rows加入“轮次/轮内总抽次”，现有字段映射不丢。默认第1轮/全部来源，可指定任意单轮、连续轮次范围或全部轮次；筛选沿用TraceFilter，变更先重置page，删除导致空页回合法页。最终AppTest验证单次点击立即显示正确上/下一页。
- [x] 明细查询一页；基础/完整列切换仅隐藏展示列。准备下载按钮先查上限，生成有限JSONL；owner绑定选中(kind,id)，换运行/筛选清缓存，普通翻页不重新导出。最终AppTest验证不同当前任务seed42→77的缓存归属。
- [x] 位置图默认1～min(200,实际来源抽数)，main/bonus单独；起点可到实际来源末尾，限制连续宽度≤1000而非绝对位置≤1000。最终AppTest验证201及1001～1100；count/rate切换，图表共用SQL聚合；无Trace时提示且不读reader。
- [x] 测试reader替身记录真实入口调用边界，聚合正确性由任务5真实SQL测试承担；概览不读明细，过滤后下载包含全部匹配而非单页。
- [x] 运行 `PY -m unittest tests.test_simulation_view tests.test_trace_view tests.test_trace_details tests.test_charts -v`。

## 任务10：历史查询、复用与删除联动

**Files:** views/history.py、app.py、tests/test_dashboard_app.py、新tests/test_history_navigation.py。

- [x] 历史列表保持规则/Trace/UTC日期过滤、20条分页，显示历史总数及每条Trace记录数；单条跳结果页，展示参数/配置/版本快照和复用入口，不在列表直接全量展开明细。保存阶段显示“写入明细/保存历史”。
- [x] 复用回草稿，完整带配置、种子、初始状态、轮数和trace_enabled，删除旧 `and trials == 1`。未知规则安全拒绝；复用不自动启动任务。
- [x] 两条对比保留汇总/配置/分类，不实例化明细reader；统计口径不同明确提醒，不叠加误导图。
- [x] 删除二次确认后级联，清run选择、对应分页与下载缓存；当前job若指向已删run不得回退result文件。测试取消删除无变化、其他历史不受影响、分页回退。
- [x] 运行 `PY -m unittest tests.test_history_navigation tests.test_dashboard_app tests.test_repository -v`。

## 任务11：部署静态合同与操作文档

**Files:** Dockerfile、docker-compose.yml、deploy/lottery-backup.service、存在时.env.example；README.md、docs/local-usage.md、docs/dashboard-guide.md、docs/deployment.md；tests/test_deployment_files.py。

- [x] 所有实际默认路径改v4/jobs_v4，systemd源lottery_v4.sqlite3、目标lottery-v4-$(date +%%F).sqlite3，保持%%；不改认证、网络、卷或secrets。
- [x] 说明多轮Trace、源/轮内序号、数据量包含赠送、1百万/1万环境变量及重启生效、CLI内存与本地完整导出、三页面和四结果视图、保存失败暂存语义。
- [x] 备份只包含历史，暂存保存失败数据不在历史备份；恢复仅接受v4，旧库不迁移；避免宽泛删data/jobs命令。
- [x] 更新部署测试fixture为v4 API，运行 `PY -m unittest tests.test_deployment_files -v`；检查示例命令/help、本地链接、git diff --check。纯文档不新增镜像式测试。

## 任务12：整体验收、记录与切换交接

**Files:** 新docs/changes/2026-09-20-multi-trial-trace-ui.md；本plan与design状态；必要集成测试。

- [x] 临时数据目录真实JobManager→worker→暂存→历史→分页→位置聚合→导出：三轮36记录，配置含非空四五星；JSONL 1条metadata+36条record，汇总相等，删除后不可再查。
- [x] 初次任务12跑 `PY -m unittest discover -v`：原记录371项/96.462秒/退出0，原临时日志现已不可核验。修复阶段受影响9组149项/21.143秒/退出0，10项回退因果测试重现10个失败后恢复修复。最新最终全套 `PY -m unittest discover -q`：385项/104.670秒/退出0；独立Luna复审I1～I7/M1～M2全部关闭，Approved、无阻断项。
- [x] 真实CLI analyze、simulate --draws 2 --trials 3 --initial-pity 29 --seed 42 --trace --format json、非Trace对照、本地export-trace验证；所有数据库用临时目录。
- [x] 真浏览器导航、草稿、三轮Trace、位置图81抽、明细筛选、下载、复用/删除验收；浏览器不可用明确标未验，AppTest与启动健康检查分别记录。⚠️实际浏览器工具不可用，此项仅完成不可用回退记录；真实浏览器交互和视觉仍未验。
- [x] 独立整体验证无旧include_records全量页面路径、无旧单轮限制、无旧目录默认；非Trace不创建暂存库和records；sampling1随机序列对照通过。禁止把旧字段文字历史记录误删。
- [x] 更新docs/changes记录实际功能、验证、限制及待现场步骤。保留既有用户文档改动；实施结束不自动提交/合并/推送。
- [x] 只读盘点旧v1/v2/v3数据库和旧任务，列出确切路径/版本/归属/备份情况。尚未实际合并切换时到此为止，记录“未删除”。实际3库、8任务及2个锁文件均保留；项目内未发现实际备份，外部未核实。
- [ ] 用户授权实际切换后：确认网页/worker归属并停止，逐个删除已确认旧库/伴随文件与旧任务参数/状态/结果/取消标记，保留日志/配置/备份；清session并启动v4小实验验证。没有实际切换授权不勾此项完成。

## 设计覆盖自审与交接

| 设计章节 | 对应任务 |
|---|---|
| 3～4 记录/随机性 | 2 |
| 5 容量/配置 | 1、6、8 |
| 6 暂存/事务/恢复 | 3、4、6 |
| 7 数据库/分页 | 4、5 |
| 8 位置统计 | 5、9 |
| 9 布局/草稿/历史 | 8、9、10 |
| 10 CLI/导出 | 7、9 |
| 11 版本/切换 | 2、6、11、12 |
| 12 验收 | 各任务指定组及12 |

关键依赖已明确：任务4定义提交guard接口，任务6实现锁内状态发布；任务5统一两个数据源查询，任务9只依赖reader；任务7导出与任务9共用JSONL格式；任务1集中限制由6/8/9读取。分页默认第1轮属于UI，reader默认无轮次过滤；位置比例不继承明细星级筛选。

✅ 最终审查的7项Important及2项Minor已修复；最终全套385项通过，独立Luna复审Approved、无阻断项。2026-09-22已本地合并到`master`，合并后385项再次通过；未在线推送。任务12报告及[实施记录](2026-09-20-multi-trial-trace-ui.md)保留各阶段证据。⚠️真实浏览器、现场部署、容量与实际切换仍待验证；最后清理项未勾选，旧数据未删除。
