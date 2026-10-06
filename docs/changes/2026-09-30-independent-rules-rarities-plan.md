# 独立规则、通用稀有度与网页说明实施计划

> **执行要求：** 按任务顺序串行推进，先读设计及相关调用路径，再实施并记录证据；步骤以复选框跟踪。仅在用户明确选择子代理分工后使用当前环境的子代理工具。本计划不依赖Superpowers技能，不能把编写计划、修改代码或隔离检查当作完整验收。

**Goal（目标）：** 实现独立规则管理、通用稀有度、配置化zmd机制及清晰网页，保留账号并切换到不兼容旧业务格式的v6。

**Architecture（架构）：** 保留React＋Django和全站单模拟任务。纯Python规则计算、随机执行、理论递推与事件流使用统一契约；网页服务冻结规则和池快照，v6库保存汇总及可选过程事件。规则参数可更新，已被引用的稀有度结构只能复制修改。

**Tech Stack（技术）：** 沿用当前Python、Django/DRF、SQLite、React/TypeScript/Vite、Altair/Vega、Docker Compose/Caddy；不顺带升级依赖或增加队列、脚本编辑器、性能框架。

**Spec（设计依据）：** [完整设计](2026-09-30-independent-rules-rarities-design.md)，执行者必须先完整阅读，再读本计划及所执行任务。

## 1. 状态与执行边界

- 2026-09-30：设计经用户确认进入计划阶段；本计划待审阅，任务1—17均未开始。
- 2026-10-01审查时：按当前Windows＋WSL环境完成定向审查与文档整理，任务1—17未开始；初版设计/计划已纳入master `a0b575f`，本次整理尚未提交。
- 2026-10-01执行进度：任务1—16已完成、集中验收通过；任务17未执行，实际证据见实施记录。
- 2026-10-02最新进度：已合并本地master、切换v6并完成原账号小实验/历史/Trace验收；任务17旧材料清理未执行。最近修复`9832bc0`后完整后端244项、前端52项及构建通过，8组性能全部完成；定向回归确认的新问题待修复，详见实施记录末节。
- 2026-10-01审查阶段只核对文档、运行环境及只读/内存示例，当时没有产品实现、产品测试、安装、部署、数据删除、提交或推送。后续实施与测试按上面的日期和实施记录区分。
- 审查开始时Windows Git工作区干净；执行前重新核对并保护当时已有修改，不使用reset/checkout覆盖。本次文档整理属于待保留的工作。
- 计划按顺序执行；到某任务暂停时，只汇报其实际完成程度，未验收部分明确标注。
- 写测试与执行测试分开：各任务补充对应用例，但不在每个步骤反复运行。任务16集中执行必要功能验证；遇到阻塞接口错误才运行该范围的最小检查。不开SHA、无关性能基准或重复全套检查。
- 本地真实数据切换在任务17，且必须等用户明确要求执行该任务/本地切换。服务器升级只提供接口与文档，不自动连接或修改当前服务器。
- 不自动提交、合并或推送；用户要求本地集成时，再按任务17核对目标和权限。此计划不是在线发布授权。
- 各任务完成后在本计划勾选步骤；第一次产品实现时创建同主题实施记录，记录证据、未验范围和Git状态。

### 1.1 当前电脑的执行起点

项目来源为[donotwantorange/lottery_simulator](https://github.com/donotwantorange/lottery_simulator)，已核对与本地origin一致。2026-10-01本机WSL环境、具体路径、启动命令、数据摘要及Git换行差异单独维护在[Windows＋WSL临时说明](../windows-wsl-temporary.md)；仓库原有README和本地使用手册保持原文。

- 后端、worker和Linux专用检查在WSL执行，复用临时说明中的解释器；无需为本轮升级现有依赖。
- 主检出使用Windows Git；WSL只读查看采用临时说明中的命令级换行配置，不批量转换主检出或修改Git全局配置。
- 当前Shell脚本存在CRLF语法问题，任务1准备LF隔离工作树并记录实际目录/分支；不把准备工作树当作安装或真实数据切换。
- 隔离工作树复用现有Python；前端依赖缺失时在Linux文件系统按锁文件准备，记录实际链接或安装位置，不提交node_modules，也不自动复制主项目data。
- 任务17前明确本机v5库或旧Ubuntu备份作为账号来源；不能把当前本机1个账号当作完整旧账号集合。

## 2. 全局约束

1. 规则、池、实验、历史分别管理；实验只能通过池选规则，任务接受时冻结两类快照与目标。
2. 公共池只绑定公共规则；公开私有池只绑定公共或公开私有规则；隐藏池按池所有者权限绑定。公开不授予编辑权限。
3. 被引用规则不能删除或原地改稀有度结构。共享参数修改校验全部引用池并原子保存，不泄露隐藏引用内容。
4. 稀有度和角色均用稳定ID。稀有度按rank排序，角色抽样按冻结名单顺序，不按名称推导身份或等级。
5. 基础概率合计1，绝对尾差容忍`1e-12`；软保底从高到低处理，增量优先扣更低档中的最低档。
6. 小保底满足“该档或更高”；大保底目标必须最高档UP。赠送池和直接赠送不改变任何主池保底。
7. zmd默认：65抽六星0.8%，66抽5.8%，79抽70.8%，80抽100%；五星10主抽或以上保底；120主抽指定第一个UP，首次主池获得后本轮关闭；30主抽独立赠送10抽一次；每240主抽直接给默认第一个UP一个、不算抽、不发奖励、不消费RNG。
8. 每档可启用UP分组，所有角色有权重；UP必须限定。关闭分组只取消概率分组，不删除UP标记。
9. 初始累计主抽、各档小保底和大保底状态分开；旧初始条件的目标/模式/结构变化须重新确认，不能静默清零或截断。
10. Trace仅开启时保存draw和character_grant事件；100万上限和1万下载上限按事件条数，管理员免业务数量限额，不免类型、存储及权限检查。
11. 保留账号，清旧业务，不兼容旧格式。新路径为`history_v6.sqlite3`、`jobs_v6/`、`exports_v6/`。迁移只能由Django管理。
12. 版本固定为：规则文件1、池3、实验2、结果4、事件3、抽样2、任务4、库6、临时Trace2、导出2；算法`rule_version`为字符串`3.0`，整数版本拒绝bool。
13. 用中文标签、错误及说明；网页概率显示百分比，增幅显示百分点；重要说明不能仅依赖hover。
14. 保持现有账号保护、单任务锁、提交丢响应找回、取消协议、下载撤权和原子保存；不恢复旧Streamlit入口。

## 3. 任务顺序与阶段可运行性

| 任务 | 交付 | 主要依赖 | 难度 |
|---|---|---|---|
| 1 | 纯配置契约、默认文档与测试夹具 | 设计 | 中 |
| 2 | 通用概率、目标解析和保底状态 | 1 | 高 |
| 3 | 模拟、两类事件与计数汇总 | 2 | 高 |
| 4 | 有限理论与主抽等待分析 | 2、3 | 高 |
| 5 | 中文CLI及新文件入口 | 1—4 | 中 |
| 6 | v6模型、迁移与默认初始化 | 1 | 中高 |
| 7 | 独立规则服务与权限 | 6 | 中高 |
| 8 | 池、实验、初始上下文服务 | 2、6、7 | 高 |
| 9 | 事件Trace、历史仓库与导出 | 3、6 | 中高 |
| 10 | worker、任务与API完整连通 | 4、7—9 | 高 |
| 11 | 规则管理网页 | 10 | 中 |
| 12 | 通用池编辑网页 | 10、11 | 中 |
| 13 | 新建实验及初始条件网页 | 10、12 | 中高 |
| 14 | 结果、历史、图表与过程明细网页 | 9、10、13 | 中高 |
| 15 | 保留账号工具与部署/备份接口 | 6、10、14 | 中高 |
| 16 | 集中验收、旧入口清理与操作文档 | 1—15 | 高 |
| 17 | 经明确授权的本地集成和真实切换 | 16 | 高风险操作 |

- 任务1—4：仅纯Python配置/核心入口可用于必要诊断；任务3提供内部纯模拟循环，任务4才组合完整理论结果。网页尚未升级，不启动新网页服务。
- 任务5后：新CLI的analyze/simulate可用；它们不写网页历史，也不读取真实账号库。export-trace待任务9的v6仓库及流式导出连通后才可用，只读访问明确指定的历史库。
- 任务6—9：只使用显式临时v6路径核对Django接口；worker/API尚未完整连通，不让旧网页指向新库，也不让新代码指向真实v5库。
- 任务10后：可在临时v6库运行完整后端流程；旧React不可作为新契约验收工具。
- 任务14后：可启动新前后端配临时v6数据，准备集中验收。
- 任务15只写工具及接口，不迁入本机或服务器真实账号。任务16先在隔离数据集中验收，任务17才允许真实本地切换。
- 开始实现时使用隔离工作树/分支，检查已有附件并复用合适工作树；不用无关旧功能工作树。计划编写阶段不创建工作树。

## 4. 文件责任图

| 文件/目录 | 本轮职责 | 任务 |
|---|---|---|
| `lottery_simulator/rules/definitions.py`（新） | 规则、稀有度、池、角色、奖励的纯类型 | 1 |
| `lottery_simulator/config_documents.py`、`formats.py` | 严格文件契约、版本与ID/名称解析 | 1、5 |
| `configs/rules/zmd.json`（新）、池/实验默认JSON | 唯一默认数据来源 | 1 |
| `lottery_simulator/rules/runtime.py`（新） | 编译池、目标、小/大保底、两个概率计算器、状态推进 | 2 |
| `lottery_simulator/events.py`、`results.py`（新）、`engine.py` | 计数计划、draw/grant事件、模拟、汇总与纯序列化 | 3、4 |
| `lottery_simulator/analysis.py`、`waiting_analysis.py`（新） | 有限状态递推与等待分析 | 4 |
| `lottery_simulator/cli.py` | 新配置中文CLI | 5 |
| `dashboard/models.py`、迁移、初始化命令 | v6 schema、规则外键、通用事件 | 6 |
| `dashboard/services/rules.py`（新）、池/实验/账号服务 | 授权、引用、修订和上下文 | 7、8 |
| `dashboard/trace_store.py`、`trace_export.py`、`repository.py` | 流式过程事件、聚合、历史与导出 | 9 |
| `dashboard/job_models.py`、`jobs.py`、`worker.py`、API | 快照、单任务、进度、取消、网页契约 | 10 |
| `frontend/src/api/types.ts`、`client.ts` | 共享API类型与请求 | 10—14 |
| Rules/RuleEditor（新）、Pools/PoolEditor | 规则与池界面 | 11、12 |
| NewExperiment/ExperimentForm | 参数、上下文与预览 | 13 |
| Results/History/ChartPanel/TraceTable | 通用结果与过程展示 | 14 |
| 保留账号命令、settings、Compose、install、backup、deploy | v6切换工具与部署接口 | 15 |
| README、三份操作手册、修改台账 | 当前功能说明和最终证据 | 16、17 |

旧`rules/rule_1.py`、`first_thirty_bonus.py`和固定`pool_config.py`只在调用方全替换后删除，不保留兼容实现。对应测试迁移到新契约，不能通过删除有效用例降低覆盖。

## 5. 跨任务接口字典

以下名称在后续任务固定使用；如确需改名，先同步本节及所有调用方，不允许相邻任务各自发明字段。

```python
# definitions.py：冻结类型，均提供from_dict()/to_dict()
RarityDefinition(id, name, rank, base_probability,
                 soft_enabled, soft_start, soft_step, hard_enabled, hard_pity)
BigPityPolicy(enabled, hard_pity, target, after_obtain)
BonusPolicy(enabled, at_main_draw, draws, rarities)
GrantPolicy(enabled, period, quantity, target)
RuleDefinition(id, name, original_author, algorithm, rarities, big_pity, bonus, grant)
CharacterDefinition(id, rarity_id, name, weight, is_up, is_limited)
RarityPool(rarity_id, characters, up_enabled, up_share)
RewardDefinition(id, name, amounts)  # amounts: dict[rarity_id, float]
PoolDefinition(id, name, original_author, rule_ref, rarity_pools,
               rarity_labels, rewards, mechanism_targets)
BigInitial(target_obtained, misses)
ExperimentParameters(draws, trials, seed, trace, initial_main_draws,
                     initial_small_pity, initial_big_pity)
InitialContext(rule_id, rarity_ids, big_mode, big_target_id)

# runtime.py：均不消费随机数
CompiledPool(rule, pool, targets)  # targets键固定big_pity、periodic_grant
DrawState(small_pity, big_misses, big_active)
compile_pool(rule: RuleDefinition, pool: PoolDefinition) -> CompiledPool
normalize_parameters(compiled: CompiledPool, raw: dict) -> ExperimentParameters
initial_context(compiled: CompiledPool) -> InitialContext
initial_state(compiled: CompiledPool, parameters: ExperimentParameters) -> DrawState
rarity_probabilities(compiled: CompiledPool, state: DrawState) -> dict[str, float]
character_probabilities(compiled: CompiledPool, rarity_id: str,
                        state: DrawState) -> dict[str, float]
pity_status(compiled: CompiledPool, state: DrawState) -> dict
advance_state(compiled: CompiledPool, state: DrawState,
              rarity_id: str, character_id: str | None) -> DrawState
transition_branches(compiled: CompiledPool, state: DrawState) -> tuple
# 每个分支：(rarity_id, character_id或None, 联合概率, after_state)

# events.py：纯计数，无RNG、无数据库
EventCounts(main_draws, bonus_draws, total_draws, grant_triggers,
            granted_characters, trace_events)
event_counts(rule: RuleDefinition, parameters: ExperimentParameters) -> EventCounts

# engine.py：结果类型与顺序由任务3落实
DrawOutcome(rarity_id, character_id, character_name, is_up, is_limited,
            rewards, pity_status)
DrawResult(outcome, probabilities, character_probability, state_before, state_after)
ProcessEvent(event_format_version, trial_index, event_index, event_type,
             main_draws_completed, mechanism_id, draw_index, source, source_index,
             draw_result, main_state_before, main_state_after, grant)
SimulationResult(seed, parameters, counts, simulation, theoretical,
                 trace_enabled, event_count, records)
draw_once(compiled: CompiledPool, state: DrawState, rng) -> DrawResult
simulate_draws(compiled: CompiledPool, parameters: ExperimentParameters, *,
               record_sink=None, progress_callback=None, phase_callback=None,
               cancel_check=None) -> SimulationResult
# simulate_draws是任务3内部交付，theoretical=None，不作为网页/CLI完整结果输出。
simulate(compiled: CompiledPool, parameters: ExperimentParameters, *,
         record_sink=None, progress_callback=None, phase_callback=None,
         cancel_check=None) -> SimulationResult
simulation_payload(result: SimulationResult, compiled: CompiledPool,
                   duration_seconds: float, include_events: bool = False) -> dict
# results.py；完整序列化要求theoretical非None，网页不内嵌事件，CLI可显式包含。

# analysis.py / waiting_analysis.py
expected_simulation_results(compiled: CompiledPool, parameters: ExperimentParameters,
                            *, cancel_check=None) -> dict
waiting_time_stats(compiled: CompiledPool, parameters: ExperimentParameters,
                   target_rarity_id: str | None = None, *, cancel_check=None) -> dict
```

JSON大整数的字符串转换只发生在API边界，不改变内核整数类型。纯类型不能导入Django；任务快照不能用当前数据库对象代替`RuleDefinition/PoolDefinition`。

DrawState必须可哈希：构造时接受ID→计数映射，内部规范化为排序的不可变键值元组，to_dict再输出JSON对象。理论用它作状态键，不能用带可变dict的frozen dataclass直接作dict键，也不能让缓存修改模拟记录的状态。

统计dict统一为`draws`（main/bonus/total）、`grants`、`acquisitions`三个区域；各区域角色用ID，奖励用奖励ID，分类在每个稀有度下使用up/other_limited/standard/unnamed。每个draw区域包含draw_count、rarity_counts、character_counts、category_counts、reward_totals、pity_triggers及每轮分布/至少一次指标；grant区域不包含抽取概率或奖励。simulation为计数/分布，theoretical为相同口径的期望/概率，不用相同数值字段冒充两种含义。

## 6. 审查重点

以下隐蔽问题必须有归属用例，不以文档沉默为许可：

1. 共享规则新参数使其他所有者隐藏池失效：全部修改回滚，错误不泄露隐藏内容。任务7。
2. 名单重排令初始“已获UP-A”变成“已获UP-B”：阻止静默沿用，不因重跑确认而跳过合法性检查。任务8、13。
3. 一次直接赠送数量2：只产生一条事件，既不增抽数，也不消费RNG。任务3、9、14。
4. 理论压缩计数污染Trace，或首次大保底已结束仍承诺120：真实计数/等待边界正确。任务2、4。
5. v5有删除中账号、源目标同文件、误给v5做v6迁移：停止且不改变源账号/业务。任务6、15。
6. 旧逐抽表触发器悬空，或新表删除行为退化：完整空库迁移及删除用例覆盖。任务6、9。
7. 总数/序号正确但赠送位置、目标或每次数量错误：用冻结规则校验Trace，不从事件自身推导预期条件。任务9、10。

---

## 任务1：纯配置契约、版本和默认文档

**文件：** 新建`lottery_simulator/rules/definitions.py`、`configs/rules/zmd.json`、`tests/fixtures_rules.py`；修改`config_documents.py`、`formats.py`、`configs/pools/default.json`、`configs/experiments/default.json`、`tests/test_config_documents.py`、`test_formats.py`；新建`tests/test_rule_definitions.py`。

**接口：** 消费设计第3—8、12.3章；产出第5节全部纯配置类型及`load_rule_document(raw)`、`load_pool_document(raw)`、`load_experiment_document(raw)`，分别返回定义或实验文档；`ExperimentDocument`含name、pool_ref、parameters、initial_context。

- [x] 检查工作区/工作树，保留已有修改；按第1.1节准备WSL可用、Shell脚本为LF的隔离工作树，记录其Windows/WSL实际目录及Git执行方式，后续命令不得回到真实数据目录。复用现有Python，核对前端依赖位置；不自动复制本机账号库。
- [x] 用冻结dataclass实现配置类型和严格JSON加载，拒绝未知字段、重复键、bool整数、非有限概率/权重及旧版本。关闭机制字段保留合法草稿但不参与执行；枚举只允许设计给出的模式/选择方式。
- [x] 定义`RULE_FORMAT_VERSION=1`、`POOL_FORMAT_VERSION=3`、`EXPERIMENT_FORMAT_VERSION=2`、`EVENT_FORMAT_VERSION=3`及全局版本值；新代码不用旧CONFIG/RECORD常量表达新契约，旧调用方在各自任务替换。
- [x] 创建唯一默认zmd规则/池/实验文件，ID一次生成并固定写入；池引用规则ID，实验引用池ID。四/五档可空名单，六星名单/奖励保持设计默认。先不删除旧文件以免中间阶段意外加载失败。
- [x] 建立公共测试夹具：`default_rule()`、`default_pool()`从新JSON加载；`default_parameters(**overrides)`构造全零初始参数；`make_default_compiled()`延迟导入任务2的compile_pool；`character_id(compiled,name)`按默认唯一名称返回ID。夹具不是产品默认代码。
- [x] 将以下断言写成unittest用例，并补旧格式/重复ID/重复rank/名称及非法权重用例，留到任务16执行：

```python
rule = default_rule()
assert rule.name == "zmd"
assert [r.name for r in sorted(rule.rarities, key=lambda r: r.rank)] == ["四星", "五星", "六星"]
assert abs(sum(r.base_probability for r in rule.rarities) - 1) <= 1e-12
assert rule.big_pity.after_obtain == "disable_after_obtain"
assert rule.grant.quantity == 1
```

**交付标准：** 默认文件、纯类型、序列化形状及测试夹具一致；本阶段不运行网页或创建数据库。

2026-10-01：任务1已实现；语法、默认加载与不可变JSON往返检查通过，unittest按计划留任务16集中执行，未标整体已验证。实际文件、证据及后续接口见[实施记录](2026-09-30-independent-rules-rarities.md#任务1纯配置契约版本和默认文件)。算法标识为dynamic_probability，三种文件的to_dict包含文件版本；参数和嵌套策略不重复版本。

## 任务2：通用概率计算、目标解析和状态推进

**文件：** 新建`rules/runtime.py`、`tests/test_dynamic_rules.py`；复用`probability.py`；修改`rules/base.py`、`rules/__init__.py`、测试夹具。

**接口：** 消费任务1类型；产出CompiledPool、DrawState及第5节全部runtime函数。`pity_status`固定返回soft_active、hard_active（稀有度ID列表）及big_forced（bool）。

- [x] compile_pool核对池的规则ID、稀有度映射、名称、角色ID/权重、奖励和启用的目标；`first_up`按高到低再名单顺序解析；大目标非最高档即中文错误。
- [x] 将参数纯类型校验和初始语义校验放到normalize_parameters；缺少当前档的零值可规范化，未知ID拒绝。首次模式misses输入为0、按H派生；循环模式target_obtained必须false；关闭大保底要求false/0。
- [x] 实现初始条件不可能历史校验及initial_context；未跟踪的档不能用0参与真实关系比较。
- [x] DrawState内部规范化不可变计数，保留to_dict/from_dict，advance_state每次返回新状态，不原地改输入；理论键与Trace序列化使用同一个定义。
- [x] 实现软保底向量、最低档扣减及最高硬保底下限，按以下次序；最终检查非负/有限/合计1，不按名称分支：

```python
p = {r.id: r.base_probability for r in compiled.rule.rarities}
misses_by_id = dict(state.small_pity)
for r in sorted(compiled.rule.rarities, key=lambda item: item.rank, reverse=True):
    position = misses_by_id.get(r.id, 0) + 1
    candidate = min(1.0, r.base_probability + r.soft_step * max(0, position-r.soft_start+1)) if r.soft_enabled else r.base_probability
    remaining = max(0.0, candidate-r.base_probability)
    lower = sorted((x for x in compiled.rule.rarities if x.rank < r.rank), key=lambda x: x.rank)
    for x in lower:
        taken = min(remaining, p[x.id])
        p[x.id] -= taken
        p[r.id] += taken
        remaining -= taken
# 再按pity_status选择最高硬保底下限，最后处理大保底的最高档必出。
```

- [x] 角色概率按当前档和UP开关分组，权重先除以组内最大权重再归一化以避免溢出。大保底强制目标时仅返回该角色1；无名单返回空分布。
- [x] advance_state按真实稀有度清零下档/增加高档；目标命中后关闭或重置。真实进度不能用理论缓存压缩值覆盖。拒绝概率为0的结果；直接赠送不调用它。
- [x] transition_branches用稀有度×角色条件概率生成分支，无名单生成character_id=None分支，不消费RNG。理论和模拟调用同一概率函数。
- [x] 写边界用例（不逐项执行）：

```python
c = make_default_compiled()
r6 = max(c.rule.rarities, key=lambda r: r.rank).id
for misses, expected in [(64, .008), (65, .058), (78, .708), (79, 1.0)]:
    s = DrawState({r6: misses}, big_misses=0, big_active=False)
    assert abs(rarity_probabilities(c, s)[r6] - expected) < 1e-12
s = DrawState({r6: 0}, big_misses=119, big_active=True)
assert character_probabilities(c, r6, s) == {character_id(c, "UP-A"): 1.0}
```

另覆盖同时软/硬保底、最低档无实际保底改善、四档新增、各档UP权重、同名跨档角色、不可能初始历史、目标已获后关闭及循环模式。真实未出数与压缩概率键分开断言。

**交付标准：** 两个计算器纯计算，状态推进无随机数，统一内核可被模拟和理论调用。

## 任务3：模拟、过程事件与统计计数

**文件：** 新建`events.py`、`results.py`、`tests/test_dynamic_engine.py`；修改`engine.py`、`control.py`（仅必要类型）、`tests/test_engine.py`、`test_bonus_rule.py`。

**接口：** 消费任务2函数；产出EventCounts、ProcessEvent、SimulationResult、draw_once、simulate_draws及simulation_payload。完整simulate由任务4组合理论；内部simulate_draws结果theoretical=None，序列化拒绝该未完成结果。event_counts返回全实验计数，另在预览输出每轮计数；trace_events关闭时为0，不能将实际事件总量误称已保存条数。

- [x] 实现event_counts：H=initial_main_draws，D=draws；首次赠送按H<T≤H+D；周期触发按整数整除差计算，乘trials，数量和事件条数分开。
- [x] draw_once按固定顺序消费一次稀有度随机数，有名单再消费一次角色随机数，包含必出抽；返回真实前后状态及角色条件概率。
- [x] simulate_draws每轮从同一初始状态开始，全运行用同一seed初始化Random一次；seed为空时生成实际seed并存入返回参数。模拟阶段以真实处理事件数（主抽＋赠送抽＋grant触发次数）反馈进度，Trace关闭也使用此阶段分母；赠送/直接赠送完成后才计该步骤完成。阶段100%不是任务完成，循环中保持取消检查。
- [x] 主抽后先运行独立临时赠送池再直接赠送，主池状态不回写；新机制都读配置。grant数量大于1仍一条事件，无奖励/RNG。
- [x] 使用统一汇总器累计draws/grants/acquisitions、动态角色和奖励及每轮分布；只Trace时构造事件，record_sink存在就流式输出，不在结果中另保留完整列表。
- [x] 完整事件序列化对draw和grant分别生成字段；draw含来源状态和main_state_before/after，赠送池事件的main状态不变；grant不含draw_result或虚构保底变化，source为null。draw_index、source_index只数抽取，event_index数全部事件，每轮从1开始。
- [x] results.py实现完整payload的版本、参数、计数、两类快照和抽样环境；网页include_events=false，CLI仅Trace时可true。奖励累计溢出或非有限数值明确报错，不写非法JSON，不把求解失败伪装成理论0。
- [x] 给测试夹具新增`deterministic_target_compiled(threshold=3, after_obtain="disable_after_obtain")`：两档，低档基础1、高档基础0，高档有UP-A，软/硬小保底关闭，大保底开启，其余赠送关闭；用它验证强制目标、模式及奖励，而不依赖随机碰巧触发。
- [x] 写明确计数/事件断言：

```python
from dataclasses import replace
c = make_default_compiled()
c = compile_pool(replace(c.rule, grant=replace(c.rule.grant, quantity=2)), c.pool)
p = default_parameters(draws=480, trials=1, seed=42, trace=True)
result = simulate_draws(c, p)
assert result.counts.main_draws == 480
assert result.counts.bonus_draws == 10
assert result.counts.total_draws == 490
assert result.counts.granted_characters == 4
assert result.event_count == 492
assert len([e for e in result.records if e.event_type == "character_grant"]) == 2
```

另比较同配置/seed的Trace开关结果；禁用/启用直接赠送的draw事件结果相同（排除事件序号差异）；30赠送不会重置大保底；实际第120抽仍只有一条主池draw。

**交付标准：** 全模拟结果不依赖Django；真实抽数、角色赠送数、事件条数和保底计数各自正确。

## 任务4：有限理论期望与主抽等待分析

**文件：** 修改`analysis.py`、`engine.py`；新建`waiting_analysis.py`、`tests/test_dynamic_analysis.py`、`tests/test_waiting_analysis.py`；更新`tests/test_analysis.py`。

**接口：** 消费transition_branches、event_counts、初始状态；产出expected_simulation_results与waiting_time_stats。结果与模拟的draws/grants/acquisitions结构对应。

- [x] 用可达状态概率质量递推主池；按联合分支累计角色、分类、奖励及触发次数，不能用星级总期望乘固定UP份额代替目标状态。
- [x] 仅在证明等价后归并状态/缓存；无用计数不进入理论键，饱和键不覆盖Trace真实计数。至少一次指标跟踪相应未获得概率，明确抽到与包括直接赠送的获得口径。
- [x] 赠送池从零状态独立递推，直接赠送数量按event_counts确定并加入获得合计；两者不回写主池理论状态。
- [x] 在engine.py提供完整simulate：先simulate_draws，进入theory阶段，以返回的实际参数调用expected_simulation_results，再用dataclasses.replace填theoretical。任务3原始循环可单独诊断，外部CLI/worker只能用完整simulate，不能把None当已计算。
- [x] 等待分析仅是未来主抽首次达到某档或以上，排除赠送。对当前内置算法先证明设计允许的非命中投影快速路径：非命中时查询档及更高档计数都加1，大目标不可能在更低档命中，低档保底不会改变查询档及以上总概率，因此下一步命中概率不依赖具体低档结果。
- [x] 使用上述投影递推，不调用“假定抽到最低档”的advance_state。有限强制边界由相关硬/软保底和仍有效的大保底剩余步数推导。若相关软/硬保底和大保底均无效，命中概率恒定q，直接用几何分布；q=0为不可达，q=1等待1。无需新建通用矩阵求解框架。
- [x] 输出waiting目标、source=main、unit=additional_main_draws、初始状态、分布描述、尾部质量、期望/分位数状态。有限显示窗口不冒充完整几何分布；未证明更新过程时不计算1/mean长期出率。非有限JSON用status与null。
- [x] 为分支、期望和等待写确定性断言，集中执行：

```python
c = deterministic_target_compiled()
p = default_parameters(draws=6, trials=1, seed=42, trace=False)
target = c.targets["big_pity"]
theory = expected_simulation_results(c, p)
assert theory["draws"]["main"]["character_counts"][target] == 1
# 首次3抽保底获得后关闭，高档基础0；未来主抽再次达到高档不可达。
p2 = default_parameters(draws=1, initial_main_draws=3,
    initial_big_pity=BigInitial(target_obtained=True, misses=0))
wait = waiting_time_stats(c, p2)
assert wait["mean"]["status"] == "infinite"
assert wait["mean"]["value"] is None
```

另枚举微型两/三档配置的有限结果与状态，核对递推；循环大保底六抽两次；首次H=2未获得目标剩余1主抽；纯固定q=.25等待均值4；有限均值不把已获标记解释为0。

**交付标准：** 期望跟踪具体目标状态；等待算法覆盖当前规则家族并有投影独立性说明，不扩展任意角色/多来源等待功能。

## 任务5：新版中文CLI与文件引用

**文件：** 修改`cli.py`、`config_documents.py`、`__main__.py`（仅必要入口）、`tests/test_cli.py`、`test_config_documents.py`。

**接口：** 消费load_rule_document、compile_pool、simulate及两类理论函数；产出`resolve_rule_reference(ref,directory,confirm)`及新版analyze/simulate/export-trace参数解析。

- [x] 从池文件引用解析规则，ID优先；仅ID不存在时按名称寻找并要求确认。ID存在但无有效文件/格式时不偷偷按同名覆盖。非交互终端存在歧义时中文报错，不等待输入或猜测。
- [x] 增加`--rule-directory`与`--rule-config`解析入口，后者仅解决池的规则引用，不允许绕过引用覆盖另一条规则；保留池/实验文件选择与显式运行参数覆盖。
- [x] 增加历史主抽、各档小保底、大保底初始状态输入：`--initial-main-draws`、`--initial-small-pity`（JSON的ID→整数映射）、`--initial-target-obtained`及`--initial-big-pity`（循环未获计数）。按模式校验；old initial-pity类参数明确拒绝，不兼容旧文件。
- [x] 中文报告按动态档名显示规则、目标、抽数、直接赠送、角色获得合计和理论含义；JSON不再输出固定mean_six_stars字段，不输出Infinity/NaN。过程导出调用任务9实现的流式接口，任务9前不宣称其可运行。
- [x] 写CLI断言和黄金输出：默认zmd读取成功、30×2/Trace事件80、H=250并显式已获目标时下一赠送480、旧格式拒绝、名称匹配需确认、任意大整数seed往返不损失。

```python
# tests/test_cli.py：通过现有main入口与StringIO捕获结果，不启动网页。
argv = ["simulate", "--pool-config", str(DEFAULT_POOL_PATH),
        "--draws", "30", "--trials", "2", "--seed", "42", "--format", "json"]
assert main(argv, stdout=output_stream) == 0
payload = json.loads(output_stream.getvalue())
assert payload["rule_snapshot"]["name"] == "zmd"
assert payload["counts"]["total_draws"] == 80
```

沿用当前`main(argv=None, stdout=None)`注入入口，不改命令行用户契约；用StringIO作为output_stream。

**交付标准：** analyze/simulate可独立使用新配置；运行入口不依赖Django或写入网页历史。

## 任务6：v6模型、迁移与默认业务初始化

**文件：** 修改`dashboard/models.py`、`dashboard/__init__.py`、`webapp/settings.py`、`management/commands/init_admin.py`；新建`dashboard/migrations/0002_independent_rules_v6.py`、`management/commands/init_business_defaults.py`；修改`tests/web/test_schema.py`、`test_bootstrap.py`、`test_sessions.py`中的路径/默认夹具。

**接口：** 消费任务1定义/默认文件；产出Rule、Pool.rule外键、SimulationRun新快照字段、SimulationEvent模型及init_business_defaults命令。保留User/LoginLimit字段与账号服务契约。

- [x] 新增Rule，字段沿用Pool的类型/可见性/所有者约束与名字规范化方式，加config_json、revision及算法标识；公共资源owner=null、private owner非空。
- [x] Pool.rule使用PROTECT，不再把rule_name当执行入口；config_json保存动态池文档。ExperimentConfig增加initial_context_json，仅解释输入，不替代当前规则。
- [x] SimulationRun增加规则ID/修订/名称/作者及rule_config_json，保存pool_config_json、parameters_json、initial_context_json、result_json及event_count；event_count替代record_count，Trace关闭为0、开启为实际事件数。删除固定initial_pity/initial_five_star_pity结构字段，seed继续文本存储，计数使用可表示int64的非负字段。
- [x] 用SimulationEvent、db_table=`simulation_events`替换DrawRecord；保留外键级联历史删除、运行/轮次/事件序号唯一性与来源/类型/JSON一致性约束。grant的source/draw_index/source_index为null，不强制有draw_result。
- [x] 保留0001原稿，新增0002。在任何DDL/触发器变更之前执行源库保护：核对`users`、`pools`、`experiment_configs`、`simulation_runs`、`draw_records`及登录防护/初始化/删除标记，非空源拒绝执行该新建目标流程，避免在真实v5源库上意外升级。空新目标完整应用0001→0002，最终`PRAGMA user_version=6`；不用仓库补建表或复制旧migration记录。
- [x] 在删除/改造旧逐抽表之前显式移除0001的`runs_draw_records_cascade`，避免残留触发器访问`draw_records`。核对`pools_config_set_null`是否随池表重建丢失，按最终ORM/SQL调用路径保证配置SET_NULL及新事件删除语义；需要底层SQL删除时明确相应新触发器，不依赖ORM的on_delete自动生成数据库CASCADE。最终schema不含指向旧表的触发器。
- [x] settings默认改v6路径。init_business_defaults须已有可用管理员，用固定默认ID创建公共zmd/池，已有资源不覆盖，同名冲突停止；成功后设置AppMeta.initialized为version=6。init_admin全新库在同一事务创建管理员后调用同一默认初始化逻辑，失败不留下部分默认对象或marker。已有账号不能通过init_admin重新初始化。
- [x] 写schema及初始化用例，包含以下核心断言；只对临时库运行最终验收：

```python
with connection.cursor() as cursor:
    cursor.execute("PRAGMA user_version")
    assert cursor.fetchone()[0] == 6
assert Rule.objects.filter(kind="public", owner=None, name="zmd").exists()
pool = Pool.objects.get(name="默认角色池")
assert pool.rule.name == "zmd"
assert not SimulationRun.objects.exists()
```

迁移拒绝用例使用MigrationExecutor生成只到0001的独立临时v5库并写账号，尝试0002应失败且账号不变；不能把Django test库当真实库。另覆盖空目标0001→0002完整迁移、删除带两类事件的历史、删除被实验配置引用的池，以及最终sqlite_master无悬空旧触发器；删除失败或关联行为退化不得交付。

**交付标准：** schema归migrations，空v6可初始化默认业务，非空v5源不被就地处理。后端其他服务仍在改造，不能用旧API宣称完整可运行。

## 任务7：独立规则服务、权限和引用保护

**文件：** 新建`dashboard/services/rules.py`、`tests/web/test_rules.py`；修改`services/accounts.py`、`api/management.py`、`tests/web/test_account_deletion.py`、`test_management.py`。

**接口：** 消费Rule模型与纯加载器；产出`visible_rules(actor)`、`rule_document(rule)`、`save_rule(actor,payload,rule_id=None,expected_revision=None)`、`copy_rule(actor,rule_id,name,kind)`、`delete_rule(actor,rule_id,expected_revision)`、`resolve_rule_reference(actor,ref,owner=None)`。新增RuleError沿用status/code/message错误形状。

- [x] 从当前DB重新验证actor、auth_version、启用/删除/必须改密状态，复用账号服务，不缓存对象权限。
- [x] 实现公共规则管理员管理、私有创建者/管理员管理、公开只读使用/复制、复制新ID保留作者。列表按权限分页，导出先鉴权。
- [x] 把保存规则放事务：先比revision；比较稀有度ID集合及rank，已有引用禁止结构变化；参数更新compile验证全部引用池，失败不更新任何字段/revision。
- [x] 隐藏转换校验所有引用池的公开关系和所有者使用权限；删除有引用直接拒绝，不能先删后补救。私有规则修改错误不返回他人隐藏池内容。
- [x] resolve_rule_reference按ID优先，ID存在但不可用返回unavailable，不降级名称匹配；ID缺失再匹配有权规则并确认。
- [x] 删除中的私有规则所有者不得接受新池引用/复制绑定；在池保存事务内重读owner.deleting。规则作者仅被停用则不自动隐藏既有公开资源；公共资源不因作者账号状态变化失效，已接受任务仍只消费快照。
- [x] 删除账号预览新增规则与他人池引用阻塞。先在原子边界做引用检查，再设置deleting；存在外部引用时不封禁用户、不级联删他人池；同一目标用户自有池删除后再删其规则。
- [x] 写角色矩阵、revision竞争、引用保护、匿名拒绝及下例：

```python
before = Rule.objects.get(pk=rule_id).revision
with self.assertRaises(RuleError):
    save_rule(owner, invalid_for_hidden_consumer, rule_id=rule_id, expected_revision=before)
assert Rule.objects.get(pk=rule_id).revision == before
assert Pool.objects.get(pk=consumer_pool_id).rule_id == rule_id
```

测试夹具中invalid_for_hidden_consumer是打开大保底，而引用的另一用户隐藏池最高档无UP；断言错误不含隐藏池名称。另验证blocked账户删除保持deleting=false及公共作者署名不变；并发新增引用与删除串行化，不让deleting期间产生新的外部引用。

**交付标准：** 普通规则管理与共享更新原子性具备；复制不改变源引用，账号删除不能越权删外部资源。

## 任务8：池、实验配置与初始上下文服务

**文件：** 修改`dashboard/services/pools.py`、`experiments.py`；新建`dashboard/services/initial_conditions.py`；更新`tests/web/test_pools.py`、`test_experiments.py`，新建`tests/web/test_initial_context.py`。

**接口：** 消费任务2/7；save_pool新增expected_rule_revision；copy_pool允许显式选择目标公共规则并核对源池/目标规则revision。`build_initial_context(compiled)`调用纯initial_context；`require_initial_context(compiled,parameters,context)`校验已确认解释；实验返回parameters及initial_context。

实施接口交接：`save_pool(..., expected_rule_revision, rarity_mapping=None, clear_unmapped=False)`；`copy_pool(..., expected_revision, expected_source_rule_revision, expected_rule_revision, rule_ref=None, rarity_mapping=None, clear_unmapped=False)`分别核对源池、源规则和目标规则。规则/池文档序列化返回纯文件定义，权限及revision由API另加；`resolve_rule_reference`返回matched/confirm/select/unavailable，matched包含内部Rule对象，名称候选是可序列化摘要。池导入使用`preview_pool_import`/`confirm_pool_import`；实验确认需要pool_revision和rule_revision。`require_initial_context`返回规范化ExperimentParameters，保存当前上下文使用`build_initial_context`。

`experiment_validation(config)`单独返回validation_errors/current_context/needs_confirmation，保留原参数不清零；任务10的实验列表/详情序列化必须调用它，不能把诊断字段混入严格导出文档。任务6移除dashboard包入口对旧job_models的提前导入，保证模型与迁移可独立加载；job_models及API的完整升级仍在任务10。

- [x] 将规则/池权限矩阵作为统一校验入口；管理员代管按owner权利，不把管理员隐藏规则赋给普通owner；同时执行任务7的规则所有者deleting保护。
- [x] 池保存解析当前规则并compile；现有池类型/作者不可原地转换。公开、复制、导入、规则切换同时校验最新rule revision。
- [x] 名单/奖励映射按ID处理；同ID复用，不同ID必须给明确映射或确认删除草稿；丢失目标拒绝保存，关闭机制不让失效草稿偷偷影响执行。
- [x] 实验配置只存池引用、参数和initial_context。保存重新normalize，不能由文件上传规则快照覆盖当前池规则。
- [x] 上下文是服务端生成的rule_id、rarity_ids顺序、big_mode、big_target_id；加载/导入/重跑比较这些字段，变化返回中文说明与需确认字段。全零值直接派生；非零或已获标记不静默清除。
- [x] raw导入解析保持大整数原文，按ID/名称确认资源，不自动升级旧格式。二次确认携带当前pool/rule revision；未知/不可访问ID不泄露存在性。参数更新导致保存配置的初始条件非法时，配置仍可读取/修正，响应附校验错误和当前上下文；不能直接提交，不自动删除配置。
- [x] 写不可能历史、目标重排、模式互换、阈值下降及下例：

```python
old = build_initial_context(compiled_a)
p = default_parameters(initial_main_draws=20,
    initial_big_pity=BigInitial(target_obtained=True, misses=0))
# compiled_b只重排最高档UP，当前第一个UP从A变成B。
with self.assertRaises(ValueError):
    require_initial_context(compiled_b, p, old)
```

ValueError可转项目ExperimentError，但不能在调用层吞掉并自动用新的true。另写公共池拒绝私有规则、公开私有池拒绝隐藏规则、复制为公共池先选公共规则、新规则参数不改旧历史用例。

**交付标准：** 保存/使用配置时初始条件有明确目标；池没有独立概率或保底副本；所有资源关系可由服务端验证。

## 任务9：过程Trace、历史仓库和流式导出

**文件：** 修改`dashboard/trace_store.py`、`repository.py`、`trace.py`、`trace_export.py`、`downloads.py`、`limits.py`、`lottery_simulator/cli.py`；更新`tests/test_trace_store.py`、`test_trace_queries.py`、`tests/web/test_downloads.py`、`test_owned_runs.py`、`test_limits.py`、`test_cli.py`。

**接口：** 保留TraceWriter/TraceReader名称，处理ProcessEvent。提供`validate_event(event)`、`TraceWriter.append(event)`、`finish(compiled,parameters,counts,*,cancel_check=None,progress_callback=None)`、`TraceReader.query_events(filters,limit,offset)`、`count_events(filters)`、`iter_events(filters,batch_size)`及position_counts（返回每个位置的list[dict]，含source_index、observations、rarity_counts）。compiled必须来自接受时的冻结快照，不能重查当前规则。TraceFilter新增event_type、rarity_id、character_id、main_from/main_to；source仍只有main/bonus。

- [x] 临时Trace库格式2以通用事件存储，按批写入，不先收集百万条事件。writer校验共同字段及按类型的字段，数量2的grant仍只写一条。
- [x] finish先用`event_counts(compiled.rule,parameters)`复核counts，再依冻结机制和已解析目标核对轮次/event_index连续、真实draw_index/source_index、事件数、主抽/赠送/周期位置、同位置顺序及每次grant目标/数量；不能仅凭总数正确或事件自报触发位置就标complete。offset从0开始，UI页码从1开始。
- [x] Reader只读打开，拒绝不完整/旧格式；任意SQL值参数绑定。grant无抽取source；非法source与grant组合过滤拒绝，不暗中变为赠送抽。
- [x] position_counts只聚合draw、按当前来源source_index，返回动态稀有度计数和实际有效轮数，最多1000连续位置。
- [x] HistoryRepository只核对v6 schema，保存规则/池/目标/上下文快照及汇总。事务批量导入SimulationEvent，关键列与JSON一致；取消回滚，删除历史级联事件。未Trace的event_count=0且不插入事件。
- [x] JSONL首行元数据及后续事件按顺序流式导出；100万/1万按事件，保留下载SessionGate、每批撤权及文件清理。CLI export-trace也调用此导出形状。
- [x] 将下例落成store与history两种Reader用例，并补旧版本、损坏记录、取消、下载10000/10001边界。构造总数和序号仍正确但首次赠送提前/延后、周期目标错误，或两次赠送数量1和3而配置均为2的事件，finish必须拒绝：

```python
events = reader.query_events(TraceFilter(event_type="character_grant"), limit=50, offset=0)
assert len(events) == 2
assert sum(item["grant"]["quantity"] for item in events) == 4
assert all(item["source"] is None and "draw_result" not in item for item in events)
counts = reader.position_counts(source="main", trial_from=1, trial_to=1,
                                source_from=239, source_to=241)
assert all(row["observations"] == 1 for row in counts)
```

query_events返回当前页list；API在外层附total/page，不能把数量2当两条或把grant作为main=240的第二次抽取。

**交付标准：** 两类事件分开合法化，非Trace不存明细，历史写入和流式下载保持既有安全边界。

## 任务10：任务快照、worker和完整后端API

**文件：** 修改`dashboard/job_models.py`、`jobs.py`、`worker.py`、`services/runs.py`、`api/serializers.py`、`api/pools.py`、`api/experiments.py`、`api/jobs.py`、`api/runs.py`、`api/urls.py`、`api/management.py`、`dashboard/charts.py`；新建`api/rules.py`；更新`tests/test_job_models.py`、`tests/web/test_owned_jobs.py`、`test_management.py`、`test_end_to_end.py`、`test_account_deletion.py`、`test_rules.py`、`test_position_chart.py`及`tests/test_dynamic_charts.py`。

**接口：** 新RunParameters固定包含job_format_version、sampling_version、parameters、rule_snapshot、pool_snapshot、resolved_targets、initial_context；JobState额外保存rule_source（id/revision/name/author）。RunParameters的to_dict/from_dict严格版本与形状校验。

任务6—8服务交接：新增`POST /api/v1/pools/import/preview/`及`/confirm/`，确认请求包含document、rule_id、rule_revision；pool copy请求包含name、kind、expected_revision、expected_source_rule_revision、rule_ref及expected_rule_revision，结构变化时附rarity_mapping/clear_unmapped。实验保存携带expected_pool_revision/expected_rule_revision，导入确认携带pool_revision/rule_revision。列表/详情调用`experiment_validation`返回原参数、validation_errors、current_context及needs_confirmation；文件导出仍是纯定义。原文件字节先严格解析，确认的API十进制文本往返由服务显式还原，不能把宽松转换用于raw文件。

提交`POST /api/v1/jobs/`形状：

```json
{
  "pool_id": "池UUID",
  "expected_pool_revision": 1,
  "expected_rule_revision": 1,
  "parameters": {
    "draws": "30", "trials": "2", "seed": "42", "trace": true,
    "initial_main_draws": "0", "initial_small_pity": {},
    "initial_big_pity": {"target_obtained": false, "misses": "0"}
  },
  "initial_context": null
}
```

全零初始条件可null并由服务端派生；其他情况提供任务8校验后的当前上下文。实际JSON示例中的池UUID需替换有效ID，不能当默认常量。

- [x] 在既有全局接受锁和DB事务内重新鉴权，检查pool/rule revision与关联权限，normalize参数、context及总事件限额，生成实际seed并freeze全部快照。JobState.total_units为真实处理事件总数而非Trace条数或只计主抽，UI明确阶段含义。
- [x] 已接受worker只从快照compile，不重读当前规则或角色；保留接受时限额快照，用户退出/降权不改变已接受算法，删除账号仍经过已有停止/提交屏障。
- [x] worker调用完整simulate，writer仅Trace启用，以同一冻结compiled和实际参数调用任务9的finish后保存结果；真实simulating/theory/validating/saving/committing阶段与取消点保持一致。job_models.result_payload(result,compiled,duration)委托纯results.simulation_payload，不让CLI导入Django；结果摘要不内嵌完整records。
- [x] 更新任务有效性、结果重存与重启调和，拒绝旧jobs目录/版本，不扩大为残次数据恢复；取消清理当前残次事件和结果，已保存历史不会被取消删除。
- [x] 新增规则collection/resource/copy/import-preview/import-confirm/export路由。池与实验路由保留位置但返回新契约，匹配/二次确认不自动重试POST。
- [x] API整数状态/seed均规范化为十进制文本，规则概率/权重为有限数值；raw文件导出不经JS解析整数；serializer拒绝未知字段、owner伪造和bool修订号。
- [x] run/任务结果、Trace、图表、原生下载及管理列表统一使用服务层授权；历史重跑比较池及规则修订/目标上下文，提交新任务不覆盖旧历史。
- [x] 将旧end-to-end夹具转v6后写一个物理临时库流程及以下断言，先保留到集中验收：

```python
state = submit_job(actor, submission_payload, synchronous=True)
assert state.status == "completed" and state.history_saved
run = SimulationRun.objects.get(pk=state.run_id)
assert run.rule_name_snapshot == "zmd" and run.schema_version == 6
assert run.event_count == 80
assert SimulationEvent.objects.filter(run=run).count() == 80
```

另覆盖共享规则修改后的下一任务生效、旧已接受快照不变、任一revision不符409、双用户403/404、并发单任务竞争、提交响应丢失通过jobs/mine找回、取消不留下半条历史。

**交付标准：** 临时v6可从API接受任务、模拟、保存、查看、取消和下载；不把旧前端或真实v5库用于此阶段验证。

## 任务11：共享前端类型与规则管理页面

**文件：** 修改`frontend/src/api/types.ts`、`App.tsx`、`styles.css`、`components/ImportDialog.tsx`；新建`pages/Rules.tsx`、`components/RuleEditor.tsx`、`test-fixtures.ts`、`pages/Rules.test.tsx`、`components/RuleEditor.test.tsx`。

**接口：** 使用现有`apiRequest<T>(path, options, signal)`，不另建认证客户端。新增RuleDocument、Rule、动态PoolDocument、ExperimentParameters、InitialContext及ProcessEventRecord类型；API整数/seed为string，概率/权重为number。ProcessEventRecord是draw/grant判别联合，不用一个全optional类型掩盖字段错误。

- [x] 按任务1/10契约更新共享类型，计数不得通过Number转换后再提交。Rule resource包含kind/visibility/owner/revision及有权限的引用摘要，RuleDocument只包含可导出的规则数据。
- [x] 在App侧栏加入“规则”，路由`/rules/`，仍由ProtectedLayout保护。中文页面说明强调改共享规则影响下一次模拟，不开始模拟。
- [x] Rules提供公共/本人/他人公开及管理员全部私有筛选、分页、查看、编辑、复制、删除和导入导出；不可编辑资源只读，复制保留作者。
- [x] RuleEditor按设计第11.2节分组。稀有度有新增/删除/上下移动控件，用stable ID作为React key，不能用数组index导致输入/确认错绑。
- [x] 有引用规则结构操作禁用并给“复制新规则”说明，参数可编辑；保存revision冲突显示重新加载提示，不自动覆盖草稿或重试。
- [x] 概率/增幅输入保留本地十进制文本中间态，失焦/提交时换单位；字段直接显示百分比/百分点及首增抽次例子；保底/赠送关闭时明确“不生效”。按钮支持键盘，重要解释直接可见。
- [x] 创建frontend test-fixtures，提供`makeRuleDocument()`、`makePoolDocument()`、`makeExperimentParameters()`从默认JSON派生新类型；`renderRuleEditor(props)`仅作为本测试文件包装。写下例及权限/结构锁/导入确认用例，不中途跑全前端：

```tsx
const rule = makeRuleDocument();
render(<RuleEditor value={rule} onChange={onChange} structureLocked={true} />);
expect(screen.getByText(/复制为新规则/)).toBeVisible();
expect(screen.getByRole("button", {name: "添加稀有度"})).toBeDisabled();
expect(screen.getByText(/百分点/)).toBeVisible();
```

RuleEditor props明确包含value、onChange、structureLocked，权限/基本元信息可在页面外层表单控制，不把owner或revision输入混进定义数据。

**交付标准：** 独立规则可按权限编辑，页面对规则结构/概率说明清晰；旧池/实验页仍待后续适配，不宣称整体前端已可用。

## 任务12：动态角色池编辑与规则绑定

**文件：** 修改`pages/Pools.tsx`、`components/PoolEditor.tsx`、`styles.css`及相关测试；新建`components/RuleSummary.tsx`、`components/RarityMapping.tsx`。

**接口：** RuleSummary消费服务端当前规则摘要及解析目标，只读；RarityMapping消费旧/新稀有度ID，产出用户明确的映射/清空选择。PoolEditor消费PoolDocument、所选Rule及权限，产出完整池草稿。

- [x] 使用任务10的有权规则候选与规则revision，不再写`rule_name: "rule1"`。池按基本信息、规则摘要、各档名单、机制目标、奖励、显示设置分组。
- [x] 各档角色使用稳定ID新增/移除/调整顺序；UP勾选自动限定，所有角色有权重；说明启用UP分组与UP标记不同，不把UP占比当整次抽取概率。
- [x] 展示最高档大目标及赠送目标，直接赠送pool_selected时从全部实际角色选ID；删除/改UP后即时显示失效绑定，不能用同名角色替代。
- [x] 切换规则先展示结构差异：相同ID保留，其他ID要明确映射或清空；没有确认不修改已有池。映射角色、奖励、显示名后重新解析目标。
- [x] 普通用户私有池复制/公开沿用关系校验，管理员复制公共池必须选公共规则。请求携带最新rule revision，不能仅因为有admin身份跳过owner可使用范围。
- [x] 奖励列由稀有度ID生成、默认缺额0；显示改名只改标签，源ID不变。默认池名单来自配置JSON，不在组件重写。
- [x] 写角色权重中间态、四档渲染、规则切换确认及下例：

```tsx
render(<PoolEditor value={pool} rule={rule} onChange={onChange} {...permissionProps} />);
expect(screen.queryByLabelText("六星基础概率")).not.toBeInTheDocument();
expect(screen.getByText(/查看规则/)).toBeVisible();
expect(screen.getByText(/权重.*比例/)).toBeVisible();
```

测试pool/rule均由makePoolDocument/makeRuleDocument构建，permissionProps在本用例显式设创建者权限；不可把权限省略解释成管理员。

**交付标准：** 池只引用规则，角色/奖励/目标动态配置，类型/公开关系有效；新界面没有重复五星保底编辑入口。

## 任务13：新建实验、初始条件与接受预览

**文件：** 修改`pages/NewExperiment.tsx`、`components/ExperimentForm.tsx`、相关测试；新建`components/InitialConditions.tsx`、`components/SimulationPreview.tsx`；必要修改任务10的预览序列化。

**接口：** ExperimentForm维护十进制文本；InitialConditions消费当前规则、目标、保存上下文及参数，产出显式确认上下文；SimulationPreview消费服务端`preview_submission`的参数校验/计数结果。新增`POST /api/v1/jobs/preview/`仅解析/校验/预览，不接受任务、不生成seed或写历史；正式提交仍重新核对。

- [x] 基本区保留主抽/轮、轮数、seed及“保存全过程明细”，保存配置和开始模拟分开，start pending禁重复。
- [x] 初始条件放高级区域，按当前规则显示各档、历史累计、大保底模式与带目标名称的标记/计数。非零摘要始终可见，禁用相关字段时不隐含携带旧有效值。
- [x] 配置加载/导入可读取非法旧初始条件并修改，但不可直接提交；当上下文变化时指出旧/新目标和模式，用户明确修正或确认。数学非法值确认后仍拒绝。
- [x] preview_submission复用compile/normalize/context/event_counts，返回每轮及全实验主抽、赠送抽、真实总抽、赠送角色数、Trace事件数及下一触发位置；类型错误显示原值，不展示伪估算。
- [x] 最终请求采用任务10形状，双revision与上下文必须匹配当前摘要；5xx/网络不确定仍只查jobs/mine人工核对，不重复POST。管理员代管他人配置保留owner池范围与本人模拟池独立选择。
- [x] 新增前端race用例，验证从UP-A的已获true切换到UP-B不会立即提交，并包含：

```tsx
// 页面夹具返回H=20、已获A配置及当前目标B。
await user.click(screen.getByRole("button", {name: "开始模拟"}));
expect(screen.getByText(/初始条件.*目标.*变化/)).toBeVisible();
expect(jobPost).not.toHaveBeenCalled();
```

另覆盖H=0且已获true、阈值下降H=110/新100、H=250且已获目标时下一赠送480、大seed raw文件往返、保存配置不开始模拟。

**交付标准：** 初始状态不会脱离目标，预览与worker计数同源；不会因说明升级而产生重复任务。

## 任务14：结果、历史、动态图表与过程明细

**文件：** 修改`pages/Results.tsx`、`History.tsx`、`components/ChartPanel.tsx`、`TraceTable.tsx`、`DownloadForm.tsx`、`dashboard/charts.py`、`api/runs.py`及对应测试。

**接口：** RunResult消费counts、simulation/theoretical、规则/池快照；TraceTable名称可保留作为组件文件名但界面叫“过程明细”，消费ProcessEventRecord联合；图表来源口径使用draws/main|bonus|total、grants、acquisitions。

- [x] 概览优先显示主抽/轮、轮数、总主抽、赠送抽、总真实抽数、直接赠送数量及角色获得合计，附规则与池revision、seed、耗时和Trace条数。
- [x] 分类统计按动态稀有度/角色/类别/奖励/保底渲染，模拟与理论柱并排、标数值；明确draw/grant/acquisition区别，理论0时相对误差不可用。
- [x] 按抽次分析只聚合draw，动态多选稀有度、单档可用，保留最多1000位置、自适应宽高、最近抽次tooltip、有效轮数及50行数值分页。不把grant画成抽取概率。
- [x] 过程表draw显示概率、角色、奖励和保底前后；grant显示直接赠送、数量、目标、主抽位置，其抽数/概率/奖励为不适用。增加类型筛选，grant选中时禁用并清除仅draw的source位置过滤。
- [x] 大整数展示用十进制文本，图表需要数值轴时不得静默损失精度；超过安全整数的位置用窗口相对坐标和原始文本刻度/tooltip，计数轴无法精确表达时明确图形近似、表格仍精确。
- [x] 原生下载沿用提前打开标签页、CSRF及服务端授权；匹配事件超过限额中文提示缩小筛选。非Trace说明无法事后补明细。
- [x] 历史显示两类快照，“按当前池及规则重跑”比较双方revision和初始上下文，确认后新任务不改原历史。停止任务保留真实阶段与清理确认，404后停止旧轮询。
- [x] 添加grant渲染、非Trace、单稀有度、新增档位、0值/巨整数和重跑目标变化测试；例：

```tsx
render(<TraceTable records={[grantEvent]} {...paginationProps} />);
expect(screen.getByText("直接赠送角色")).toBeVisible();
expect(screen.getByText("2")).toBeVisible();
expect(screen.getAllByText("不适用").length).toBeGreaterThan(0);
```

grantEvent使用event_type=character_grant、quantity=2、source=null，不含draw_result。组件props由任务9/10API页结构明确适配，分页元信息不能伪造不存在的记录。

**交付标准：** 结果不再局限六星且不混淆赠送与抽取概率，现有图表交互及下载权限没有回退。

## 任务15：保留账号工具与v6部署、备份接口

**文件：** 新建`dashboard/management/commands/import_v5_accounts.py`、`dashboard/services/account_transfer.py`、`tests/web/test_account_transfer.py`；修改`Dockerfile`、`docker-compose.yml`、`scripts/install.sh`、`scripts/backup_db.py`（仅必要提示/契约）、`deploy/lottery-backup.service`、`tests/test_installer.py`、`test_deployment_files.py`。

**接口：** `import_v5_accounts --source <只读v5路径>`目标取Django当前v6设置，不接受模糊隐含路径；`transfer_accounts(source:Path) -> dict`返回数量摘要，不能返回密码散列。source readonly、目标账号导入transaction，默认业务初始化另一步执行。

- [x] 导入工具解析真实路径并拒绝samefile、源非5、目标非6/迁移不完整、已有目标用户/业务、deleting账号/未完成删除清单、无可用管理员及迁移状态异常。只读检查全部成功后才能写目标。
- [x] 读取完整账号标量字段及LoginLimit防护，保留UUID/密码/角色/启用/必须改密等状态，auth_version递增；不复制Session、业务或旧迁移记录。目标原子导入，异常不留部分用户，不记录敏感字段。
- [x] 切换说明采用“备份 → 空v6 migrate → 导入账号 → init_business_defaults → 配置路径 → 最终切换”，旧库始终作为只读来源；不得在新migration中顺便删除v5内容。
- [x] Compose/settings/Dockerfile的目录改v6，安装脚本需完整rules默认文件。仅全新安装创建管理员；若发现v5库或升级情形就中文停止，不能在同一卷里悄悄创建新账号绕过保留流程。
- [x] 备份service使用`/app/data/history_v6.sqlite3`与`lottery-v6-`前缀，保留systemd中的`%%F`转义。文档说明备份包含账号与规则等私有数据，无旧任务目录自动恢复。
- [x] 保持腾讯云镜像、域名/HTTPS、双目录前端构建挂载和已有.env保留逻辑，不自动调整服务器软件源/域名/安全组，不运行真实安装。
- [x] Shell脚本保持LF，在WSL执行`bash -n scripts/install.sh`并安排原有假Docker用例；CRLF语法失败先处理工作树检出方式，不以批量修改源码或真实安装绕过。
- [x] 写源/目标临时库测试，覆盖只迁账号、旧会话失效、原密码可验证但不输出、源数据保持、deleting停止及samefile：

```python
before = read_source_users(source_with_deleting_user)  # 不打印敏感字段
with self.assertRaises(ValueError):
    transfer_accounts(source_with_deleting_user)
assert not User.objects.exists()
assert read_source_users(source_with_deleting_user) == before
```

测试辅助`read_source_users`和v5源生成函数只在test_account_transfer.py定义，用MigrationExecutor的0001历史模型生成，目标独立完整v6。安装测试仍假Docker流程，不把它记成实机部署。

**交付标准：** 保留账号与默认初始化可控，配置/备份接口指向v6；当前真实账号与服务器保持不变。

## 任务16：集中验收、旧入口清理与操作文档

**文件：** 所有归属用例及夹具、`README.md`、`dashboard-guide.md`、`deployment.md`、`docs/windows-wsl-temporary.md`；原本地使用手册按用户要求保持原文；维护任务1创建的`docs/changes/2026-09-30-independent-rules-rarities.md`。删除不再被调用的旧固定模块、旧默认文件及旧字段入口，测试迁移而不是全部删除。

**接口：** 消费任务1—15完整流程；产出可交付版本、真实验证证据与可执行操作说明，不自动做真实切换。

- [x] 对照本计划与设计逐项核查调用路径，替换所有当前运行/测试中的Rule1、固定4/5/6、旧版本/路径引用。历史变更文档不机械改成新版本；保留probability.py通用执行器及原账号/会话安全用例。
- [x] 在WSL执行集中验收，先按Windows临时说明设置LOTTERY_PYTHON，工作目录取任务1记录的隔离工作树，不使用Windows `.venv`或旧电脑路径。核对Shell脚本为LF且Bash语法通过；前端依赖只在确实缺少或锁文件变化时于Linux目录准备。
- [x] 以mktemp建立一次独立验收目录，环境绑定其history_v6、jobs_v6和exports_v6；所有DB测试/命令必须继承这些显式变量。

```bash
: "${LOTTERY_WORKTREE:?先设置为任务1记录的WSL隔离工作树绝对路径}"
: "${LOTTERY_PYTHON:?先设置为Windows临时说明中的有效WSL解释器路径}"
cd "$LOTTERY_WORKTREE"
LOTTERY_CHECK_DIR=$(mktemp -d /tmp/lottery-v6-acceptance.XXXXXX)
export LOTTERY_DATA_DIR="$LOTTERY_CHECK_DIR"
export LOTTERY_DB_PATH="$LOTTERY_CHECK_DIR/history_v6.sqlite3"
export LOTTERY_JOBS_DIR="$LOTTERY_CHECK_DIR/jobs_v6"
export LOTTERY_EXPORTS_DIR="$LOTTERY_CHECK_DIR/exports_v6"
"$LOTTERY_PYTHON" manage.py test tests --verbosity 1
/usr/local/bin/npm --prefix frontend run test -- --run
/usr/local/bin/npm --prefix frontend run build
```

以上命令是在实施后的任务16执行，不在编写本计划时执行。主功能用例集中一遍；失败时只重跑归属组定位，修复后再进行必要最终回归，不添加SHA/重复无关检查。

- [x] 同一隔离环境完成migrate、默认初始化、两个临时账号与真实worker的小型流程；浏览器验证规则复制/结构锁、池分组/映射、初始状态确认、30×2=80、240赠送、筛选/图表/下载、取消和历史重跑。
- [x] 浏览器启动前只读核对端口，已有服务不能盲目终止；优先现有8000/5173代理组合，若占用则明确调整隔离服务端口及临时代理配置。不更改正式数据环境；验收完只停止自己启动的服务。
- [x] 做临时v5→v6账号保留演练及v6备份/恢复功能验收；核对migrations最终状态和user_version，迁入账号可登录，Session未迁入，旧任务不被读取。不是服务器部署演练。
- [x] 补本轮已要求的操作说明：规则页、各档UP/权重、大小保底、两类赠送、初始条件、Trace口径、CLI及本地/服务器升级步骤。部署文档继续区分旧版本手动部署成功、新版接口验证和自动安装实机未测。
- [x] 记录实际命令、通过/失败、观察范围、未验项目与必要因果回归；不填预计测试数量冒充实测，不用进程启动或构建成功证明浏览器已加载新产物。

**交付标准：** 本轮核心与业务端到端集中验收通过，文档与实现一致；存在必需失败不得标已验证，不在此任务清真实旧库或推送。

## 任务17：授权后的本地集成与真实账号切换

**文件/对象：** 实施记录、修改台账、主项目实际Git状态、本地明确解析的v5源库/v6目标库及各任务/导出目录。涉及真实数据，默认不自动执行。

**接口：** 前置任务16必需验收通过，用户明确要求本地集成/执行真实切换；使用任务15工具，不另造删除/迁移快捷脚本。

- [x] 先汇报当前功能提交/分支及未提交修改，确认主项目真实路径、原版本和要保留的账号来源；本机候选为Windows临时说明记录的v5库，旧Ubuntu备份或服务器数据不能默认等同于该库，另选来源须明确核对。保护既有文档。只在明确授权后提交/本地合并，不推送，不改变GitHub默认分支。
- [x] 检查本地活动任务、服务、下载和定时备份，按设计停机边界等待/取消自己管理的任务；未知服务不强停。核对v5库实际路径、schema及没有deleting残留，备份为新私有文件。
- [x] 在独立v6目标运行完整migrate，检查版本后导入账号及初始化业务。仅统计账号数量/ID/角色状态，不打印用户名列表之外的私有内容、密码散列或Session。源库保持不变直到目标准备成功。
- [x] 切换本地配置到新库/新任务与导出路径，启动明确的新版本后端和对应前端产物；用用户原账号实际登录，完成一条小实验、历史读取及Trace访问。记录实际加载路径，不把构建成功当运行确认。
- [ ] 按事先列出的精确清单清理旧业务运行文件/任务状态引用，备份保留独立私有路径；不删除.env、整个data、工作区或Docker命名卷。材料删除后说明去向与备份可恢复范围。
- [ ] 失败则停止新服务并按既定回滚恢复旧代码/配置/库；不让旧代码读取v6，不执行reset --hard。更新实际Git、切换和证据状态；服务器仍未升级。

**交付标准：** 经授权的本地集成和真实切换完成，保留账号可用，新业务为空/default初始化；在线推送和服务器部署明确不包含。

## 7. 集中验收对照表

| 设计范围 | 实现任务 | 最终验收归属 |
|---|---|---|
| 独立规则、公共私有权限、复制/引用保护 | 6—8、11 | rules/pools/account_deletion＋浏览器 |
| 任意稀有度、全部角色权重及UP分组 | 1、2、12 | definitions/dynamic_rules＋池页面 |
| 基础/软硬小保底、默认65/66/79/80 | 2 | dynamic_rules |
| 大保底首次关闭与循环重置 | 2—4 | dynamic_engine/dynamic_analysis |
| 30临时池和周期直接赠送、初始累计 | 3、8 | dynamic_engine/initial_context |
| 初始上下文变更、不可能历史 | 2、8、13 | initial_context＋实验页面 |
| 有限理论、主抽等待与非有限输出 | 4、5 | dynamic_analysis/CLI |
| Trace、非Trace、事件顺序/数量与限额 | 3、9、14 | trace_store/queries/downloads＋页面 |
| 快照、接受锁、丢响应、取消、保存、撤权 | 9、10、13 | owned_jobs/end_to_end/downloads |
| 通用统计与图表、重跑及中文说明 | 11—14 | frontend/position_chart＋浏览器 |
| CLI引用、seed精度及旧格式拒绝 | 1、5、10 | CLI/config_documents |
| v6迁移、账号保留、备份、部署接口 | 6、15 | schema/account_transfer/deployment_files |
| 操作文档和本地实际切换 | 16、17 | 实施记录及用户真实登录观察 |

## 8. 自审与执行交接

- [x] 逐章对照设计第1—15章，每项功能/保护有任务及验收归属。
- [x] 核对跨任务名称、输入输出、ID/整数/JSON版本、事件数量与角色数量一致。
- [x] 核对任务3/4的模拟和理论依赖、中间阶段隔离、任务6/15的迁移及账号导入顺序。
- [x] 核对审查重点均有明确用例，不靠泛称“测试边界”。
- [x] 只读检查计划和现有入口，对照CLI的stdout注入、Django迁移、worker及Trace接口；不运行产品测试。

2026-09-30自审完成，修正了模拟/理论任务交接、event_count字段、真实阶段进度、DrawState可哈希及CLI测试入口等计划一致性问题。以上是文档核对，不是实现验收；任务1—17所有步骤仍未执行。

2026-10-01本机续接审查已完成：第1.1节记录实际WSL环境和只读数据摘要；任务1/15/16补LF工作树与Shell检查，任务6补旧触发器处理，任务9/10补冻结规则校验输入，CLI阶段明确分开analyze/simulate与过程导出。上述为审查阶段文档修订；后续任务1—16已完成、集中验收通过，进度与证据见实施记录，环境准备见Windows临时说明末节。设计第15.2节记录审查观察和未验范围。

默认按任务串行推进；内核、理论、上下文和切换任务需要熟悉完整契约，不能让相邻任务并行随意变更接口。只有用户明确选择分工才使用当前可用的子代理工具，不要求安装Superpowers或指定某个模型。本次审查不自动派代理、启动实施或切换真实数据。

阶段暂停时应写明“已实现但未集中验收”“已验证但未合并”“已本地切换但未服务器升级”，不能只写整体完成。
