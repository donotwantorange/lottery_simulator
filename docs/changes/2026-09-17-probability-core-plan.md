# 抽取概率核心重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分离概率计算与抽样，预留四五星名单，统一结果及保底状态，切换到不兼容旧格式的新历史与任务文件。

**Architecture:** Rule1计算条件概率和状态转换，PoolConfig计算角色份额，通用执行器只依据分布与roll选择；draw_once组织一次抽取，simulate组织实验及赠送。新库和新任务根通过路径与版本校验隔离旧数据，不迁移旧历史，Trace暂仍单轮。

**Tech Stack:** Python 3.11+、标准库random/math/sqlite3/dataclasses/unittest、现有Streamlit/pandas；不新增依赖。

**Spec:** [概率核心重构设计](2026-09-17-probability-core-design.md)。每名执行者先完整读design，再读自身任务；此前版本plan作废。

**状态:** 任务1～12已完成并独立审查通过，已按用户授权提交并合并到本地 `master`。合并后主目录311项测试通过；CLI和临时Streamlit启动健康检查此前已通过。真实浏览器点击与服务器现场未验，旧历史未清理，未在线推送。详见[本地合并记录](2026-09-18-probability-core-local-merge.md)。

## 全局约束

- 主项目：`/home/qykj/202607/test/lottery_simulator`。
- 测试解释器固定 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python`；工作目录为执行工作树，不能假定工作树内存在.venv。
- 执行前使用using-git-worktrees隔离。现有未提交README、使用手册、页面指南及设计计划均属于用户，保留并带入授权工作流，不清理或覆盖。用apply_patch编辑。
- rule_version是字符串 `"2.0"`；配置、结果、记录、抽样、任务版本为整数1；数据库版本为整数3。整数版本拒绝bool，不支持旧格式。
- 星级执行顺序6/5/4，角色按配置名单顺序。整次实验只初始化一次rng；有名单消耗角色roll，即使仅一人，无名单不消耗角色roll。Trace不消费随机数。
- 配置四五星默认空名单；角色身份为稀有度加名称；跨星级同名允许，同星级重名拒绝。
- 不要求重构前后seed逐抽一致，只承诺同新rule/sampling版本、完整配置、参数、种子和Python实现/版本可复现。
- Trace明确默认关闭，仍仅单轮。仅网页限制Trace主抽最多100000；核心/CLI本次不增加主抽上限。
- 不包含多轮Trace、位置频数图、海量明细分批存储、页面重排、四五星编辑表或四五星批量角色分析。
- 抽奖公式、奖励、首30主抽赠送及双池隔离不变；不新增依赖、性能框架、认证变化、服务器实测或SHA验证。
- 默认新库data/history_v3.sqlite3、新任务根data/jobs_v3。自定义LOTTERY_DB_PATH优先，旧库拒绝，不自行清空外部文件。
- 不兼容旧接口、字段、配置、结果或历史，不提供fallback或迁移框架。过渡任务暂留的方法在指定后续任务删除，最终不保留兼容代码。
- 不自动提交、合并或推送；授权实际切换前不删除用户历史或干扰其运行服务。

## 执行与交接规则

严格按任务1～12执行，一次一项。每项先由主代理告知任务输入、文件与验收标准，结束后审查通过才继续。

任务1、2、3、7、9、11可交Luna；4、5、6、8、10涉及状态或持久化，建议Terra高强度或主代理执行；12由主代理负责全局收尾。本文不启动子代理。

每项固定闭环：失败测试RED → 最小实现 → 指定测试组GREEN → 定向变异/撤回自身最小改动使同一检查失败 → 恢复GREEN → 主代理审查。不得回退用户无关改动。

旧测试引用已删除结构时，同任务按新契约更新断言，不用删除业务检查、放宽错误或保留旧别名来通过。任务之间未接入的展示/任务格式测试可暂列后续责任，指定组不能留失败，任务12全套必须通过。不虚构测试数量。

遇到文档与代码冲突，执行者向主代理说明，不自行增加新功能。最终记录每项测试命令、退出码、现象、变异恢复证据与作用边界。

## 最终文件职责

| 文件 | 职责 |
|---|---|
| 新lottery_simulator/formats.py | 版本常量、整数版本校验、采样环境信息 |
| 新lottery_simulator/probability.py | sample_distribution通用执行器 |
| rules/pool_config.py、configs/rule1_default.json | 新配置格式、名单与角色份额 |
| rules/base.py、rules/rule_1.py | 新Protocol、规则概率及状态转换 |
| engine.py | 通用结果、具名单抽返回、嵌套记录与实验组织 |
| analysis.py、dashboard/charts.py | 理论算法和新角色概率接口 |
| dashboard/views/configuration.py | 编辑往返保留名单 |
| cli.py、dashboard/models.py | 新JSON、文字输出与任务模型 |
| dashboard/repository.py | v3两表、校验、历史事务 |
| 新dashboard/trace.py、views/simulation.py | 中文Trace展开及展示 |
| dashboard/jobs.py、worker.py、app.py、views/history.py | 新任务版本、路径、失效引用 |
| docker-compose.yml、deploy/lottery-backup.service、存在时.env.example | 新路径及备份服务静态合同 |
| 对应tests/test_*.py | 目标行为和既有业务回归 |
| 当前README及使用/页面/部署手册 | 实际操作说明 |

### 唯一新逐抽序列化结构

```json
{
  "record_format_version": 1,
  "draw_index": 1,
  "source": "main",
  "source_index": 1,
  "bonus_event": null,
  "main_draws_completed": 1,
  "draw_result": {
    "outcome": {
      "rarity": 4,
      "character_name": null,
      "is_up": false,
      "is_limited": false,
      "rewards": {"奖励A": 1.0, "奖励B": 0.0},
      "five_star_pity_triggered": false,
      "six_star_hard_pity_triggered": false
    },
    "probabilities": {"four_star": 0.912, "five_star": 0.08, "six_star": 0.008},
    "state_before": {"misses_since_six_star": 0, "misses_since_five_or_higher": 0},
    "state_after": {"misses_since_six_star": 1, "misses_since_five_or_higher": 1}
  },
  "main_state_before": {"misses_since_six_star": 0, "misses_since_five_or_higher": 0},
  "main_state_after": {"misses_since_six_star": 1, "misses_since_five_or_higher": 1}
}
```

它是一条Trace记录，不是完整结果。运行级sampling_version与环境信息在结果中，不重复写到每条记录。

---

## 任务1：版本常量与环境信息

**Files:** 新lottery_simulator/formats.py、tests/test_formats.py。

**Produces:** 下列接口，后续直接导入，不各处重复硬编码，不做版本注册框架。

```python
import platform

CONFIG_FORMAT_VERSION = 1
RESULT_FORMAT_VERSION = 1
RECORD_FORMAT_VERSION = 1
SAMPLING_VERSION = 1
JOB_FORMAT_VERSION = 1
DATABASE_SCHEMA_VERSION = 3

def require_version(value: object, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise ValueError(f"{label}版本不支持")

def sampling_metadata() -> dict[str, int | str]:
    return {
        "sampling_version": SAMPLING_VERSION,
        "rng_algorithm": "python.random.Random",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }
```

- [x] 写失败测试，require_version(1,1)通过，True/"1"/None/2拒绝；metadata四键及platform值正确：

```python
def test_integer_version_rejects_bool_and_string(self):
    for value in (True, "1", None, 2):
        with self.subTest(value=value), self.assertRaises(ValueError):
            require_version(value, 1, "任务")
```

- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_formats -v` 看到接口缺失RED；按示例实现，再GREEN。
- [x] 变异type检查为isinstance(value,int)，True必须导致测试失败，恢复通过。rule_version字符串不能调用require_version。

## 任务2：通用概率执行器

**Files:** 新lottery_simulator/probability.py、tests/test_probability.py。

**Produces:** `sample_distribution(distribution: Sequence[tuple[T,float]], roll:float)->T`；T在项目中为int或str，不接受bool选项。

- [x] 写阈值与零尾项失败测试：

```python
def test_order_and_threshold(self):
    values = ((6, 0.008), (5, 0.08), (4, 0.912))
    self.assertEqual(sample_distribution(values, 0.0), 6)
    self.assertEqual(sample_distribution(values, 0.008), 5)
    self.assertEqual(sample_distribution(values, 0.5), 4)

def test_zero_tail_never_selected(self):
    values = (("a", 0.9999999999995), ("zero", 0.0))
    self.assertEqual(sample_distribution(values, 0.9999999999998), "a")
```

- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_probability -v` 确认RED。
- [x] 校验非空、选项类型/唯一；概率非bool数值，转float捕获TypeError/ValueError/OverflowError，有限且[0,1]；math.fsum和与1差≤1e-12。roll有限非bool数值且[0,1)，非法统一ValueError。
- [x] 实现核心选择，不调用rng：

```python
cumulative = 0.0
for item, probability in validated:
    if probability == 0.0:
        continue
    last_positive = item
    cumulative += probability
    if roll < cumulative:
        return item
return last_positive
```

validated为已校验且float化的输入序列；合法和为1保证至少一项正概率。不裁剪、不自动归一化非法分布。

- [x] 补非法subTest：空、重复项、负p、p>1、NaN/inf、和0.9、bool/字符串概率、10**400、roll=-0.1/1/NaN/bool。GREEN后 `<` 变异为 `<=` 应失败，恢复GREEN。

## 任务3：新配置与可选四五星名单

**Files:** rules/pool_config.py、configs/rule1_default.json、tests/test_pool_config.py；analysis.py、dashboard/charts.py的新角色接口调用；临时更新rule_1.py旧pick_six_star的计算入口，任务5删除它。

**Produces:** WeightedCharacter(name:str,weight:float=1.0)、两个默认空tuple名单、PoolConfig.character_probabilities(rarity:int)->dict[str,float]。

- [x] 写失败测试：

```python
def test_optional_rosters_round_trip(self):
    raw = load_pool_config().to_dict()
    raw["four_star_characters"] = [
        {"name": "同名角色", "weight": 1}, {"name": "四星B", "weight": 3}
    ]
    raw["five_star_characters"] = [{"name": "同名角色"}]
    config = PoolConfig.from_dict(raw)
    self.assertEqual(config.character_probabilities(4), {"同名角色": 0.25, "四星B": 0.75})
    self.assertEqual(config.character_probabilities(5), {"同名角色": 1.0})
    self.assertEqual(PoolConfig.from_dict(config.to_dict()), config)
```

- [x] RED后默认JSON增加format_version=1、两份空数组。from_dict必须验证版本，拒绝旧无版本配置；既有手写测试配置按新规范补版本，不加fallback。
- [x] WeightedCharacter用frozen/slots，复用现有名称与有限数校验，weight>0；PoolConfig验证名单tuple、元素类型、同稀有度名称唯一。字段不要求保持旧位置构造，测试推荐关键字。
- [x] 名单省略等价空，显式null/非列表拒绝；weight省略1。to_dict始终输出version与两份数组，哪怕空。
- [x] 六星复用UP缩放算法；四五星先除最大权重再归一化，返回配置名单顺序，rarity非4/5/6或bool拒绝。
- [x] 删除six_star_character_probabilities，所有数学/图表调用改character_probabilities(6)，不保留别名。
- [x] 校验具体例：多UP1:3占0.5→0.125/0.375；大有限权重1e308+1e308→0.5/0.5；同星级重名/空名/权重0负NaNinfbool/溢出拒绝，跨星级同名允许。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_pool_config tests.test_charts -v`。变异权重分母或名单顺序检查，失败后恢复GREEN。

## 任务4：规则职责、显式硬保底和合法转换

**Files:** rules/base.py、rules/rule_1.py、tests/test_rule_1.py、tests/test_bonus_rule.py。

**Produces:** rule.character_probabilities(rarity,state)、six_star_hard_pity_active(state)、严格advance_rarity。暂留advance供任务6过渡，不保留到最终。

- [x] 写失败测试：

```python
def test_bonus_has_no_six_star_hard_pity(self):
    rule = Rule1(fixed_six_star_probability=0.008, subrules=())
    self.assertFalse(rule.six_star_hard_pity_active(DrawState(79, 0)))
    self.assertTrue(Rule1().six_star_hard_pity_active(DrawState(79, 0)))

def test_five_star_pity_cannot_return_four_star(self):
    with self.assertRaises(ValueError):
        Rule1().advance_rarity(DrawState(0, 9), 4)
```

- [x] RED后Protocol新增方法。角色概率验证state后委托配置，不使用roll。硬保底判断验证state后固定池False，主池max_pity-1 True，不使用p6==1判断。
- [x] advance_rarity拒绝非4/5/6及bool、零概率星级，不生成非法双状态；先算概率再转换，不能形成rarity_probabilities与advance_rarity相互递归。
- [x] 保持主池六星0～79；固定概率池的连续未出六星计数允许非负并不设80硬保底，避免仅沿用主池状态上限。这不改变默认赠送10抽长度。五星计数依然受自己的保底设置限制。
- [x] 四星剩余概率只允许数学舍入[-1e-12,0)归0，低于则拒绝；已有普通配置及赠送复制预校验保留。
- [x] for_bonus继承三类名单、奖励、UP，五星强制10，subrules清空，主池state不共享。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_rule_1 tests.test_bonus_rule -v`；变异硬保底为只看计数应失败，恢复GREEN。65/66/79/80公式不变。

## 任务5：具名单抽结果、统一选角和新Trace

**Files:** engine.py、rules/base.py、rules/rule_1.py、tests/test_engine.py、tests/test_bonus_rule.py。

**Produces:** DrawOutcome通用character_name；DrawResult(outcome,probabilities,state_before,state_after)；design第7节DrawRecord；draw_once返回DrawResult。

- [x] 复用现有SequenceRandom写失败测试：

```python
def test_four_star_name_uses_common_result(self):
    raw = Rule1().config.to_dict()
    raw["four_star_characters"] = [
        {"name": "四星A", "weight": 1}, {"name": "四星B", "weight": 3}
    ]
    result = draw_once(Rule1(PoolConfig.from_dict(raw)), DrawState(), SequenceRandom((0.9, 0.2)))
    self.assertEqual(result.outcome.rarity, 4)
    self.assertEqual(result.outcome.character_name, "四星A")
    self.assertEqual(result.state_before, DrawState())
    self.assertEqual(result.state_after, DrawState(1, 1))
```

- [x] RED后按design建立frozen/slots类，删除six_star_character、is_six_star及旧记录顶层probability/pity_position/state_after，不添加旧别名。
- [x] draw_once使用以下执行入口：

```python
probabilities = rule.rarity_probabilities(state)
rarity = sample_distribution(
    ((6, probabilities.six_star), (5, probabilities.five_star), (4, probabilities.four_star)),
    rng.random(),
)
characters = rule.character_probabilities(rarity, state)
name = sample_distribution(tuple(characters.items()), rng.random()) if characters else None
```

6星分布空时必须报错；非空一人名单也消费第二roll。六星由name查元数据，四五星flags False。奖励按星级、两种触发按抽前接口、advance_rarity更新，返回DrawResult。

- [x] 删除pick_six_star及Protocol定义。simulate两处draw_once读具名字段；六星判断rarity==6，六星角色汇总只访问6星name，不能混入四五星。
- [x] collect_records默认False，None拒绝，True仍要求trials1；需要Trace的既有测试显式True，不以保留单轮隐式行为兼容。
- [x] 主池记录两套state前后分别一致；赠送draw_result是临时池，main前后相等且累计不动；record_format_version为1，无trial_index。
- [x] 验证默认无名单四五星只消费一个roll、有名单消费两个；五星角色、六星flags、奖励与状态。Trace开关一致性：

```python
def test_trace_does_not_change_outcome(self):
    a = simulate(Rule1(), 30, trials=1, seed=42, collect_records=False)
    b = simulate(Rule1(), 30, trials=1, seed=42, collect_records=True)
    self.assertEqual(a, replace(b, records=()))
```

- [x] 用patch(engine.DrawRecord,side_effect=AssertionError)证明关闭时主/赠送均不构造记录，开启控制确实触发；更新旧契约测试的字段路径。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_engine tests.test_bonus_rule -v`；变异多/少消耗角色roll或赠送main状态赋值，失败后恢复GREEN。

## 任务6：理论递推与旧advance删除

**Files:** analysis.py、rules/base.py、rules/rule_1.py、tests/test_analysis.py。

**Produces:** 等待时间一维数学递推、有限期望真实双状态分支，彻底移除旧advance。

- [x] 写不依赖旧转换及接口统一失败测试：

```python
def test_waiting_distribution_does_not_advance_five_star_state(self):
    class NoAdvanceRule(Rule1):
        def advance(self, *args):
            raise AssertionError("不得调用旧advance")
        def advance_rarity(self, *args):
            raise AssertionError("等待时间不得虚构星级")
    values = waiting_time_distribution(NoAdvanceRule(), initial_pity=64)
    self.assertEqual(len(values), 16)
    self.assertAlmostEqual(sum(values), 1.0)

def test_theory_uses_explicit_hard_pity_flag(self):
    class NoHardFlagRule(Rule1):
        def six_star_hard_pity_active(self, state):
            return False
    result = expected_pool_results(NoHardFlagRule(), 1, DrawState(79, 0))
    self.assertEqual(result.pity_triggers["six_star_hard"], 0.0)
```

- [x] RED后waiting_time_distribution使用从0开始的offset，避免与design中从1开始的抽次i混淆：

```python
for offset in range(rule.max_pity - initial_pity):
    m = initial_pity + offset
    probability = rule.probability(DrawState(m, 0))
    probabilities.append(survival * probability)
    survival *= 1.0 - probability
    if probability == 1.0:
        break
```

循环前初始化survival=1.0、probabilities=[]。首次调用对应当前初始进度的下一抽，与design的m=m0+i-1一致；不用advance/advance_rarity，最多80-initial_pity项，累计概率与1之差≤1e-12。
- [x] 固定概率池完整周期明确ValueError；Rule1当前固定模式可用明确属性识别并供分析读取，不新建通用能力框架。不能将80项截断后归一化。
- [x] expected_pool_results保留真实4/5/6非零分支及advance_rarity，five/six触发均读接口；固定池在79位置也不会被理论误判硬保底。
- [x] expected_six_stars委托expected_pool_results(rule,draws,DrawState(initial_pity,0)).rarity_counts["6"]；完整运行的expected_simulation_results使用真实初始双状态，独立赠送用有限DP。
- [x] 删除Rule1/Protocol.advance，核对全部调用。当前一维等待算法限六星概率不依赖五星状态的Rule1，不推广为任意规则。
- [x] 复用现有Fraction独立枚举参考：draws1～4、初始六星0/64/65/78、五星0/9，逐组比较星级期望；完整分布80累计1、默认赠送six硬触发0。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_analysis tests.test_rule_1 tests.test_engine tests.test_bonus_rule tests.test_charts -v`；理论硬判断变异为计数应失败，恢复GREEN。

## 任务7：配置编辑全链路不丢名单

**Files:** dashboard/views/configuration.py、tests/test_configuration_view.py。

**Produces:** editor_rows_to_config两个默认空名单参数、session初始化及重建转交，导入/导出/复用统一。

- [x] 现有EditorBoundary补失败测试：

```python
def test_editor_rebuild_keeps_imported_optional_roster(self):
    raw = load_pool_config().to_dict()
    raw["four_star_characters"] = [{"name": "四星A", "weight": 2}]
    st = EditorBoundary()
    config = PoolConfig.from_dict(raw)
    set_pool_config_editor_state(st, config)
    rebuilt = render_pool_config_editor(st)
    self.assertEqual(rebuilt.four_star_characters, config.four_star_characters)
    self.assertEqual(PoolConfig.from_dict(json.loads(st.download)), rebuilt)
```

- [x] RED后editor_rows_to_config增加four_star_characters=()/five_star_characters=()，接收WeightedCharacter序列，原字典增加format_version及两份name/weight数组。
- [x] set函数保存pool_four_star_characters/pool_five_star_characters，render显式转交；import/default/historyreuse沿现有set逻辑，恢复默认清空。
- [x] 摘要显示4/5星人数和“通过JSON编辑”，不增表格；Fake st需要caption时只增加公开最小方法。
- [x] 不回写data_editor返回值为baseline，原连续编辑测试必须保持。修改UP或奖励后导出名单仍在。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_configuration_view -v`，变异删名单转交参数应失败，恢复GREEN。

## 任务8：新结果格式、CLI和v3历史库

**Files:** cli.py、dashboard/models.py、dashboard/repository.py、tests/test_cli.py、tests/test_dashboard_models.py、tests/test_repository.py。

**Produces:** JSON结果版本1、采样环境metadata、新记录格式、数据库3。任务状态读取另由任务10调整。

- [x] repository临时库测试先断言user_version3及嵌套Trace往返；fixture需要Trace时明确collect_records=True。原“未来版本3不支持”fixture改4，成功2 fixture改3，旧拒绝测试仍覆盖1/2。
- [x] CLI和dashboard结果加入result_format_version及sampling_metadata；rule_version从rule.version取字符串2.0。CLI analyze带结果格式版本，不把无随机的理论分析伪称随机实验。
- [x] 非Trace不输出records，Trace用asdict嵌套记录；文字Trace读取draw_result.outcome/probabilities/state，配置摘要显示4/5星人数。不保留旧键。
- [x] _SCHEMA/initialize/save_run的成功版本和错误提示统一3，仍两表、外键级联、单轮(run_id,draw_index)主键及同事务提交，不增加概率/角色表或索引。
- [x] 保存前require_version检查结果/采样/配置版本，rule字符串单独校验；Trace要求trials1、record版本1、来源序号及嵌套必要类型，错误ValueError且事务无半份记录。
- [x] get_run返回前验证结果/配置格式，include_records时验证记录格式；旧库拒绝，不迁移、不自动删除。
- [x] 失败测试示例放repository现有类中：

```python
def test_reject_invalid_sampling_version_before_insert(self):
    payload = deepcopy(self.payload)
    payload["sampling_version"] = True
    with self.assertRaises(ValueError):
        self.repository.save_run(payload, trace_enabled=False)
    self.assertEqual(self.counts(), (0, 0))
```

- [x] 网页RunParameters Trace100001拒绝，CLI/核心不添100000限制，三入口多轮Trace仍拒绝。通过源码/参数校验测试证明，不为验证上限差异强跑巨量Trace。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_cli tests.test_dashboard_models tests.test_repository -v`；变异取消版本检查应失败，恢复GREEN。保留事务失败、旧库不被改写及级联删除检查。

## 任务9：中文Trace展开展示

**Files:** 新dashboard/trace.py、tests/test_trace_view.py；dashboard/views/simulation.py、tests/test_simulation_view.py。

**Produces:** `trace_rows(records:list[dict], reward_names:Sequence[str])->list[dict]`，纯展示，不改原记录。

- [x] 把plan顶部JSON作为普通字典fixture写失败测试：

```python
def test_trace_rows_keep_original_record(self):
    before = deepcopy(self.record)
    rows = trace_rows([self.record], ("奖励A", "奖励B"))
    self.assertEqual(rows[0]["星级"], 4)
    self.assertEqual(rows[0]["来源"], "主池")
    self.assertEqual(rows[0]["角色"], "未配置角色名单")
    self.assertEqual(rows[0]["六星概率"], 0.008)
    self.assertEqual(rows[0]["奖励：奖励A"], 1.0)
    self.assertEqual(self.record, before)
```

- [x] RED后按design第7节完整列映射实现，来源序号/星级/角色在前，状态分两计数独立列，奖励按配置顺序；无名单提示正确，四五星有角色直接显示。
- [x] st.dataframe改用展开rows，概率列NumberColumn或等价格式显示百分比，原JSON仍0～1小数；Fake st补最小公开接口，下载仍嵌套JSON。
- [x] 历史/当前结果同映射，运行信息增加sampling/environment摘要，放折叠区，不重排页面。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_trace_view tests.test_simulation_view -v`；变异将main状态映射为source状态，专门赠送fixture应失败，恢复GREEN。

## 任务10：任务版本、worker和旧结果隔离

**Files:** dashboard/models.py、jobs.py、worker.py、app.py、views/history.py；tests/test_jobs.py、test_dashboard_app.py、test_dashboard_models.py。

**Produces:** RunParameters.from_dict(raw)、JobState.from_dict(raw)严格读版本，新job根及失效session引用处理。

- [x] 两模型新增job_format_version/sampling_version，内存新对象可默认常量；文件from_dict必须先检查版本键存在，不能用构造默认接收旧文件：

```python
def test_serialized_parameters_require_explicit_version(self):
    raw = RunParameters("rule1", 1, 1, 0, 42, False).to_dict()
    raw.pop("job_format_version", None)
    with self.assertRaises(ValueError):
        RunParameters.from_dict(raw)
```

- [x] RED后from_dict先require_version(raw.get(...))再cls(**raw).validate，validate也验证版本；模型to_dict写两版本。JobManager.start拒绝不支持版本。
- [x] app默认history_v3/jobs_v3，worker读参数用from_dict，manager.get读state用from_dict；无效旧格式/损坏版本返回None并日志提示，活动扫描跳过不阻塞新任务。
- [x] get_result检查任务版本、完成状态、result_format与sampling对应state；错误/缺失返回None，不能仅依据status与文件名。
- [x] worker在queued切running前验证版本，非法不执行抽奖、不写完整历史；已有完成/取消/失败、保存失败提示和锁流程保持安全。
- [x] current_job_id在新根无效时清session并提示；历史选择/复用ID新库不存在时清相应引用，不报未捕获KeyError。
- [x] 临时目录测试：旧jobs与新jobs_v3独立；新根放无版本state也跳过；伪旧completed result不能展示；无效版本PID不能用于kill；合法任务可正常启动/取消/重启恢复。
- [x] 更新app路径期望v3，保留认证、路径安全、并发与进程归属检查，不删除原业务断言。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_jobs tests.test_dashboard_app tests.test_dashboard_models -v`；取消结果版本检查的变异应失败，恢复GREEN。

## 任务11：默认路径静态合同与使用文档

**Files:** docker-compose.yml、deploy/lottery-backup.service、存在时.env.example、tests/test_deployment_files.py；README.md、docs/local-usage.md、docs/dashboard-guide.md、docs/deployment.md。

**Produces:** 本机history_v3/jobs_v3，容器LOTTERY_DB_PATH=/app/data/lottery_v3.sqlite3；systemd备份服务读取同一v3源库，备份文件名使用lottery-v3前缀。

- [x] 静态合同测试期望先改v3，旧配置RED；例如现有Compose environment断言改为 `/app/data/lottery_v3.sqlite3`，backup命令期望同库。
- [x] app环境、systemd备份服务、env默认成套改v3。明确修改deploy/lottery-backup.service的ExecStart：源库为/app/data/lottery_v3.sqlite3，目标为/app/backups/lottery-v3-$(date +%%F).sqlite3，保留systemd中%%的转义。静态测试同时核对源库和目标文件名前缀。不改认证、端口、卷、secrets或部署机制，用rg定位，不批量把任意字符2换3。
- [x] 当前使用文档更新新库、jobs_v3、备份/恢复目标、新Trace结构及中文列、仅网页10万限制、默认False、单轮限制、sampling复现条件。
- [x] 新名单配置例子复制默认JSON全部必要字段，version1、4星1:3、5星单人；必须可通过PoolConfig.from_dict。说明名单通过JSON编辑，批量角色图暂仅六星。
- [x] 历史docs/changes、旧superpowers设计记录不机械替换，保留当时事实；本次实施记录说明旧库可清理、不迁移。不要给清空data/jobs的宽泛命令。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_deployment_files -v`。静态通过不代表Docker/OIDC公网实测。
- [x] 变异备份库路径回v2测试应失败，恢复GREEN；检查文档链接和git diff --check。

## 任务12：整体验收与受控上线清理

**Files:** 新docs/changes/2026-09-17-probability-core.md；design/plan补真实完成状态。不新增清理框架。

**Consumes:** 前序全部接口。实际集成授权前只在隔离工作树和临时数据目录测试，不影响用户旧服务/库。

- [x] 现有job或engine测试补集成场景：四五星名单、seed固定、初始29主抽1+赠送10，11条记录、累计30、赠送main状态不变，config/result/record/sampling为1、DB3，往返一致。
- [x] 运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest discover -v`，记录实际测试数/耗时/退出码。残余失败归责任任务修复，不删测试逃避。
- [x] CLI功能运行：

```bash
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator analyze --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1000 --seed 42 --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 1 --trials 1 --initial-pity 29 --seed 42 --trace --format json
```

- [x] 检查80主池位置、rule字符串2.0、sampling/result1、1主+10赠送、嵌套状态、非Trace无records。临时新名单配置重复同种子可复现，角色与理论字段正确，不写用户现有历史库。
- [x] 临时LOTTERY_DATA_DIR完成AppTest及真实Streamlit启动/健康检查；交互浏览器控制工具不可用，连续点击验收明确记录为未验，未用单测冒充。
- [x] rg收尾：实现无pick_six_star、旧角色概率函数、旧advance调用或旧Trace键；不要误删配置six_star_characters字段。禁止调用测试中的旧方法定义可保留。
- [x] git diff --check及范围审查通过，无多轮Trace/位置图/新依赖/认证变化/旧迁移代码。
- [x] 只读确认没有运行中的本项目网页或worker；隔离开发未停止或干扰用户服务。实际切换时仍须重新按PID及命令行确认归属。
- [x] 只读盘点旧库/任务绝对路径、PRAGMA版本、归属及实际存在的伴随文件；没有仅凭文件名删除候选。
- [x] 旧历史物理删除限定在合并后的实际本地切换阶段；当前未合并隔离分支不执行，且未递归清空data/jobs或处理外部路径。
- [x] session失效引用及新库写入由临时AppTest/job集成验证；实际用户目录仍停在只读清单，未先删数据。
- [x] 本次删除清单为空；旧库/任务仍可由当前文件恢复，未核实另有备份。实际删除时须另行记录具体清单与可恢复性。
- [x] 最终汇报区分已验证和未验/待用户步骤，不自动提交、合并或推送。

## 设计覆盖与计划自审

| design要求 | 任务 |
|---|---|
| 概率职责与统一执行器 | 2、4、5 |
| 名单、权重、角色身份 | 3、5、7 |
| 具名结果、双池状态、默认Trace | 5 |
| 两类理论递推与统一硬保底 | 4、6 |
| 版本类型、sampling、环境 | 1、8、10 |
| 中文Trace映射 | 9 |
| 新历史库不迁移与事务 | 8 |
| 新任务根、旧结果/引用隔离 | 10、12 |
| 编辑/复用/赠送名单链路 | 3、4、7、10 |
| 单轮Trace、仅网页10万上限 | 5、8、11 |
| 静态合同、文档、验收、清理 | 11、12 |

✅ 文档级自审：接口、字段、任务输入输出、删除时机、版本类型和限制范围已按design明确。没有用旧结果兼容作为验收目标。

✅ 任务1～12已执行并审查；v3库/任务结构已在临时目录验证，用户现有历史未变。全仓和CLI证据见实施记录；真实浏览器点击及服务器现场仍未验。

## 交接入口

任务1～12已完成并合并到本地 `master`。后续使用入口为 `/home/qykj/202607/test/lottery_simulator`，无需进入开发工作树。旧数据尚未清理，开发工作树与审查记录保留，未在线推送。原执行约束和任务步骤保留当时语境，最新集成状态以[本地合并记录](2026-09-18-probability-core-local-merge.md)为准。
