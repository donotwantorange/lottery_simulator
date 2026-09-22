# 抽取概率核心职责重构设计

## 1. 状态、确认要求与边界

最新集成状态：已按用户授权合并到本地 `master`，合并后311项测试通过，未在线推送，旧历史保留。详见[本地合并记录](2026-09-18-probability-core-local-merge.md)；下文的实施授权边界保留设计阶段语境。

设计内容已确认并完成实现。任务1～12均已实施和独立审查，实际证据见[实施记录](2026-09-17-probability-core.md)。配置、抽样核心、理论分析、CLI、v3历史/任务隔离、中文Trace及部署静态合同已经接入；旧数据未迁移或删除。

用户已确认：

- 分离星级概率计算器、角色概率计算器与统一概率执行器，每抽由单抽入口组织。
- 本次一起预留四五星名单、通用角色结果及全星级选角流程。
- 不考虑旧接口、旧数据格式和旧历史的兼容；旧历史可删除，不做迁移。
- 设计讨论阶段先更新design，后补清歧义并重写plan；用户分阶段授权任务1～3、4～6、7～9，最后授权完成剩余任务10～12。

此前原plan中的兼容要求已废弃；完整目标已拆为[12项任务](2026-09-17-probability-core-plan.md)。当前12项均已实现，未删除用户历史、任务文件或数据库。

### 本次包含

1. 概率计算与执行职责分离。
2. 可选四五星名单及统一角色身份。
3. 单抽结果、Trace记录和双池状态语义统一。
4. 配置导入、导出、编辑、任务快照、历史复用及赠送复制全链路调整。
5. 理论分析、六星汇总、CLI及网页字段读取同步。
6. 配置、结果、记录格式版本标识及新格式历史库初始化，不迁移旧数据。

### 本次不包含

多轮Trace、明细分批持久化、位置频数图、页面导航重排、四五星角色编辑表格、四五星批量角色分析、新保底规则、性能框架或服务器实测。不新增依赖，不自动提交、合并或在线推送。现有未提交页面文档必须保留。

## 2. 当前结构与目标关系

现有星级概率计算在Rule1中，六星角色份额计算在PoolConfig中，星级抽样在draw_once中，角色抽样在Rule1.pick_six_star中。目标不是重写规则，而是统一抽样并清理角色专用字段。

```text
simulate：组织轮次、主抽、赠送、汇总及可选记录
  └─ draw_once：一次抽取
       ├─ 星级概率计算器 → 星级分布
       ├─ 概率执行器 → 星级
       ├─ 角色概率计算器 → 所选星级内部角色分布
       ├─ 非空名单：概率执行器 → 角色
       └─ 奖励结算、保底标记、状态转换 → 单抽结果
```

概率计算器不使用随机数、不修改状态、不结算奖励、不写存储。概率执行器不知道规则、角色、奖励或保底。单抽入口不写数据库。模拟组织者不再自己实现抽样阈值。

采用两阶段抽样，不在每抽展开全部角色的联合概率；联合概率在说明或分析中为“本抽星级概率 × 星级内部角色概率”。

## 3. 规则接口与星级概率计算

继续使用现有Rule1与规则Protocol，不创建额外计算器类或插件框架。

```python
rule.rarity_probabilities(state: DrawState) -> RarityProbabilities
rule.character_probabilities(rarity: int, state: DrawState) -> dict[str, float]
rule.advance_rarity(state: DrawState, rarity: int) -> DrawState
rule.five_star_pity_active(state: DrawState) -> bool
rule.six_star_hard_pity_active(state: DrawState) -> bool
```

新增显式六星硬保底判断，不能由引擎或理论分析仅凭计数等于79猜测：主池第80抽为True，固定概率赠送池为False。draw_once中的实际触发标记和expected_pool_results中的理论触发期望都必须调用six_star_hard_pity_active；五星触发也统一调用five_star_pity_active。分析中的硬保底贡献是“当前状态概率质量 × 接口返回的触发指示”，不是“本抽恰好出六星”的概率。

DrawState只包含连续未出六星次数与连续未出五星及以上次数；主池累计抽数仍由模拟组织者持有，不混入保底状态。

星级分布使用现有不可变RarityProbabilities表达四、五、六星。有效概率有限、各自在[0,1]、总和为1，允许1e-12浮点误差。不得通过任意截断或重新归一化掩盖非法规则；若理论上应为0的剩余概率因舍入在[-1e-12,0)内，可归0，超出则拒绝。

状态输入必须为有效整数计数，bool不是整数输入；advance_rarity拒绝非法星级、硬保底位不可能的星级结果，不生成越界状态。

动态保底主池的六星未出计数限定0～79；固定概率赠送池没有80抽硬保底，其六星未出计数只要求非负，不能强行继承主池的79上限。五星计数仍遵守该池的五星保底范围，关闭时只能0。这使固定池概率和状态含义一致，不改变默认赠送仅10抽的规则。

移除角色专用随机接口pick_six_star及其Protocol定义，不保留兼容包装。保留 `rule.probability(state: DrawState) -> float` 作为纯六星概率公式入口；rarity_probabilities与六星周期数学分析都复用它，不各自复制66/80边界公式。

删除旧advance(state, is_six_star)接口，但不能把“未出六星”机械替换成advance_rarity(state, 4)或advance_rarity(state, 5)。等待时间改用第8节的六星进度数学递推；有限抽数完整期望继续使用真实4/5/6分支与advance_rarity。所有advance调用都必须按用途分别替换。

## 4. 角色配置与条件概率计算

### 角色身份

角色身份为 `(rarity, name)`。同一星级内名称非空且唯一，不同星级允许同名。暂不引入独立角色ID或角色数据库。

### 配置结构

六星保留已有名单、UP份额、限定标记及UP权重规则：UP必须限定，多UP分配总份额，非UP平分余量。四五星使用最小不可变WeightedCharacter(name, weight)，没有UP、限定或角色级保底概念。

配置新增：

```json
{
  "format_version": 1,
  "four_star_characters": [],
  "five_star_characters": []
}
```

以上为字段片段，完整配置仍包含up_share、five_star、six_star_characters、rewards。format_version必填且为整数1，不接受bool；不支持旧版未带版本的配置。默认配置文件同步更新。

四五星名单读取时可省略，等价于空名单；规范导出总是输出两份数组，不再为旧快照格式省略空数组。显式null、非数组、非法角色对象拒绝。

可用名单项为 `{"name": "四星角色A", "weight": 1}`，weight省略默认1；必须有限且严格为正，不接受bool。各稀有度按名单顺序保留。按最大权重缩放后归一化，避免大有限权重求和溢出。

### 计算接口

```python
config.character_probabilities(rarity: int) -> dict[str, float]
```

- 4、5星：空名单返回空分布；非空按权重归一化。
- 6星：沿用六星UP与非UP算法，六星名单不能为空。
- 其他稀有度：ValueError。
- 返回字典按该稀有度配置名单顺序排列，不能按UP分组排序。
- Rule1同名接口验证state后委托配置，当前角色份额不随状态变化。
- 删除旧six_star_character_probabilities，分析与图表统一调用新接口。

## 5. 通用概率执行器

唯一执行函数放在lottery_simulator/probability.py：

```python
def sample_distribution(
    distribution: Sequence[tuple[T, float]], roll: float,
) -> T:
    ...
```

输入roll是已经生成的一次随机数，不是种子；执行器内部不初始化或推进rng。

校验：非空分布、概率为非bool数值且有限、各自在[0,1]、math.fsum总和与1之差不超过1e-12；roll为非bool数值、有限且在[0,1)。转换溢出或非法类型统一报ValueError。重复选项拒绝；本项目选项只使用稀有度整数或角色名称字符串。

执行：按输入顺序累计，使用严格 `roll < cumulative`；零概率项跳过；合法分布仅因舍入留下尾差时返回最后一个正概率项。不能自动归一化非法分布或回退到零概率项。

## 6. 单抽结果与入口

### 单抽结果

DrawOutcome使用以下字段，不保留six_star_character或is_six_star等可由rarity推导的重复字段：

| 字段 | 含义 |
|---|---|
| rarity | 4、5或6 |
| character_name | 对应星级角色名；无名单时None |
| is_up / is_limited | 当前仅六星可为True，四五星恒False |
| rewards | 本抽全部奖励名称与数量 |
| five_star_pity_triggered | 本抽来源池到达五星保底位 |
| six_star_hard_pity_triggered | 本抽来源池到达六星硬保底位 |

角色身份由rarity与character_name共同表达，无须再保存拼接字符串。

### 单抽返回结构

新增最小不可变DrawResult，将原匿名三元组改为具名结果：

| 字段 | 类型/含义 |
|---|---|
| outcome | DrawOutcome |
| probabilities | RarityProbabilities |
| state_before | 本抽来源池抽前DrawState |
| state_after | 本抽来源池抽后DrawState |

```python
draw_once(rule: LotteryRule, state: DrawState, rng: random.Random) -> DrawResult
```

执行顺序：

1. 计算星级分布，消耗一次roll，按6、5、4顺序执行。
2. 对实际选中星级计算角色条件分布。
3. 有名单则消耗一次角色roll，即使名单仅一人也统一消耗；无名单则不消耗。六星无名单报错。
4. 六星查配置得到UP和限定标记；四五星只填角色名，相关标记False。
5. 按星级结算奖励，在抽前状态判断保底触发，再调用advance_rarity。
6. 返回具名结果，不更新传入的不可变state，不进行存储。

奖励、五星与六星保底、赠送隔离等抽奖规则不变。

## 7. Trace记录与双池状态

Trace仍只支持单轮。本次核心和网页均明确默认关闭Trace；simulate默认collect_records=False，删除原“单轮隐式收集”的行为。关闭时不创建DrawRecord。

新的DrawRecord使用嵌套单抽结果，避免重复保存同一概率或角色字段：

| 字段 | 含义 |
|---|---|
| record_format_version | 整数1 |
| draw_index | 本轮总体实际序号，包含赠送 |
| source | main或bonus |
| source_index | 本轮当前来源中的抽取序号 |
| bonus_event | 赠送事件，主池None |
| main_draws_completed | 本抽结束时累计主抽数，包含假设历史 |
| draw_result | DrawResult，内含来源池抽前后状态、结果及概率 |
| main_state_before | 主池抽前状态 |
| main_state_after | 主池抽后状态 |

主池抽：draw_result.state_before/after分别等于main_state_before/after。赠送抽：draw_result中是赠送池状态，main_state_before等于main_state_after，主池累计数保持不变。

不再保存pity_position、probability、state_after等旧顶层歧义或重复字段。页面需要的“来源池第几次保底抽”从draw_result.state_before连续未出次数加1计算，明确不是累计抽取序号；固定六星概率赠送池不将该值称为六星硬保底位置。

本次不新增trial_index，以免假装已支持多轮；后续多轮Trace独立增加轮次、复合主键、分批存储和分页。

当前记录仍采用原单轮收集方式，不声称解决大规模明细内存问题。仅网页参数校验保持Trace每轮主抽最多10万的限制；CLI和核心本次不新增抽数上限，不能将网页限制写成所有入口的现有行为。Trace的trials必须1则适用于网页、CLI和核心。

### Trace展示映射

JSON和数据库保留上述嵌套结构；网页使用一个纯展示帮助函数把记录展开为中文列，不改写原记录。至少显示以下映射：

| 中文列 | 数据路径 |
|---|---|
| 总体抽取序号 | draw_index |
| 来源 | source，main显示主池、bonus显示赠送 |
| 来源内序号 | source_index |
| 主池累计抽数 | main_draws_completed |
| 星级 | draw_result.outcome.rarity |
| 角色 | draw_result.outcome.character_name |
| 是否UP / 是否限定 | draw_result.outcome.is_up / is_limited |
| 四星 / 五星 / 六星概率 | draw_result.probabilities.four_star / five_star / six_star |
| 来源池抽前未出六星 / 未出五星及以上 | draw_result.state_before的两个计数字段 |
| 来源池抽后未出六星 / 未出五星及以上 | draw_result.state_after的两个计数字段 |
| 主池抽前未出六星 / 未出五星及以上 | main_state_before的两个计数字段 |
| 主池抽后未出六星 / 未出五星及以上 | main_state_after的两个计数字段 |
| 五星保底 / 六星硬保底触发 | draw_result.outcome中的两个触发字段 |
| 赠送事件 | bonus_event |
| 各奖励数量 | draw_result.outcome.rewards按配置顺序展开为“奖励：名称”列 |

默认列序优先来源、序号、星级、角色，概率与状态放后。无角色显示“未配置角色名单”，不能误写为未出六星；没有奖励时不造空奖励列。概率列按百分比格式展示，不将0.008误显示为0.008%。

CLI文字Trace采用同一语义直接读嵌套字段，概率和状态用紧凑文字显示。历史与当前结果复用相同展示映射；下载JSON仍保留原始嵌套格式，不下载页面展开后的表格代替原数据。

本次仅完成新字段展示映射，不夹带多轮分页和筛选功能。

## 8. 配置传递、分析与汇总

### 配置链路

解析、导出、默认配置、网页重建、worker参数、历史快照、复用与for_bonus复制均使用新版本配置。不能丢失四五星名单。

网页暂不增加四五星角色表，名单通过JSON修改；配置摘要显示名单人数和修改方式。恢复默认明确清空名单。保留已修复的动态编辑器稳定输入baseline，不能回写返回值导致第一次编辑失败复发。

### 理论分析

理论分析分为两条有不同状态含义的算法，两条都不使用rng或执行器。

**A. 首次六星等待时间及周期统计：仅追踪六星进度。**

当前Rule1六星概率不依赖五星进度，可按以下数学递推计算主池首次六星分布：

```text
m0 = 初始连续未出六星次数
S0 = 1
第i次抽取（i从1开始）：
  m = m0 + i - 1
  p_i = rule.probability(DrawState(m, 0))
  首次命中概率 f_i = S_(i-1) × p_i
  未命中存活概率 S_i = S_(i-1) × (1 - p_i)
  p_i为1时结束，不创建下一状态
```

这里五星进度0只是调用纯六星公式的有效占位，不代表“每次未出六星都出了五星”或真实五星状态被重置。主池最多计算80-m0项，累计首次命中概率须为1（允许1e-12误差）；用f_i计算均值、方差、分位数与累计曲线。waiting_time_distribution不调用advance或advance_rarity，不虚构4/5星分支。

该一维算法只适用于六星概率与五星状态无关的当前规则，不宣称对未来任意规则通用。固定六星0.8%的赠送池没有80抽必出，不能截到80后归一化冒充完整周期；本次主池周期接口明确只用于动态保底主池，对固定概率池请求完整周期统计报ValueError。赠送有限长度的期望仍由B算法计算，不受此限制。

**B. 有限抽数的星级、六星数量、奖励及保底期望：双保底状态递推。**

保持expected_pool_results已有联合状态递推，以配置的初始DrawState概率质量1开始。每个可达state计算完整星级分布；对概率大于0的4/5/6分支分别调用advance_rarity，按“状态质量 × 分支概率”累计结果与下轮状态质量。不合并4星和5星为一个虚构的未出六星转换。

保底触发期望在分支前分别通过five_star_pity_active与six_star_hard_pity_active累计当前状态质量，模拟标记与理论期望采用相同定义。固定概率赠送池的六星硬保底理论触发为0，不能再根据未出计数判断。

expected_six_stars若保留作为便捷分析入口，则明确委托expected_pool_results的六星数量期望，不保留另一套基于旧advance的有限期望递推；只有初始六星进度的入口将五星初始进度明确设为0，完整运行使用真实配置的初始双保底。expected_simulation_results组合主池与独立赠送池的B算法结果。

六星角色理论数量使用新角色概率接口。当前角色分布静态，角色期望为星级期望乘条件份额；未来动态角色规则不在本次范围，不能把该公式推广为所有规则通用。

### 汇总与展示

星级、奖励、保底汇总保持原口径；六星构成、角色图表和批量角色统计仍仅六星。四五星名字出现在单抽结果和Trace中，非Trace不保存它们的角色数量统计。

_add_outcome只在rarity==6时访问六星角色统计键，避免四五星同名串入。CLI文字Trace及网页直接读取新嵌套字段；JSON导出不生成旧字段别名或fallback。规则曲线读取纯星级概率，无角色抽样。

## 9. 格式版本与历史库

| 版本 | 本次定义 | 含义 |
|---|---|---|
| rule_version | 仍为2.0 | 抽奖规则数学行为，核心组织变化不等于规则变化 |
| 配置format_version | 1 | 本次新规范配置格式 |
| result_format_version | 1 | 新汇总结果及Trace嵌套结构 |
| record_format_version | 1 | 单条新Trace格式 |
| sampling_version | 1 | 两阶段抽样顺序、阈值及随机数推进契约 |
| job_format_version | 1 | 新任务参数、状态及读取契约 |
| 数据库user_version/schema_version | 3 | 新格式历史库契约，不承诺旧快照可读 |

rule_version为规则使用的字符串，本次明确为 `"2.0"`，不是整数版本。配置format_version、result_format_version、record_format_version、sampling_version、job_format_version与数据库user_version/schema_version为表中约定的整数，均拒绝bool。文件中必填版本缺失或类型错误时拒绝，不自动补版本，不回退旧字段。结果包含配置快照、规则版本、结果格式版本和sampling_version；Trace记录附自身版本，不逐条重复运行级sampling_version。

sampling_version是一个固定常量，不建立版本注册或算法管理框架。凡改变星级或角色区间顺序、roll消耗方式、影响选取结果的边界/尾差算法或随机源推进方式，必须增加该版本，即使规则和JSON结构没变。新任务记录启动时的版本，worker校验与自身版本相同再运行，结果写实际执行版本；不接受旧算法版本并悄悄用新算法重跑。

结果运行信息另保存 `rng_algorithm="python.random.Random"` 与实际Python实现和完整版本字符串；这些是复现实验环境信息，不作为算法版本号或依赖锁管理系统。

### 数据库策略

不迁移旧历史。新默认数据库为data/history_v3.sqlite3，保留现有两表组织：simulation_runs保存配置与汇总JSON，draw_records保存新记录JSON。单轮逐抽主键仍为(run_id, draw_index)，无需为概率拆分增加角色表或概率表。

simulation_runs保存schema_version=3；SQLite user_version=3。字段格式变化通过新JSON契约管理，不将每个嵌套字段都拆成SQL列。本次不增加多轮、来源或星级查询索引。

开发默认路径、worker、启动入口、部署接口默认路径及文档须一致指向新库。显式LOTTERY_DB_PATH优先；若指向旧库，拒绝启动并提示版本不兼容，绝不自行清空任意指定路径。

### 任务文件换代与隔离

新任务默认根目录改为 `LOTTERY_DATA_DIR/jobs_v3/`，而不是继续扫描旧jobs目录。数据库和任务根目录必须在app、JobManager、worker、部署接口及文档中成套更新。

parameters.json与state.json均带必需job_format_version及sampling_version。JobManager创建、读取、查找活动任务、启动恢复、worker开始运行都检查版本；缺少或不支持的任务版本不解释为新任务，不尝试按新字段修补。活动任务扫描跳过无效旧格式并记录提示，不能阻止新任务启动。

get_result检查任务版本、完成状态以及结果result_format_version/sampling_version，匹配后才返回；不能仅凭status=completed和文件名就加载旧结果。浏览器session中的current_job_id若在新任务根下不存在或版本无效，则清除引用并提示结果已失效；历史复用/选择的缓存引用若新库找不到也清除，不因读取失败崩溃。

旧任务恢复与旧worker停止分开处理：上线切换前先按PID及worker命令行确认归属并停止旧任务，不能只换目录留下旧worker继续写旧库；新启动恢复只处理新根目录中的有效新任务。无效版本文件不能作为杀进程依据。

即使用户不立即删除旧文件，以上路径与版本校验也必须保证旧jobs/state/result不会进入新代码展示或恢复流程。不读旧结果与物理删除旧文件是两件事，正确性不能依赖用户恰好清理干净。

### 旧历史清理

用户允许删除旧历史，不做兼容或迁移。但本设计更新不执行删除。实施时先停网页与worker，用只读检查定位实际旧数据库及关联任务目录，明确目标后再执行用户授权的清理。

清理仅针对确认属于本项目旧格式的历史数据库及其确实存在的SQLite伴随文件，以及确定旧任务的parameters.json、state.json、result.json和cancel.request；同时清除网页当前任务ID和历史选择/复用引用。不能只删result而让旧state继续被恢复。保留任务日志；不递归清空整个data或jobs目录，不删除backups、奖池配置、日志、源码或无关文件，不使用未解析的环境变量或宽泛通配符做删除目标。自定义外部库或归属不明路径先请求确认。

无需为旧库实现读取/迁移代码，也不强制建立新备份机制；已有备份可保留。完成删除时报告具体移除内容及是否可从已有备份恢复。

## 10. 随机性、输入验证与性能边界

- 整次实验初始化一次rng；各轮与每抽沿用现有rng推进方式，不每抽或每轮重设相同种子。
- 可复现前提为同rule_version、sampling_version、完整配置快照、初始状态、参数、种子以及相同Python实现和版本。格式版本只说明数据结构，不代替抽样版本；不承诺跨任意Python环境或重构前后逐抽相同，不建立旧结果golden兼容契约。
- 明确顺序6、5、4和配置角色顺序，用受控roll测试阈值，保证新实现确定性。
- 名单改变会改变角色roll消耗及后续随机序列，不承诺配置增减名单后星级序列不变；星级概率公式不因名单改变。
- 同配置开启/关闭Trace不得改变rng调用数量或抽奖结果，保存不能消费随机数。
- 无效配置、概率、状态、星级明确失败；不静默裁剪、默认角色或掩盖错误。
- 不新增角色/奖励通用框架，不增加依赖；只新增必要执行函数和具名单抽结果。
- 不承诺此次拆分加速。可复用静态角色分布，但只能绑定不可变配置；动态星级概率按当前状态计算，不缓存为常数。

## 11. 验证标准

执行阶段逐项使用RED、最小修改、GREEN、定向变异/撤销后失败重现、恢复通过的因果验证。保留用户无关改动，只做功能验证，不做SHA或性能框架验证。

必验：

1. 普通、软保底、五星硬保底、六星硬保底概率；第65/66/79/80抽边界。
2. 执行器阈值、零概率、合法尾差、非法值及重复选项。
3. 四五星空名单只输出星级，有名单按权重选角；六星UP权重和非UP份额正确。
4. 跨稀有度同名允许、同稀有度重复拒绝；不会污染六星汇总。
5. 单抽具名字段、保底触发标记、状态转换无歧义；不可能硬保底结果拒绝。
6. 初始主抽29再主抽1触发送10抽，赠送继承名单且不改变主池状态。
7. 导入、网页编辑、导出、任务快照、复用、赠送复制不丢名单。
8. Trace开关抽奖结果一致，关闭时不创建记录，单轮限制继续有效。
9. 新格式历史保存/读取/删除及事务失败回滚；旧库拒绝、新库初始化，不做迁移。
10. CLI text/JSON、新字段图表与网页展示、理论期望同一口径；全套现有适用测试加新增测试通过。
11. 等待时间一维递推与独立直接乘积参考相符，第80抽累计为1；将旧advance设为抛错后分析仍可运行。对短长度和多初始状态，双保底六星期望与独立六星进度参考递推一致；五星结果与保底触发由真实分支验证。
12. 模拟和理论均通过显式硬保底接口：用一个接口返回False但计数位于max_pity-1的最小测试规则证明不会被计数误判；另验证默认独立赠送池六星硬保底触发为0。
13. Trace映射中文列直接可见星级、角色、概率、来源、双池抽前后状态及奖励；展示不修改原JSON，四五星有名单时角色正确可见。
14. sampling_version在CLI、网页结果、任务状态和历史快照中一致；不支持的任务抽样版本拒绝运行，同版本同环境重跑一致，Trace开关结果不变。
15. 放置旧jobs文件及旧session任务ID，换新库/新任务根后不会展示、恢复或导入旧结果；在新根放版本缺失/错误记录同样拒绝，不阻塞合法任务。

浏览器验收和自动化检查分别记录；未进行的服务器实测不能标为通过。

## 12. 设计自审与后续

✅ 设计审计项均已补齐并同步plan。任务1～12已实现和审查；配置编辑、CLI、新结果、v3仓库/任务文件、中文Trace、默认路径与部署静态合同均已验证。

✅ 全仓自动化、CLI、临时v3集成及Streamlit启动健康检查已完成。⚠️ 交互浏览器点击和真实服务器部署仍未验；v3仅在临时目录验证，用户实际历史未变。

多轮Trace仍独立实施，不夹带轮次字段及分批存储。本次不自动提交、合并、推送或在未合并状态下清理用户旧数据。
