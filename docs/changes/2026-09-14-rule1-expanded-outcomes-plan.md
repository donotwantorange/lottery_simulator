# 规则 1 多星级与可配置奖池实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将规则 1 升级为可配置的 4/5/6 星抽取系统，支持双保底、多 UP 与具体六星角色、赠送临时池、按星级附赠奖励、精确期望、网页编辑和新版历史快照。

**Architecture:** 使用不可变 `PoolConfig` 作为规则配置快照，在现有 `DrawState` 上追加五星状态，以 `draw_once()` 统一执行星级、角色、奖励和状态转移。主池与赠送池调用相同单抽核心，赠送事件通过 `Rule1.for_bonus()` 克隆配置并覆盖固定六星率、临时五星保底和空子规则；批量引擎流式聚合，理论层对双保底状态做精确动态规划。

**Tech Stack:** Python 3.11+ 标准库、`unittest`、Streamlit 1.63、SQLite 3、现有 Docker/Caddy 部署接口；不新增依赖。

**Spec:** `docs/changes/2026-09-14-rule1-expanded-outcomes-design.md`

## Global Constraints

- 规则版本从 `1.2` 升为 `2.0`。
- 主池六星率保持：1–65 抽 0.8%，66–79 抽从 5.8% 每抽增加 5 个百分点，第 80 抽 100%。
- 五星基础率默认 8%；非五星保底抽的四星率为 `1 - p6 - p5`。
- 五星保底默认开启、阈值 10；五星或六星均满足，六星优先。
- 默认六星池 `T=9、U=1、L=3`；UP 合计占六星 50%，UP 内按权重，非 UP 等概率。
- 默认奖励A为 4/5/6 星 `1/5/25`，奖励B为 `0/2/10`；一次抽取同时发放全部已配置奖励。
- 赠送 10 抽由配置克隆的临时池执行：六星固定 0.8%、五星保底 10、状态从 0 开始、无子规则。
- `initial_five_star_pity` 是高级可选参数，默认 0；原 `initial_pity` 语义不变。
- 非 Trace 模拟不得保存逐抽对象；Trace 仍只允许单轮。
- 新历史默认写入 `data/history_v2.sqlite3`；不迁移、不读取、不覆盖或删除旧 `data/history.sqlite3`。
- 所有配置入口共用同一校验实现；后台任务接收不可变快照的 JSON 表示。
- 所有修改记录写入 `docs/changes/`；不做 SHA 验证，不执行在线推送或真实服务器部署测试。
- 每个代码任务执行 RED → GREEN → 临时错误突变/恢复 → 关联测试；最后执行完整测试。

---

### Task 1: 不可变奖池配置与默认 JSON

**Files:**
- Create: `lottery_simulator/rules/pool_config.py`
- Create: `configs/rule1_default.json`
- Create: `tests/test_pool_config.py`
- Modify: `lottery_simulator/rules/__init__.py`
- Modify: `lottery_simulator/__init__.py`

**Interfaces:**
- Produces: `FiveStarPolicy(base_probability: float, pity_enabled: bool, hard_pity: int)`。
- Produces: `SixStarCharacter(name: str, is_up: bool, is_limited: bool, up_weight: float | None = None)`。
- Produces: `RewardRule(name: str, four_star: float, five_star: float, six_star: float)`。
- Produces: `PoolConfig(up_share, five_star, six_star_characters, rewards)`，以及 `from_dict()`, `to_dict()`, `six_star_character_probabilities()`, `rewards_for()`。
- Produces: `load_pool_config(path: str | Path | None = None) -> PoolConfig`；`None` 加载 `configs/rule1_default.json`。

- [ ] **Step 1: 写配置解析、默认值和概率分配的失败测试**

```python
class PoolConfigTest(unittest.TestCase):
    def test_default_config_has_expected_roster_probabilities_and_rewards(self):
        config = load_pool_config()
        probabilities = config.six_star_character_probabilities()
        self.assertEqual(len(config.six_star_characters), 9)
        self.assertEqual(sum(c.is_up for c in config.six_star_characters), 1)
        self.assertEqual(sum(c.is_limited for c in config.six_star_characters), 3)
        self.assertAlmostEqual(probabilities["UP-A"], 0.5)
        self.assertTrue(all(
            abs(probabilities[name] - 0.0625) < 1e-12
            for name in probabilities if name != "UP-A"
        ))
        self.assertEqual(config.rewards_for(5), {"奖励A": 5.0, "奖励B": 2.0})
        self.assertEqual(PoolConfig.from_dict(config.to_dict()), config)

    def test_multiple_up_characters_share_up_probability_by_weight(self):
        raw = load_pool_config().to_dict()
        raw["six_star_characters"][1].update(
            {"is_up": True, "is_limited": True, "up_weight": 3}
        )
        config = PoolConfig.from_dict(raw)
        probabilities = config.six_star_character_probabilities()
        self.assertAlmostEqual(probabilities["UP-A"], 0.125)
        self.assertAlmostEqual(probabilities["限定-B"], 0.375)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)
```

另写 `test_invalid_character_combinations_are_rejected` 和 `test_invalid_probability_and_reward_values_are_rejected`，用子测试逐项覆盖：重复/空名称、UP 非限定、非正或非有限权重、非法 `up_share`、`up_share < 1` 却无非 UP、非法五星概率/阈值、负数/无穷奖励和布尔值冒充数字。依赖规则六星曲线的 `p6 + base_p5` 校验放在 Task 2，避免配置模块反向依赖 Rule1。

- [ ] **Step 2: 运行测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_pool_config -v`  
Expected: FAIL，模块 `lottery_simulator.rules.pool_config` 不存在。

- [ ] **Step 3: 实现最小配置模型和 JSON 加载器**

```python
@dataclass(frozen=True, slots=True)
class PoolConfig:
    up_share: float
    five_star: FiveStarPolicy
    six_star_characters: tuple[SixStarCharacter, ...]
    rewards: tuple[RewardRule, ...]

    def six_star_character_probabilities(self) -> dict[str, float]:
        ups = tuple(c for c in self.six_star_characters if c.is_up)
        non_ups = tuple(c for c in self.six_star_characters if not c.is_up)
        result = {
            c.name: self.up_share * c.up_weight / sum(u.up_weight for u in ups)
            for c in ups
        }
        if non_ups:
            share = (1.0 - self.up_share) / len(non_ups)
            result.update({c.name: share for c in non_ups})
        return result

    def rewards_for(self, rarity: int) -> dict[str, float]:
        field = {4: "four_star", 5: "five_star", 6: "six_star"}[rarity]
        return {reward.name: float(getattr(reward, field)) for reward in self.rewards}
```

`from_dict()` 负责完整边界校验并把列表转换为元组；`to_dict()` 输出可 JSON 序列化的稳定字段。默认 JSON 精确写入设计文档中的 9 名角色和两项奖励。

- [ ] **Step 4: 运行配置测试确认 GREEN**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_pool_config -v`  
Expected: PASS。

- [ ] **Step 5: 做配置校验因果检查并恢复**

临时删除“UP 必须限定”的校验，运行：

`/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_pool_config.PoolConfigTest.test_invalid_character_combinations_are_rejected -v`

Expected: FAIL；恢复校验后同一命令 PASS。

- [ ] **Step 6: 提交**

```bash
git add configs/rule1_default.json lottery_simulator/rules/pool_config.py \
  lottery_simulator/rules/__init__.py lottery_simulator/__init__.py tests/test_pool_config.py
git commit -m "feat: add configurable lottery pool"
```

### Task 2: 双保底状态、星级概率与单抽结果

**Files:**
- Modify: `lottery_simulator/rules/base.py`
- Modify: `lottery_simulator/rules/rule_1.py`
- Modify: `lottery_simulator/engine.py`
- Modify: `tests/test_rule_1.py`
- Modify: `tests/test_engine.py`

**Interfaces:**
- Consumes: `PoolConfig` and `load_pool_config()` from Task 1。
- Produces: `DrawState(misses_since_six_star=0, misses_since_five_or_higher=0)`。
- Produces: `RarityProbabilities(four_star, five_star, six_star)`。
- Produces: `DrawOutcome(rarity, six_star_character, is_up, is_limited, rewards, five_star_pity_triggered, six_star_hard_pity_triggered)`。
- Produces: `Rule1(config: PoolConfig | None = None)`, `rarity_probabilities(state)`, `advance_rarity(state, rarity)`；保留 `probability(state)` 作为六星率接口。
- Produces: `draw_once(rule: LotteryRule, state: DrawState, rng: random.Random) -> tuple[DrawOutcome, DrawState, RarityProbabilities]`。

- [ ] **Step 1: 写双保底边界和状态转移失败测试**

```python
def test_rarity_probabilities_and_five_star_pity_boundaries(self):
    rule = Rule1()
    self.assertEqual(rule.version, "2.0")
    normal = rule.rarity_probabilities(DrawState(64, 0))
    self.assertEqual(normal, RarityProbabilities(0.912, 0.08, 0.008))
    soft = rule.rarity_probabilities(DrawState(65, 0))
    self.assertAlmostEqual(soft.six_star, 0.058)
    self.assertAlmostEqual(soft.five_star, 0.08)
    self.assertAlmostEqual(soft.four_star, 0.862)
    five_pity = rule.rarity_probabilities(DrawState(65, 9))
    self.assertEqual(five_pity.four_star, 0.0)
    self.assertAlmostEqual(five_pity.five_star, 0.942)
    self.assertAlmostEqual(five_pity.six_star, 0.058)
    self.assertEqual(rule.rarity_probabilities(DrawState(79, 9)).six_star, 1.0)

def test_each_rarity_advances_both_pity_states(self):
    rule = Rule1()
    self.assertEqual(rule.advance_rarity(DrawState(4, 3), 4), DrawState(5, 4))
    self.assertEqual(rule.advance_rarity(DrawState(4, 3), 5), DrawState(5, 0))
    self.assertEqual(rule.advance_rarity(DrawState(4, 3), 6), DrawState(0, 0))
```

增加关闭五星保底测试：用 `dataclasses.replace()` 设置 `pity_enabled=False`，断言高五星计数被拒绝或规范为 0，所有非六星硬保底位置仍为基础五星 8%。

增加 `test_rule_rejects_base_five_probability_that_overflows_reachable_six_rates`：把基础五星率设为 30%，构造 `Rule1(config)` 时必须因第 79 抽 `70.8% + 30% > 100%` 被拒绝。该检查属于规则与配置的组合校验。

- [ ] **Step 2: 运行规则测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_rule_1 -v`  
Expected: FAIL，缺少第二状态、`RarityProbabilities` 和新规则方法。

- [ ] **Step 3: 扩展状态并实现规则 2.0**

```python
@dataclass(frozen=True, slots=True)
class DrawState:
    misses_since_six_star: int = 0
    misses_since_five_or_higher: int = 0

def rarity_probabilities(self, state: DrawState) -> RarityProbabilities:
    six = self.probability(state)
    five_pity = (
        self.config.five_star.pity_enabled
        and state.misses_since_five_or_higher == self.config.five_star.hard_pity - 1
    )
    five = 1.0 - six if five_pity else self.config.five_star.base_probability
    return RarityProbabilities(max(0.0, 1.0 - six - five), five, six)

def advance_rarity(self, state: DrawState, rarity: int) -> DrawState:
    if rarity == 6:
        return DrawState(0, 0)
    six_misses = state.misses_since_six_star + 1
    five_misses = 0 if rarity == 5 else state.misses_since_five_or_higher + 1
    return DrawState(six_misses, five_misses)
```

保留 `advance(state, is_six_star)` 供六星等待时间分析使用；`False` 仅推进六星计数，五星计数不参与该旧接口的判断。

- [ ] **Step 4: 写结构化单抽失败测试**

使用测试内固定随机序列分别覆盖四星、五星、六星角色选择；断言六星结果含角色与 UP/限定标记，所有结果都含两个奖励，五星保底抽即使命中六星也将 `five_star_pity_triggered=True`。测试 helper 和测试名明确为：

```python
class SequenceRandom:
    def __init__(self, values):
        self.values = iter(values)

    def random(self):
        return next(self.values)

def test_draw_once_returns_rarity_character_rewards_and_state(self):
    outcome, state_after, probabilities = draw_once(
        Rule1(), DrawState(9, 9), SequenceRandom((0.0, 0.0))
    )
    self.assertEqual(outcome.rarity, 6)
    self.assertEqual(outcome.six_star_character, "UP-A")
    self.assertTrue(outcome.is_up)
    self.assertTrue(outcome.is_limited)
    self.assertTrue(outcome.five_star_pity_triggered)
    self.assertEqual(outcome.rewards, {"奖励A": 25.0, "奖励B": 10.0})
    self.assertAlmostEqual(sum(astuple(probabilities)), 1.0)
    self.assertEqual(state_after, DrawState(0, 0))
```

- [ ] **Step 5: 运行单抽测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_engine.EngineTest.test_draw_once_returns_rarity_character_rewards_and_state -v`  
Expected: FAIL，`draw_once` 尚不存在。

- [ ] **Step 6: 实现 `draw_once()` 最小逻辑**

```python
def draw_once(rule, state, rng):
    probabilities = rule.rarity_probabilities(state)
    roll = rng.random()
    rarity = 6 if roll < probabilities.six_star else (
        5 if roll < probabilities.six_star + probabilities.five_star else 4
    )
    character = rule.pick_six_star(rng.random()) if rarity == 6 else None
    outcome = DrawOutcome(
        rarity=rarity,
        six_star_character=character.name if character else None,
        is_up=bool(character and character.is_up),
        is_limited=bool(character and character.is_limited),
        rewards=rule.config.rewards_for(rarity),
        five_star_pity_triggered=rule.five_star_pity_active(state),
        six_star_hard_pity_triggered=state.misses_since_six_star == rule.max_pity - 1,
    )
    return outcome, rule.advance_rarity(state, rarity), probabilities
```

- [ ] **Step 7: 运行 Task 2 关联测试并做概率突变恢复**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_rule_1 tests.test_engine -v`  
Expected: PASS。

临时让五星保底抽仍返回基础 8%，运行 `test_rarity_probabilities_and_five_star_pity_boundaries`，确认 FAIL；恢复后 PASS。

- [ ] **Step 8: 提交**

```bash
git add lottery_simulator/rules/base.py lottery_simulator/rules/rule_1.py \
  lottery_simulator/engine.py tests/test_rule_1.py tests/test_engine.py
git commit -m "feat: add rarity outcomes and five star pity"
```

### Task 3: 赠送十抽临时池

**Files:**
- Modify: `lottery_simulator/rules/base.py`
- Modify: `lottery_simulator/rules/first_thirty_bonus.py`
- Modify: `lottery_simulator/rules/rule_1.py`
- Modify: `lottery_simulator/engine.py`
- Modify: `tests/test_bonus_rule.py`
- Modify: `tests/test_engine.py`

**Interfaces:**
- Produces: `BonusEvent(name, draws, six_star_probability, five_star_hard_pity)`；`six_star_probability` 在此事件中表示临时池固定六星率，字段名保留现有兼容性。
- Produces: `Rule1.for_bonus(event: BonusEvent) -> Rule1`，返回共享角色/奖励配置、固定六星率、强制五星保底、空 `subrules` 的规则实例。
- Consumes: Task 2 的 `draw_once()`；临时状态始终 `DrawState()`。

- [ ] **Step 1: 写临时池配置与隔离失败测试**

```python
class ConstantRandom:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value

def test_bonus_event_builds_isolated_temporary_pool(self):
    main = Rule1()
    event = FirstThirtyBonusRule().events_after_main_draw(30)[0]
    temporary = main.for_bonus(event)
    self.assertIs(temporary.config.six_star_characters,
                  main.config.six_star_characters)
    self.assertIs(temporary.config.rewards, main.config.rewards)
    self.assertEqual(temporary.probability(DrawState(9, 9)), 0.008)
    self.assertTrue(temporary.config.five_star.pity_enabled)
    self.assertEqual(temporary.config.five_star.hard_pity, 10)
    self.assertEqual(temporary.subrules, ())

def test_temporary_pool_guarantees_at_least_five_star_in_ten_draws(self):
    temporary = Rule1().for_bonus(
        FirstThirtyBonusRule().events_after_main_draw(30)[0]
    )
    state = DrawState()
    rarities = []
    rng = ConstantRandom(0.999)
    for _ in range(10):
        outcome, state, _ = draw_once(temporary, state, rng)
        rarities.append(outcome.rarity)
    self.assertEqual(rarities, [4] * 9 + [5])

def test_bonus_records_do_not_change_main_double_pity(self):
    result = simulate(Rule1(), draws=2, trials=1, seed=42,
                      initial_pity=29, initial_five_star_pity=8,
                      collect_records=True)
    bonus = [record for record in result.records if record.source == "bonus"]
    self.assertEqual(len(bonus), 10)
    self.assertEqual(len({record.state_after for record in bonus}), 1)
    self.assertEqual(bonus[0].source_state_before, DrawState())
    self.assertTrue(any(
        record.source_state_after.misses_since_five_or_higher == 0
        for record in bonus
    ))
```

`ConstantRandom` 是测试文件内返回同一浮点值的最小 helper；它不进入生产代码。

- [ ] **Step 2: 运行赠送规则测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_bonus_rule -v`  
Expected: FAIL，事件缺少临时池字段或 `for_bonus()` 不存在。

- [ ] **Step 3: 实现事件覆盖与配置克隆**

```python
def for_bonus(self, event: BonusEvent) -> "Rule1":
    temporary_config = replace(
        self.config,
        five_star=replace(
            self.config.five_star,
            pity_enabled=True,
            hard_pity=event.five_star_hard_pity,
        ),
    )
    return Rule1(
        config=temporary_config,
        fixed_six_star_probability=event.six_star_probability,
        subrules=(),
    )
```

引擎触发事件时创建一次临时规则和临时状态，连续调用 10 次 `draw_once()`，然后丢弃；主池 `state` 和 `main_draws_completed` 在赠送期间保持原值。

- [ ] **Step 4: 运行赠送和引擎测试并做隔离突变恢复**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_bonus_rule tests.test_engine -v`  
Expected: PASS。

临时把赠送池状态改为主池 `state`，运行 `test_bonus_records_do_not_change_main_double_pity`，确认 FAIL；恢复独立 `DrawState()` 后 PASS。

- [ ] **Step 5: 提交**

```bash
git add lottery_simulator/rules/base.py lottery_simulator/rules/first_thirty_bonus.py \
  lottery_simulator/rules/rule_1.py lottery_simulator/engine.py \
  tests/test_bonus_rule.py tests/test_engine.py
git commit -m "feat: run bonus draws in a temporary pool"
```

### Task 4: 流式批量汇总与结构化 Trace

**Files:**
- Modify: `lottery_simulator/engine.py`
- Modify: `tests/test_engine.py`

**Interfaces:**
- Produces: `SimulationResult.source_summaries: dict[str, dict]`，键为 `main/bonus/total`。
- Produces: `SimulationResult.source_distributions: dict[str, dict]`，精确结构为 `{source: {"rarity_counts": {rarity: {count_string: frequency}}, "reward_totals": {reward_name: {total_string: frequency}}}}`。
- Produces: `SimulationResult.at_least_one_rates: dict[str, dict[str, float]]`，第一层键为 `main/bonus/total`，第二层键为 `five_or_higher/six_star/up_six_star/limited_six_star`；并保存 `pool_config`, `initial_five_star_pity`。
- 每个 source summary 包含 `draws`, `mean_rarity_counts`, `mean_six_star_categories`, `mean_character_counts`, `mean_rewards`, `mean_pity_triggers`。
- Trace `DrawRecord` 增加 `rarity`, `six_star_character`, `is_up`, `is_limited`, `rewards`, `rarity_probabilities`, `source_state_before`, `source_state_after`, `five_star_pity_triggered`, `six_star_hard_pity_triggered`。现有 `state_after` 对主池和赠送都继续表示主池状态；赠送记录因此能同时显示临时池推进和主池保持不变。保留现有来源和六星兼容字段。

- [ ] **Step 1: 写统计守恒、来源拆分和非 Trace 内存失败测试**

```python
def test_structured_aggregates_conserve_draws_characters_and_rewards(self):
    result = simulate(Rule1(), draws=30, trials=20, seed=42,
                      collect_records=False)
    for source in ("main", "bonus", "total"):
        summary = result.source_summaries[source]
        self.assertAlmostEqual(sum(summary["mean_rarity_counts"].values()),
                               summary["draws"])
        self.assertAlmostEqual(
            sum(summary["mean_character_counts"].values()),
            summary["mean_rarity_counts"]["6"],
        )
    total = result.source_summaries["total"]
    expected_reward_a = (
        total["mean_rarity_counts"]["4"]
        + 5 * total["mean_rarity_counts"]["5"]
        + 25 * total["mean_rarity_counts"]["6"]
    )
    self.assertAlmostEqual(total["mean_rewards"]["奖励A"], expected_reward_a)
    self.assertEqual(result.records, ())

def test_bonus_ten_draws_have_at_least_one_five_or_six_per_trial(self):
    result = simulate(Rule1(), draws=30, trials=100, seed=7,
                      collect_records=False)
    bonus = result.source_summaries["bonus"]["mean_rarity_counts"]
    self.assertGreaterEqual(round((bonus["5"] + bonus["6"]) * result.trials), 100)
```

Trace 测试断言第 30 次主抽后紧跟 10 条 `source="bonus"`，赠送记录的主池前后双状态完全相同，且每条记录的星级概率之和为 1。

- [ ] **Step 2: 运行引擎测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_engine -v`  
Expected: FAIL，结构化汇总和 Trace 字段不存在。

- [ ] **Step 3: 实现内部逐轮计数器和结果字段**

```python
def _empty_counts(config):
    return {
        "rarities": {"4": 0, "5": 0, "6": 0},
        "categories": {"up": 0, "other_limited": 0, "standard": 0},
        "characters": {c.name: 0 for c in config.six_star_characters},
        "rewards": {reward.name: 0.0 for reward in config.rewards},
        "pity_triggers": {"five_star": 0, "six_star_hard": 0},
    }
```

每轮为 main/bonus/total 创建小型字典，逐抽原地累加；轮末更新总量和分布。只有 `collect_records=True` 时构造 `DrawRecord`。最终用总量除以 `trials` 生成均值，并从结构化字段派生现有 `mean_six_stars`、`count_distribution` 等兼容字段。

- [ ] **Step 4: 运行引擎测试与流式突变恢复**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_engine -v`  
Expected: PASS。

临时在非 Trace 路径追加一条 record，运行 `test_large_single_trial_can_explicitly_skip_record_collection`，确认 FAIL；恢复后 PASS。

- [ ] **Step 5: 提交**

```bash
git add lottery_simulator/engine.py tests/test_engine.py
git commit -m "feat: aggregate structured lottery outcomes"
```

### Task 5: 双状态精确期望

**Files:**
- Modify: `lottery_simulator/analysis.py`
- Modify: `lottery_simulator/engine.py`
- Modify: `lottery_simulator/__init__.py`
- Modify: `tests/test_analysis.py`
- Modify: `tests/test_engine.py`

**Interfaces:**
- Produces: `PoolExpectations(rarity_counts, six_star_categories, character_counts, rewards, pity_triggers)`。
- Produces: `expected_pool_results(rule, draws, initial_state=DrawState()) -> PoolExpectations`。
- Produces: `expected_simulation_results(rule, draws, initial_pity=0, initial_five_star_pity=0) -> dict[str, PoolExpectations]`，键为 `main/bonus/total`。
- `SimulationResult.theoretical_source_summaries` 保存与模拟 source summary 对齐的期望字段。

- [ ] **Step 1: 写独立穷举对照失败测试**

在测试中使用 `fractions.Fraction` 和 `itertools.product((4, 5, 6), repeat=draws)` 独立枚举 1–5 抽，按设计公式手算每条路径权重和状态转移；不得调用生产 `rarity_probabilities()` 计算期望侧概率：

```python
def enumerate_pool_expectations(draws, initial, config):
    expected = {"4": Fraction(0), "5": Fraction(0), "6": Fraction(0)}
    base_five = Fraction(str(config.five_star.base_probability))
    for outcomes in product((4, 5, 6), repeat=draws):
        state = initial
        weight = Fraction(1)
        for rarity in outcomes:
            pull = state.misses_since_six_star + 1
            if pull == 80:
                six = Fraction(1)
            elif pull >= 66:
                six = Fraction(8, 1000) + (pull - 65) * Fraction(5, 100)
            else:
                six = Fraction(8, 1000)
            five_pity = (
                config.five_star.pity_enabled
                and state.misses_since_five_or_higher
                    == config.five_star.hard_pity - 1
            )
            five = 1 - six if five_pity else base_five
            probabilities = {4: 1 - six - five, 5: five, 6: six}
            weight *= probabilities[rarity]
            if weight == 0:
                break
            state = (
                DrawState(0, 0) if rarity == 6 else
                DrawState(state.misses_since_six_star + 1,
                          0 if rarity == 5 else
                          state.misses_since_five_or_higher + 1)
            )
        for rarity in outcomes:
            expected[str(rarity)] += weight
    return {rarity: float(value) for rarity, value in expected.items()}

def test_double_state_dp_matches_independent_exhaustive_outcomes(self):
    rule = Rule1()
    for initial in (DrawState(0, 0), DrawState(64, 8), DrawState(65, 9)):
        for draws in range(1, 6):
            with self.subTest(initial=initial, draws=draws):
                actual = expected_pool_results(rule, draws, initial)
                expected = enumerate_pool_expectations(draws, initial, rule.config)
                self.assertEqual(actual.rarity_counts.keys(), expected.keys())
                for rarity in ("4", "5", "6"):
                    self.assertAlmostEqual(actual.rarity_counts[rarity],
                                           expected[rarity], places=12)
```

另断言默认配置下角色期望之和等于六星期望、UP/其他限定/常驻之和等于六星期望、奖励期望等于星级期望的线性组合；跨过累计主抽 30 时 bonus 期望恰好来自一次 10 抽临时池。

- [ ] **Step 2: 运行分析测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_analysis -v`  
Expected: FAIL，`PoolExpectations` 和双状态分析函数不存在。

- [ ] **Step 3: 实现双状态稀疏动态规划**

```python
states = {initial_state: 1.0}
for _ in range(draws):
    next_states = {}
    for state, mass in states.items():
        probabilities = rule.rarity_probabilities(state)
        for rarity, probability in (
            (4, probabilities.four_star),
            (5, probabilities.five_star),
            (6, probabilities.six_star),
        ):
            if probability == 0.0:
                continue
            branch = mass * probability
            rarity_counts[str(rarity)] += branch
            after = rule.advance_rarity(state, rarity)
            next_states[after] = next_states.get(after, 0.0) + branch
    states = next_states
```

五星保底触发期望在进入分支前按状态质量累计一次；六星硬保底同理。六星类别、角色和奖励从星级期望及配置条件概率精确派生。`expected_simulation_results()` 仅在主抽范围跨过第 30 抽时建立一次赠送规则并计算 10 抽期望。

- [ ] **Step 4: 接入引擎理论结果并运行关联测试**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_analysis tests.test_engine -v`  
Expected: PASS。

- [ ] **Step 5: 做 DP 状态转移突变恢复**

临时让五星分支不清零五星状态，运行独立穷举对照测试，确认 FAIL；恢复后同一测试 PASS。

- [ ] **Step 6: 提交**

```bash
git add lottery_simulator/analysis.py lottery_simulator/engine.py \
  lottery_simulator/__init__.py tests/test_analysis.py tests/test_engine.py
git commit -m "feat: analyze double pity expectations"
```

### Task 6: CLI 配置入口与中文输出

**Files:**
- Modify: `lottery_simulator/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_pool_config()`、`Rule1(config=...)`、Task 4/5 的结构化结果。
- Produces: `simulate --pool-config PATH --initial-five-star-pity N`。
- Produces: `analyze --pool-config PATH`，输出六星等待分析以及配置摘要。
- JSON 输出包含 `pool_config`, `source_summaries`, `theoretical_source_summaries`, `source_distributions`, `at_least_one_rates` 和扩展 Trace。

- [ ] **Step 1: 写 CLI 失败测试**

```python
def test_cli_loads_pool_config_and_reports_structured_results(self):
    with TemporaryDirectory() as directory:
        path = Path(directory) / "pool.json"
        raw = load_pool_config().to_dict()
        raw["up_share"] = 0.6
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        code, output = self.run_cli(
            "simulate", "--draws", "10", "--trials", "2", "--seed", "42",
            "--pool-config", str(path), "--initial-five-star-pity", "3",
            "--format", "json",
        )
    self.assertEqual(code, 0)
    payload = json.loads(output)
    self.assertEqual(payload["rule_version"], "2.0")
    self.assertEqual(payload["pool_config"]["up_share"], 0.6)
    self.assertEqual(payload["initial_five_star_pity"], 3)
    self.assertIn("rarity_counts", payload["theoretical_source_summaries"]["total"])
```

增加文本输出标签、配置文件不存在/JSON 错误/语义错误、五星初始值越界、Trace 新字段和默认配置回归测试。

- [ ] **Step 2: 运行 CLI 测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_cli -v`  
Expected: FAIL，解析器不认识新参数或结果缺字段。

- [ ] **Step 3: 实现 CLI 参数、规则构造和输出**

```python
simulation.add_argument("--pool-config")
simulation.add_argument("--initial-five-star-pity", type=int, default=0)
analyze.add_argument("--pool-config")

config = load_pool_config(args.pool_config)
rule = RULES[args.rule](config=config)
result = simulate(
    rule,
    draws=args.draws,
    trials=args.trials,
    seed=args.seed,
    initial_pity=args.initial_pity,
    initial_five_star_pity=args.initial_five_star_pity,
    collect_records=args.trace,
)
```

文本输出按“星级 → 六星类别 → 角色 → 奖励 → 保底 → Trace”分段；角色和奖励由配置动态遍历，不硬编码 9 名角色或两个奖励。

- [ ] **Step 4: 运行 CLI 和真实模块入口测试**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_cli -v`  
Expected: PASS。

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 10 --trials 1 --seed 42 --trace --format json`  
Expected: exit 0；10 次主抽，若从零开始不触发赠送；records 每条含 rarity、rewards 和双保底状态。

- [ ] **Step 5: 提交**

```bash
git add lottery_simulator/cli.py tests/test_cli.py
git commit -m "feat: expose configurable pools in cli"
```

### Task 7: 全新 v2 历史数据库

**Files:**
- Modify: `dashboard/repository.py`
- Modify: `tests/test_repository.py`
- Modify: `tests/test_dashboard_app.py`

**Interfaces:**
- `HistoryRepository.initialize()` 只接受空数据库或新版 `PRAGMA user_version = 2`。
- `simulation_runs` 保存常用筛选列、`pool_config_json` 和无 records 的 `result_json`。
- `draw_records(run_id, draw_index, record_json)` 逐条保存完整 Trace JSON，不为动态奖励创建列。
- 旧 `user_version = 1` 数据库抛出安全的版本不兼容错误，不执行任何写操作。

- [ ] **Step 1: 写新库往返和旧库拒绝失败测试**

```python
def test_initialize_rejects_old_schema_without_modifying_it(self):
    with closing(sqlite3.connect(self.path)) as connection:
        connection.execute("CREATE TABLE legacy_marker(value TEXT)")
        connection.execute("INSERT INTO legacy_marker VALUES ('keep')")
        connection.execute("PRAGMA user_version = 1")
    with self.assertRaisesRegex(ValueError, "版本不兼容"):
        self.repository.initialize()
    with closing(sqlite3.connect(self.path)) as connection:
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT value FROM legacy_marker").fetchone()[0],
                         "keep")

def test_v2_round_trip_preserves_config_summary_and_trace(self):
    self.repository.initialize()
    run_id = self.repository.save_run(self.payload, trace_enabled=True)
    run = self.repository.get_run(run_id, include_records=True)
    self.assertEqual(run["pool_config"], self.payload["pool_config"])
    self.assertEqual(run["records"], self.payload["records"])
    self.assertEqual(run["schema_version"], 2)
```

- [ ] **Step 2: 运行 repository 测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_repository -v`  
Expected: FAIL，当前 schema 为 1 且缺少配置/结构化 Trace 存储。

- [ ] **Step 3: 用全新 schema 2 替换建库定义**

```sql
CREATE TABLE simulation_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    main_draws INTEGER NOT NULL,
    trials INTEGER NOT NULL,
    initial_pity INTEGER NOT NULL,
    initial_five_star_pity INTEGER NOT NULL,
    seed TEXT NOT NULL,
    trace_enabled INTEGER NOT NULL CHECK (trace_enabled IN (0, 1)),
    pool_config_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 2)
);
CREATE TABLE draw_records (
    run_id TEXT NOT NULL REFERENCES simulation_runs(id) ON DELETE CASCADE,
    draw_index INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (run_id, draw_index)
);
PRAGMA user_version = 2;
```

保留现有事务、外键、无符号 64 位 seed 文本存储、分页白名单、级联删除、在线备份和写入失败整体回滚行为。

- [ ] **Step 4: 运行 repository 与页面错误边界测试**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_repository tests.test_dashboard_app.DashboardAppTest.test_repository_initialization_failure_shows_safe_read_only_error_before_business_ui -v`  
Expected: PASS。

- [ ] **Step 5: 做旧库拒绝因果检查并恢复**

临时允许 `user_version=1` 继续初始化，运行 `test_initialize_rejects_old_schema_without_modifying_it`，确认 FAIL；恢复严格拒绝后 PASS。

- [ ] **Step 6: 提交**

```bash
git add dashboard/repository.py tests/test_repository.py tests/test_dashboard_app.py
git commit -m "feat: store rich results in v2 history"
```

### Task 8: 网页配置编辑、任务参数和历史复用

**Files:**
- Create: `dashboard/views/configuration.py`
- Create: `tests/test_configuration_view.py`
- Modify: `dashboard/models.py`
- Modify: `dashboard/jobs.py`
- Modify: `dashboard/worker.py`
- Modify: `dashboard/app.py`
- Modify: `dashboard/views/history.py`
- Modify: `tests/test_dashboard_models.py`
- Modify: `tests/test_jobs.py`
- Modify: `tests/test_dashboard_app.py`

**Interfaces:**
- `RunParameters` 末尾追加 `initial_five_star_pity: int = 0` 和 `pool_config: dict | None = None`，保留现有位置参数顺序。
- Produces: `config_to_editor_rows(config)`, `editor_rows_to_config(...)`, `render_pool_config_editor(st) -> PoolConfig`。
- `validate_parameters_for_active_rule()` 从参数快照构造 `PoolConfig` 和 `Rule1`，同时校验两个保底范围。
- worker 用参数内配置创建规则，不重新读取默认文件。
- `apply_pending_reuse()` 恢复新历史的配置和初始五星保底。

- [ ] **Step 1: 写纯配置编辑转换失败测试**

```python
def test_editor_rows_round_trip_and_preserve_dynamic_entries(self):
    original = load_pool_config()
    characters, rewards = config_to_editor_rows(original)
    characters.append({
        "角色名称": "UP-J", "是否UP": True, "是否限定": True, "UP权重": 2.0
    })
    rebuilt = editor_rows_to_config(
        up_share=0.5,
        five_star_probability=0.08,
        five_star_pity_enabled=True,
        five_star_hard_pity=10,
        character_rows=characters,
        reward_rows=rewards,
    )
    self.assertEqual(len(rebuilt.six_star_characters), 10)
    self.assertEqual(rebuilt.six_star_characters[-1].name, "UP-J")
    self.assertEqual(PoolConfig.from_dict(rebuilt.to_dict()), rebuilt)
```

增加导入 JSON 错误返回中文消息、非 UP 行空权重规范为 `None`、UP 行缺权重拒绝、奖励增删往返测试。

- [ ] **Step 2: 写任务参数快照失败测试**

```python
def test_worker_uses_serialized_pool_config_and_initial_five_pity(self):
    config = load_pool_config().to_dict()
    config["up_share"] = 0.6
    parameters = RunParameters("rule1", 10, 1, 0, 42, True, 7, config)
    state = self.manager.start(parameters, synchronous=True)
    payload = self.manager.get_result(state.job_id)
    self.assertEqual(payload["pool_config"]["up_share"], 0.6)
    self.assertEqual(payload["initial_five_star_pity"], 7)
```

- [ ] **Step 3: 运行配置、模型和任务测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_configuration_view tests.test_dashboard_models tests.test_jobs -v`  
Expected: FAIL，新视图、参数字段和 worker 配置传递不存在。

- [ ] **Step 4: 实现参数模型和统一校验**

```python
@dataclass(frozen=True, slots=True)
class RunParameters:
    rule_name: str
    draws: int
    trials: int
    initial_pity: int
    seed: int | None
    trace: bool
    initial_five_star_pity: int = 0
    pool_config: dict[str, Any] | None = None
```

`validate_parameters_for_active_rule()` 使用 `PoolConfig.from_dict()` 或默认配置创建当前规则；验证 `initial_pity < rule.max_pity`，五星开启时验证 `initial_five_star_pity < hard_pity`，关闭时要求或规范为 0。worker 必须只使用序列化参数，不读取页面 session state。

- [ ] **Step 5: 实现网页配置编辑器和入口布局**

`configuration.py` 把中文表格列与稳定 JSON 字段互转。`app.py` 在侧栏保留核心参数，在“高级设置”放初始五星保底，在“奖池与奖励设置”调用两个 `st.data_editor`，并提供恢复默认、上传 JSON 和下载 JSON。点击开始模拟时先将编辑值构造成 `PoolConfig`，再创建任务。

```python
def editor_rows_to_config(*, up_share, five_star_probability,
                          five_star_pity_enabled, five_star_hard_pity,
                          character_rows, reward_rows):
    return PoolConfig.from_dict({
        "up_share": up_share,
        "five_star": {
            "base_probability": five_star_probability,
            "pity_enabled": five_star_pity_enabled,
            "hard_pity": five_star_hard_pity,
        },
        "six_star_characters": [
            {
                "name": row["角色名称"],
                "is_up": row["是否UP"],
                "is_limited": row["是否限定"],
                "up_weight": row["UP权重"] if row["是否UP"] else None,
            }
            for row in character_rows
        ],
        "rewards": [
            {
                "name": row["奖励名称"],
                "four_star": row["四星"],
                "five_star": row["五星"],
                "six_star": row["六星"],
            }
            for row in reward_rows
        ],
    })

with st.expander("奖池与奖励设置"):
    character_rows = st.data_editor(
        st.session_state["pool_character_rows"], num_rows="dynamic",
        key="pool_character_editor",
    )
    reward_rows = st.data_editor(
        st.session_state["pool_reward_rows"], num_rows="dynamic",
        key="pool_reward_editor",
    )
```

本地默认数据库路径同时改为：

```python
database_path = Path(os.environ.get(
    "LOTTERY_DB_PATH", data_dir / "history_v2.sqlite3"
))
```

- [ ] **Step 6: 接入历史复用和页面测试**

`apply_pending_reuse()` 更新 `initial_five_star_pity` 和配置编辑器 session state；旧库不进入该流程。使用 Streamlit `AppTest` 验证默认折叠区、动态表格、无效配置在建 job 前显示错误、完成任务保存配置，以及复用后字段恢复。

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_configuration_view tests.test_dashboard_models tests.test_jobs tests.test_dashboard_app -v`  
Expected: PASS。

- [ ] **Step 7: 做 worker 快照突变恢复**

临时让 worker 调用 `load_pool_config()` 而不是参数快照，运行 `test_worker_uses_serialized_pool_config_and_initial_five_pity`，确认 FAIL；恢复后 PASS。

- [ ] **Step 8: 提交**

```bash
git add dashboard/views/configuration.py dashboard/models.py dashboard/jobs.py \
  dashboard/worker.py dashboard/app.py dashboard/views/history.py \
  tests/test_configuration_view.py tests/test_dashboard_models.py \
  tests/test_jobs.py tests/test_dashboard_app.py
git commit -m "feat: edit pool configuration in dashboard"
```

### Task 9: 新结果图表与 Trace 展示

**Files:**
- Modify: `dashboard/charts.py`
- Modify: `dashboard/views/simulation.py`
- Modify: `tests/test_charts.py`
- Modify: `tests/test_simulation_view.py`
- Modify: `tests/test_dashboard_app.py`

**Interfaces:**
- Produces: `rarity_comparison_rows(payload, source)`。
- Produces: `six_star_category_rows(payload, source)`。
- Produces: `character_rows(payload, source)`。
- Produces: `reward_rows(payload, source)` 和 `reward_distribution_rows(payload, source, reward_name)`。
- Produces: `pity_rows(payload, source)`。
- `render_result()` 使用 `总览/六星构成/具体角色/附赠奖励/保底统计/Trace` 六个结果区域，并保留 JSON 下载。

- [ ] **Step 1: 写图表纯数据映射失败测试**

```python
def test_character_rows_compare_simulation_and_theory(self):
    rows = character_rows(self.payload, "total")
    self.assertEqual([row["角色"] for row in rows], [
        "UP-A", "限定-B", "限定-C", "常驻-D", "常驻-E",
        "常驻-F", "常驻-G", "常驻-H", "常驻-I",
    ])
    self.assertEqual(rows[0]["类型"], "UP限定")
    self.assertAlmostEqual(rows[0]["六星内理论占比"], 0.5)
    self.assertAlmostEqual(sum(row["理论期望"] for row in rows),
                           self.payload["theoretical_source_summaries"]["total"]
                           ["rarity_counts"]["6"])
```

分别用字面量 payload 覆盖星级、类别、奖励、保底和奖励分布的字段映射，不在测试期望中调用生产 helper。

- [ ] **Step 2: 运行 chart 测试确认 RED**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_charts -v`  
Expected: FAIL，新 helper 不存在。

- [ ] **Step 3: 实现图表行转换 helper**

每个 helper 只把 payload 转换为数字行，不调用 Streamlit；角色顺序遵循 `pool_config.six_star_characters`，动态奖励顺序遵循 `pool_config.rewards`。分布 JSON 的数字键按数值排序，不按字符串排序。

```python
def character_rows(payload, source):
    config = PoolConfig.from_dict(payload["pool_config"])
    probabilities = config.six_star_character_probabilities()
    simulated = payload["source_summaries"][source]["mean_character_counts"]
    theoretical = payload["theoretical_source_summaries"][source]["character_counts"]
    six_mean = payload["source_summaries"][source]["mean_rarity_counts"]["6"]
    return [
        {
            "角色": character.name,
            "类型": "UP限定" if character.is_up else
                    ("其他限定" if character.is_limited else "常驻"),
            "模拟均值": simulated[character.name],
            "理论期望": theoretical[character.name],
            "六星内实际占比": (
                simulated[character.name] / six_mean if six_mean else None
            ),
            "六星内理论占比": probabilities[character.name],
        }
        for character in config.six_star_characters
    ]

def reward_rows(payload, source):
    simulated = payload["source_summaries"][source]["mean_rewards"]
    theoretical = payload["theoretical_source_summaries"][source]["rewards"]
    return [
        {"奖励": name, "模拟均值": simulated[name], "理论期望": theoretical[name]}
        for name in simulated
    ]
```

- [ ] **Step 4: 写并实现结果渲染失败测试**

扩展现有 `RecordingStreamlit`，断言六个区域标题、主池/赠送/总计切换数据、具体角色 9 行、奖励A/B、保底指标、Trace 新字段和 UTF-8 JSON 下载。非 Trace 时绝不把 records 传给 dataframe。

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_simulation_view -v`  
Expected before implementation: FAIL，新标签和图表缺失。实现 `render_result()` 后 Expected: PASS。

- [ ] **Step 5: 运行结果页面关联测试**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_charts tests.test_simulation_view tests.test_dashboard_app -v`  
Expected: PASS；Streamlit 裸模式已有 `missing ScriptRunContext` 提示可以存在，但不得出现弃用参数警告或测试失败。

- [ ] **Step 6: 提交**

```bash
git add dashboard/charts.py dashboard/views/simulation.py \
  tests/test_charts.py tests/test_simulation_view.py tests/test_dashboard_app.py
git commit -m "feat: visualize rarity roles and rewards"
```

### Task 10: 新数据库路径、说明文档与最终验收

**Files:**
- Modify: `docker-compose.yml`
- Modify: `deploy/lottery-backup.service`
- Modify: `tests/test_deployment_files.py`
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Create: `docs/changes/2026-09-14-rule1-expanded-outcomes.md`
- Modify: `docs/changes/2026-09-14-rule1-expanded-outcomes-design.md`

**Interfaces:**
- Compose app 和备份服务统一使用 `/app/data/lottery_v2.sqlite3`。
- 本地开发默认使用 `data/history_v2.sqlite3`。
- README 给出默认配置、JSON 修改、CLI、网页、双保底和结果字段的中文使用示例。
- 变更记录包含每个任务提交、RED/GREEN/突变恢复证据和未执行的服务器现场测试边界。

- [ ] **Step 1: 更新部署静态合同测试并确认 RED**

```python
def test_compose_and_backup_use_v2_database_path(self):
    compose = self.compose_services()
    self.assertEqual(
        compose["app"]["environment"]["LOTTERY_DB_PATH"],
        "/app/data/lottery_v2.sqlite3",
    )
    service = (ROOT / "deploy/lottery-backup.service").read_text()
    self.assertIn(
        "/app/data/lottery_v2.sqlite3 /app/backups/lottery-v2-$(date +%%F).sqlite3",
        service,
    )
```

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_deployment_files.DeploymentFilesTest.test_compose_and_backup_use_v2_database_path -v`  
Expected: FAIL，当前仍为 `/app/data/lottery.sqlite3`。

- [ ] **Step 2: 更新 Compose、备份服务和部署文档路径**

把运行、备份、恢复、完整性检查和升级示例中的活动库统一改成 `lottery_v2.sqlite3`；明确旧 `lottery.sqlite3` 不迁移、不删除。不得声称 Docker/Caddy、公网 HTTPS 或 OIDC 已实际运行验证。

- [ ] **Step 3: 更新 README 与变更记录**

README 至少给出：

```bash
python3 -m lottery_simulator simulate --draws 100 --trials 100000 \
  --pool-config configs/rule1_default.json --seed 42
```

说明网页表格、JSON 导入导出、初始五星保底、星级联动、多 UP、具体角色、奖励和赠送临时池。将设计文档状态改为“已实现”仅在完整测试通过之后。

- [ ] **Step 4: 运行完整自动化测试**

Run: `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest discover -v`  
Expected: 所有测试 PASS，0 failures，0 errors。

- [ ] **Step 5: 运行三个功能验收命令**

```bash
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator analyze --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1000 --seed 42 --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1 --seed 42 --trace
```

Expected:

- analyze 显示规则版本 2.0、默认配置摘要和 80 行六星概率表；
- 批量结果每轮为 30 主抽 + 10 赠送，星级/角色/奖励统计守恒；
- Trace 在主抽 30 后显示 10 条赠送记录，含星级、角色、奖励和双保底，赠送期间主池状态不变。

- [ ] **Step 6: 最终差异与工作区检查**

Run: `git diff --check`  
Expected: exit 0。

Run: `git status --short`  
Expected: 只显示本任务文档的预期修改；无数据库、任务状态、secrets 或其他运行数据被跟踪。

- [ ] **Step 7: 提交**

```bash
git add docker-compose.yml deploy/lottery-backup.service tests/test_deployment_files.py \
  README.md docs/deployment.md \
  docs/changes/2026-09-14-rule1-expanded-outcomes.md \
  docs/changes/2026-09-14-rule1-expanded-outcomes-design.md
git commit -m "docs: complete rule1 outcome expansion"
```

- [ ] **Step 8: 请求最终代码审查**

使用 `superpowers:requesting-code-review` 检查设计逐项覆盖、统计守恒、配置快照、临时池隔离、历史写入安全和非 Trace 内存边界。修复审查发现后重新运行完整测试，再进入本地合并/保留分支选择；除非用户另行授权，不推送 GitHub。
