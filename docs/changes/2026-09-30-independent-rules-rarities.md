# 独立规则、通用稀有度与网页说明实施记录

- 实际开始：2026-10-01。
- 当前状态：已验证、未合并；任务1—16已完成，集中验收通过；任务17未执行。
- 设计：[设计契约](2026-09-30-independent-rules-rarities-design.md)。计划：[逐任务计划](2026-09-30-independent-rules-rarities-plan.md)。
- 工作树：`D:\Web_project\lottery_simulator\.worktrees\independent-rules-v6`；WSL路径见[Windows临时说明](../windows-wsl-temporary.md)。
- Git：基于`a0b575f`的detached HEAD，修改未提交、未合并、未推送。主项目产品代码未改变，真实v5数据及既有服务保持现状。

## 任务1：纯配置契约、版本和默认文件

### 已实现

- 新增`lottery_simulator/rules/definitions.py`：计划约定的规则、稀有度、大小保底、两类赠送、池、角色、奖励、实验参数及初始上下文类型。使用冻结dataclass、tuple及标准库只读映射，输入复制，`to_dict()`返回独立的JSON对象/数组。
- 构造和文件加载均校验类型；拒绝未知/缺失字段、重复ID/rank/同作用域名称、bool整数、非法枚举、非有限或负概率/权重/奖励。概率尾差容忍为`1e-12`，不自动归一化。角色权重为正，UP必须限定，启用分组不能给空组正概率。
- 复用现有JSON字节解析器的大小限制、重复键检查及非有限数值拒绝；新版`load_rule_document`、`load_pool_document`、`load_experiment_document`不调用旧Rule1或Django。
- 纯配置规则算法标识固定为`dynamic_probability`；规则名称可以变化，算法版本`RULE_VERSION`为字符串`3.0`。三种文件顶层带严格整数format_version，嵌套配置不重复该元数据。
- 版本采用计划值：规则1、池3、实验2、结果4、事件3、抽样2、任务4、库6、临时Trace2、导出2。旧CONFIG/RECORD常量及旧稀有度显示辅助函数仅暂留给尚未迁移的调用方，新契约不使用它们；没有旧文件兼容加载器。
- 新增`configs/rules/zmd.json`，更新池/实验默认文件。UUID只在本次生成并固定保存；保持默认名单、权重、奖励和机制参数。`configs/rule1_default.json`仍保留原文，后续调用方全部迁移后再删除。
- 新增`tests/fixtures_rules.py`；默认规则、池、参数均从唯一默认文件读取。任务1阶段compile_pool夹具延迟导入任务2模块；任务2实现后改为直接导入。
- 新增`test_rule_definitions.py`，迁移`test_config_documents.py`及`test_formats.py`到新契约；涵盖文件/类型往返、冻结及输入副本、重复键/ID/排序/名称、整数/版本、非法概率/权重、UP分组边界、默认引用和任意精度seed等用例。

### 实际检查

- WSL Python以`-B -c`进行7个新增/修改Python文件的内存compile语法检查：通过，没有生成数据库。
- 加载三份默认文件，核对规则→池→实验ID引用；使用默认夹具、dataclasses.replace、初始上下文及全部配置类型的严格JSON往返：通过。
- `json.dumps(..., allow_nan=False)`输出合法；`2**200+1`种子保持精度；尝试写入只读配置映射得到TypeError。
- `git -c core.autocrlf=input diff --check`：通过。旧默认文件、README及本地使用手册无修改；隔离工作树没有data目录。

以上是小范围语法/接口检查，不是集中功能验收。按计划尚未运行以下unittest组，留到任务16：

```bash
"$LOTTERY_PYTHON" -m unittest tests.test_rule_definitions tests.test_config_documents tests.test_formats
```

### 未验范围与后续交接

- 任务1结束时尚未实现抽样、概率推进、理论分析、CLI适配、ORM/API、前端或v6迁移；概率推进已由下方任务2补齐。隔离工作树的旧CLI/网页/模拟不能作为新版入口使用；主项目原v5服务继续使用原代码。
- 任务2实现compile_pool、目标解析、初始条件的模式/保底历史语义校验及动态显示名最终校验；本任务只完成文件结构、类型和数值边界。关闭机制的合法草稿保留，启用后的目标有效性由任务2核对。
- `RuleDefinition/PoolDefinition/ExperimentDocument.to_dict()`包含文件版本，嵌套策略及参数to_dict不含文件版本。只读映射由to_dict转换为普通dict；后续快照使用该接口，不用dataclasses.asdict深复制只读映射。
- 任务5、6、8等按原责任图迁移旧调用方；任务16集中执行已写用例和完整流程，不能把当前小范围检查记为整体已验证。


## 任务2：通用概率计算、目标解析和状态推进

### 已实现

- 新增`lottery_simulator/rules/runtime.py`，提供计划约定的CompiledPool、DrawState及全部runtime函数；纯标准库，不消费随机数、不访问Django或数据库。
- compile_pool复用任务1构造校验，核对规则ID、完整稀有度映射及继承/覆盖后的最终显示名；启用机制按从高到低、名单顺序解析first_up，指定赠送绑定按角色ID查找，大保底目标必须属于最高档。关闭机制的目标草稿不参与运行。targets固定两个键，保存只读目标ID映射。
- normalize_parameters补齐缺省零值，拒绝未知档及关闭机制的非零状态；分别处理首次模式的历史推导与循环模式的显式计数，校验历史累计、各档真实计数关系、硬保底阈值、目标已获标记。最低档不能伪造未满足进度，未跟踪档不参与真实历史关系比较。initial_context记录按rank排序的稀有度及当前大目标/模式。
- DrawState复制并规范化ID计数为排序tuple，可哈希、冻结，支持严格JSON对象往返。状态推进返回新对象，保留被跟踪档的真实未满足数，不加入理论缓存或截断Trace进度。
- 稀有度概率按高档优先软增、最低档先扣、最强硬保底下限及大保底强制目标执行；最终检查有限、非负且合计1。向量输出顺序从高到低。最高档硬保底与大保底明确为概率1，其他硬保底保留高档概率。
- 角色条件概率支持每档UP分组及开关，组内先除最大权重再求和，避免巨大权重求和溢出；输出保持名单顺序，空名单返回空分布。advance_state拒绝零概率、未知档或错误角色，按档位重置/递增小保底，并按目标获得模式关闭/重置大保底。
- transition_branches返回正联合概率及新状态，无名单产生None角色分支；复用两类概率及推进函数，不复制执行语义，不消费RNG。直接赠送不调用状态推进。
- rules包导出新版内核，默认测试夹具直接使用compile_pool。base.py标明旧Rule1接口的过渡用途；旧引擎、分析和CLI仍需旧双计数类型，因此未提前替换其DrawState，任务3/4/5迁移调用方后再移除。新代码统一从runtime导入通用DrawState，不以旧类型替代通用状态。
- 新增`tests/test_dynamic_rules.py`的9组用例：默认65/66/79/80边界，同时保底、四档及软增优先级、最低档无改善、各档UP及超大权重、同名角色、目标解析及重排、首次/循环模式、初始不可能历史、冻结/哈希/序列化、真实状态与等价概率、联合分支及零概率结果拒绝。

### 实际检查

- WSL隔离工作树Python对runtime.py、base.py、rules/__init__.py、测试夹具和新增测试文件进行5个源文件内存compile：通过。
- 默认compile_pool加载、initial_state/initial_context接口及DrawState严格JSON往返：通过；这是默认接口小范围检查，没有执行概率边界用例或unittest套件。
- `git -c core.autocrlf=input diff --check`检查及README/原本地使用手册保护核对见本次交付；不初始化数据库，不提交、合并或推送。

集中功能验收仍在任务16，尚未执行：

```bash
"$LOTTERY_PYTHON" -m unittest tests.test_dynamic_rules
```

### 后续交接

- 任务2交付时的下一步为任务3抽样、事件计数、赠送执行及通用模拟结果；该项已在下方完成，当前下一步任务4接入理论分析。当前新版内核交付不代表旧CLI/网页已可使用新格式。
- 参数规范化保留首次模式输入misses=0，真实历史推导仅进入DrawState，不能把派生值回填为首次模式的用户输入。CompiledPool.targets保存目标ID，展示/事件从冻结池按ID取名称与档位。
- 理论等价状态压缩留任务4；其缓存键与真实输入/Trace状态分开，不能把内部压缩计数送回历史语义校验。


## 任务3：模拟、过程事件与统计计数

### 已实现

- 用户授权本任务及后续任务可拆分使用子代理，优先GPT-6-luna。本任务由主代理实现模拟循环，两个GPT-6-luna子代理分别负责事件/结果与测试，另一个进行只读审查；各自文件范围分开，主代理核对接口和整合结果。该授权不改变逐任务推进或任务16集中验收安排。
- 新增events.py：EventCounts按全实验计算主抽、赠送抽、真实总抽、周期触发次数、直接赠送角色数及Trace事件数。首次赠送使用H<T≤H+D，周期使用整除差；所有结果、实际处理事件总量和抽取加直接赠送的获得数量上限均核对int64上限。Trace关闭的保存事件数为0。
- engine.py替换固定Rule1模拟器，draw_once复用任务2概率及状态函数，稀有度按从高到低消费一次随机数，有名单再按冻结顺序消费一次角色随机数，必出结果也消费对应随机数。无名单返回None角色及None条件概率。
- simulate_draws只执行模拟，各轮从同一初始状态开始，全实验只有一个Random实例。None seed生成实际整数并回填参数；历史初始部分不计入本次统计。取消使用既有control.py，无新控制框架。
- 主抽后按首次赠送池、周期直接赠送顺序执行。bonus_pool从冻结主池复制角色/UP/奖励及显示名，使用赠送配置概率和独立零保底，关闭大保底和所有递归赠送；赠送池不回写主池状态。直接赠送按配置quantity累计，一次触发仅一条事件，不抽样、不发奖励、不推进主池保底。
- 汇总统一为draws（main/bonus/total）、grants、acquisitions，稳定稀有度/角色/奖励ID作为键，分类使用up/other_limited/standard/unnamed。数值为每轮均值，同时保留每轮计数/奖励/分类/保底触发分布和至少一次发生率。稀有度至少一次指标查询该档或更高；角色指标按具体ID。grants/acquisitions没有抽取奖励或保底字段，character_count只计有名单角色；unnamed结果仍保留稀有度和分类计数。奖励逐次及跨轮累计检查有限性，溢出立即报错。
- 进度分母为全实验真实抽取数加周期触发次数，Trace关闭也相同；每个事件处理后反馈，最后一份赠送执行完成才到该阶段100%。回调按约1000次节流，逐事件保留取消检查；模拟阶段结束不代表完整任务成功。
- 新增results.py的DrawOutcome、DrawResult、ProcessEvent和SimulationResult；只Trace时构造ProcessEvent，sink存在即流式输出，records不重复保留。每轮event_index、draw_index、source_index分别计事件、真实抽取和来源抽取，从1开始；赠送池事件main_state_before/after相同，grant序列化不含draw_result或虚构保底状态，source及抽取序号为null。
- simulation_payload包含版本、抽样环境、真实参数、全实验counts、规则/池/目标/初始上下文快照、模拟和理论；明确拒绝theoretical=None及非有限JSON。include_events仅用于开启Trace且内存事件齐全的结果；网页默认不嵌入事件。模拟内部结果保持theoretical=None，任务4才提供完整simulate。
- 包顶层导出通用模拟/事件接口，移除旧固定结果导出；旧CLI、worker、Trace存储等调用方继续按任务4/5/9/10迁移，不增加旧格式兼容层。control.py已有回调和取消类型足够，本任务没有修改。
- 新增deterministic_target_compiled两档夹具和test_dynamic_engine；test_engine/test_bonus_rule迁移到新接口，保留取消与赠送隔离检查。明确写入480主抽＋10赠送抽＋2次quantity=2赠送＝4角色、492条Trace事件，以及Trace/RNG/流式/模式/序号/历史边界/溢出/序列化等用例。

### 检查与未验范围

- 已进行源码和接口静态核对，检查计数口径、顺序、状态隔离、Trace关闭分支及旧调用迁移边界。子代理的语法/空白检查不代替功能验收。
- 按用户安排，不在本任务运行unittest或完整模拟验收；WSL以-B执行8个源文件内存compile、3个测试模块导入、默认池/计数接口及确定性夹具加载：通过；静态统计15个测试方法，未执行这些方法或模拟循环。工作树与主目录的git diff --check通过，README/原本地使用手册无差异，隔离工作树没有data目录。没有访问真实数据库或启动新版Web/worker。
- 尚未计算理论或等待分布，不能把simulate_draws内部结果输出成已完成运行。下一步任务4接入理论并提供完整simulate，任务16集中验证测试和整条流程。
- 主项目只同步进度文档，原README/本地使用手册和产品代码未变；工作树修改未提交、合并或推送。

待任务16集中执行：

```bash
"$LOTTERY_PYTHON" -m unittest tests.test_dynamic_engine tests.test_engine tests.test_bonus_rule
```

主审处理只读复核意见：运行前核对抽取数＋赠送角色数的上界，保护全部获得统计；分布汇总递归覆盖分类与保底触发。修正测试中的单轮参数、quantity断言及确定性赠送目标，不靠默认1000轮或偶然抽中满足断言。上述是源码核对和修正记录，功能用例仍留任务16执行。


## 任务4：有限理论期望与主抽等待分析

### 已实现

- analysis.py改为通用有限状态质量递推，消费runtime.transition_branches，按真实稀有度/角色联合概率累加抽取、分类、奖励和抽前保底触发期望，不用稀有度次数乘固定UP占比。每个状态附各指标的未命中质量，独立跟踪各档或更高、具体角色及按档类别至少一次概率，不使用全部指标的联合命中掩码。
- 理论输出使用与模拟相同的draws（main/bonus/total）、grants、acquisitions口径，数值为单轮期望。trials不会再次缩小主抽或赠送期望；直接赠送从全实验计数用整数整除恢复单轮次数/数量。赠送池独立零状态递推，至少一次概率按独立事件的未命中乘积合并；直接赠送只并入获得指标，无抽取奖励/保底，不生成伪造的模拟频率分布。
- 理论键仅压缩已证明候选概率饱和的soft-only计数，保留软保底生效标记；hard-enabled计数不压缩，避免丢失硬保底触发统计。先完成真实初始历史校验再建立内部等价键，不修改参数或Trace真实状态。转换缓存复用统一内核；每层及缓存最多200,000状态、累计最多2,000,000分支，超限明确ValueError，不输出部分期望或近似结果。每256状态及64分支检查取消，校验状态质量守恒、有限数和概率尾差。
- engine.simulate提供完整入口：先simulate_draws，明确进入theory阶段，再以实际种子/规范化参数计算期望，最后replace填充theoretical；阶段切换前后均可取消。原内部模拟结果仍不能冒充完整结果，包顶层导出完整simulate及两类理论函数。
- 新增waiting_analysis.py：等待目标为未来主抽首次获得查询档或更高，输出真实initial_state、source=main、unit=additional_main_draws。投影仅将低档计数置零，未命中时查询档及更高计数加1，活跃大保底加1；不调用假设抽到最低档的advance_state。
- 投影依据：概率按高到低处理，低档软保底只移动低档质量，低档硬保底也不改变查询档及以上总概率；大目标属于最高档，低档结果不能满足它。因此所有未命中分支具有同一后续命中概率序列。相关硬/软保底及活跃大保底证明有限必达边界；软饱和步数核对实际浮点候选，不能让无法计算的soft边界覆盖其他有效hard/big边界。
- 无相关有效保底时使用几何闭式：q=0不可达且mean=infinite/null，q=1等待1，其余均值1/q与分位数。显示窗口100步，完整有限递推上限100,000步；窗口残余、尾部下溢或资源/数值未完成均明确报告。几何尾部下溢使用null及log_value，不假装为零；有限递推下溢返回incomplete。long_run_rate保持not_applicable/null，未证明更新过程不计算1/mean。
- 新增test_dynamic_analysis、test_waiting_analysis，迁移test_analysis并补完整simulate阶段交接测试；包括两种大保底六抽、三档两抽路径枚举、单轮期望不随trials变、独立赠送与递归分类概率、获得合计、q=.25均值4、H=2只需1主抽、已获目标后不可达、软饱和首必达位置、尾部/资源/取消及JSON有限性。

### 边界

- 数值和资源保护属于明确失败边界，不承诺任意稀有度/阈值配置均可快速完成。等待未完成不会将已算出的有限实验期望改成0或伪无穷。
- 旧test_pool_config/test_rule_1等固定接口及尚未迁移的网页调用仍留任务16统一迁移/清理；没有为旧expected_pool_results或旧Rule1输出增加兼容层。这是分阶段替换中的已知交接项，当前不能对整个旧测试发现集或网页宣称可运行。

## 任务5：新版中文CLI与文件引用

### 已实现

- CLI不再调用Rule1、固定稀有度结果或旧DistributionStats。analyze计算有限期望和主抽等待；simulate只调用任务4完整simulate并使用统一simulation_payload。main(argv=None, stdout=None)保持StringIO注入契约，不依赖Django、不写网页历史。
- 新增resolve_rule_reference(ref,directory,confirm)，规范化UUID并按ID优先；已有ID对应坏格式/同ID多个文件时拒绝。只有ID不存在才按唯一名称候选且显式确认；非交互不等待或猜测。池引用解析同步保护坏格式同ID，保持无关坏文件不挡住有效ID匹配。ID不拼接路径。
- --rule-directory及--rule-config解决池绑定引用，显式其他ID先核对原绑定ID存在性，不能绕过已有ID。实验显式池文件也核对原引用，不静默换池。名称确认后的引用只在内存规范化，不写回原文件；非零初始历史要求保存上下文存在且与当前解释一致，全零可派生。
- 新参数包括历史累计主抽、严格JSON稀有度ID计数、目标已获标记（裸flag或true/false）、循环大保底计数；复用类型及历史语义校验。旧initial-pity/five-star-pity参数和旧文件拒绝。显式运行参数覆盖文件；analyze默认100主抽只适用于无实验文件，simulate无实验必须提供--draws，默认单轮。任意精度seed保持Python整数。
- 中文文本按动态档名/角色所属档显示目标、来源、每轮模拟均值与理论期望、奖励、直接赠送与获得合计，解释赠送不计抽数/抽取奖励；展示下一周期累计主抽位置。等待状态译为中文，未完成说明保留。JSON包含当前版本、快照、参数、计数与上下文，不输出旧mean_six_stars或Infinity/NaN。
- export-trace仅准备新版事件类型、来源、稀有度/角色ID、轮次/来源内位置及主抽触发区间参数；明确任务9接口尚未实现，不调用旧导出、不读数据库、不创建文件。任务9完成后才接入流式导出。
- test_cli及test_config_documents补默认zmd、30×2/Trace=80、H=250已获目标下一赠送480、旧参数/文件拒绝、ID优先/同ID坏格式/名称确认、任意大种子、实验默认覆盖及上下文保护、中文黄金片段与未实现导出说明。

### 本次实际检查（任务4、5合并交付）

- WSL以-B执行13个新增/修改Python文件内存compile：通过；6个相关测试模块导入、默认规则引用解析和CLI参数/help接口检查：通过。大整数seed和裸目标已获flag经参数解析保留；analyze parser没有假显式draws默认值。
- 静态读取相关6个测试模块共42个test方法，未执行方法。各子代理只做源码/语法检查和只读复核；主代理处理了单轮期望缩放、类别递归、真实状态/尾部表示、ID优先及单轮/首次命中测试断言等问题。
- 未执行理论、等待或模拟计算，没有运行CLI analyze/simulate命令或unittest套件。源码/导入通过不等于业务功能已验证；集中验收继续在任务16。
- 工作树及主目录git diff --check均通过；原README/本地使用手册无差异，隔离工作树没有data目录。主目录只同步进度文档，产品代码与真实v5数据不变；修改未提交、合并或推送。

待任务16集中执行：

```bash
"$LOTTERY_PYTHON" -m unittest tests.test_dynamic_analysis tests.test_waiting_analysis tests.test_analysis tests.test_engine tests.test_cli tests.test_config_documents
```

任务4/5交付时的下一步为任务6；真实v5数据切换仍是另行授权的任务17。


## 任务6：v6模型、迁移与默认业务初始化

- 新增Rule，池以PROTECT外键绑定规则，实验配置保存initial_context_json；历史保存规则和池两类ID/修订/作者/配置快照、参数、上下文及event_count。计数和事件序号使用非负int64字段，seed保持十进制文本。
- SimulationEvent替换旧DrawRecord；draw和character_grant共用轮次/事件序号唯一性及JSON一致性约束，赠送索引保存真实稀有度/角色ID，抽取序号和source为空，不伪造draw_result。数量、布尔/整数类型及索引列一致性由数据库约束保护。
- 保留0001原稿，0002在任何DDL前拒绝非空账号、业务、登录防护、初始化/删除标记、会话和权限关联表。先移除旧draw_records及池删除触发器，再改表，恢复池SET_NULL和新事件级联SQL触发器，最终设置user_version=6。此不兼容迁移不可反向执行；回滚使用旧版本及原v5备份流程，不通过降级迁移清除v6数据。
- settings默认使用history_v6.sqlite3、jobs_v6、exports_v6。init_business_defaults要求可用管理员及完整v6迁移；固定默认ID幂等，不覆盖用户修改，同名不同ID冲突停止。init_admin在同一事务创建管理员和默认业务，已有账号拒绝重新初始化，失败回滚。
- 移除dashboard包入口对尚未迁移的旧job_models的提前导入；当前没有依赖这些包级导出的调用方，Django模型可独立加载。旧任务模块/worker仍在任务10改造。
- schema/bootstrap测试保留资源所有权/唯一名、配置SET_NULL、Session及seed语义，增加空目标完整链、非空v5拒绝及源状态不变、两类事件/raw SQL级联、坏JSON/数量及初始化原子性。均未执行。

## 任务7：规则服务、权限与账号引用保护

- 新增rules服务：规则列表范围、编辑/复制/删除、授权导出、ID优先解析及统一规则池关系校验。复制生成新规则UUID并保留稀有度ID/最初作者；公开资源不因署名账号停用而隐藏。
- 保存事务重读actor/auth_version，核对revision，引用存在时禁止稀有度集合/rank变化；参数及可见性更新逐一校验全部消费池并compile，任何失败整笔回滚。错误不返回其他用户隐藏池名称或配置。
- 关系权限按池所有者校验，管理员代管不转授自己的隐藏规则权限；私有规则所有者deleting时拒绝新引用/复制。已有不可访问ID不按名称回退，缺失ID只给有权名称候选并要求确认。
- 删除账号预览增加规则数及外部池引用数；删除事务在设置deleting之前检查外部引用。使用Pool查询检查同一规则同时有自有/外部池的情况，不能用多值关系exclude遗漏外部引用。无外部引用时先清自有池、保留其他配置池名提示，再删自有规则，保留原停止任务/文件清理/撤销会话协议。
- 补规则权限、修订竞争、结构锁、共享参数回滚/不泄漏、授权导出、停用/删除状态及账号删除阻塞用例，未执行。

## 任务8：池、实验及初始条件服务

- 池保存绑定当前规则并compile，核对expected_rule_revision；池类型和作者不可原地转换。复制核对源池、源规则、目标规则修订；复制公共池要求明确选择公共规则。
- 切换规则按稳定ID映射角色名单/UP设置、显示名、奖励；不同ID必须显式映射或确认清空，拒绝自动合并冲突及失效机制目标。文件导入严格拒绝旧版本、重复键、未知字段和权限意图。
- 池/实验导入分预览和确认，确认在IMMEDIATE事务内重新按ID优先解析权限及候选并核对最新修订；已有ID不可访问时不允许任意选另一资源绕过。文件原始字节保持严格类型，只有API预览往返对象显式还原十进制文本，大seed和嵌套计数保持精度。
- 实验只保存池引用、规范化参数及服务端当前上下文。全零条件可派生；非零历史或已获标记要求rule_id、稀有度顺序、big_mode、big_target_id匹配，确认后仍校验数学合法性，不清零或截断。新增experiment_validation提供原参数与当前上下文不兼容诊断。
- 任务10必须将experiment_validation接入实验API列表/详情，并连通新版两阶段导入与修订字段；严格文件导出不混入诊断。当前交付是模型和服务，旧API、worker与前端还未完整升级。
- 池/实验服务用例迁移并补权限、修订、作者、配置引用、结构映射、大整数、上下文/目标重排、模式互换和阈值下降；原API安全场景保留为新版契约用例，等待任务10连通后在任务16执行。

### 任务6—8实际检查与边界

- 已做源码及调用路径复核，处理模型与迁移约束漂移、旧包入口导入阻塞、赠送索引遗漏、共享可见性、外部引用查询及导入确认事务等问题。
- WSL以-B进行21个相关Python文件内存compile及14个模型/服务/测试模块导入：通过。MigrationLoader(None)和MigrationAutodetector在内存核对最终dashboard迁移状态与当前模型：无差异；此检查不打开数据库，不运行DDL。
- 未执行migrate、初始化命令、服务CRUD、模拟或unittest；新测试的功能验证仍集中在任务16。旧job_models/API序列化/历史仓库调用按任务9/10替换，旧任务测试夹具和前端衔接仍待后续，不能宣称网页后端整体已可运行。
- 原README、docs/local-usage.md及0001迁移无差异；隔离工作树无data目录。真实v5账号库、旧服务、服务器保持原状，未提交、合并或推送。

待任务16集中执行：

```bash
"$LOTTERY_PYTHON" manage.py test tests.web.test_schema tests.web.test_bootstrap tests.web.test_sessions tests.web.test_rules tests.web.test_pools tests.web.test_experiments tests.web.test_initial_context tests.web.test_account_deletion tests.web.test_management
```

任务6—8交付时的下一步为任务9/10；真实账号切换仍由任务17另行授权。


## 任务9：过程事件Trace、历史仓库与流式导出

- 临时Trace库格式2存储draw和character_grant，批量写入，赠送数量2仍一条事件。新增validate_event/validate_event_row，严格检查版本、字段、UUID、整数范围、有限概率/奖励、角色和状态结构及索引列与JSON一致性；拒绝旧记录和损坏数据。写入路径独占创建，不覆盖已有文件。
- iter_validated_events复用纯runtime和冻结CompiledPool，按每轮真实主抽顺序校验主池/赠送池状态、概率、角色条件概率、奖励、保底与状态推进；核对首次赠送位置、同位置顺序、周期目标及每次数量。TraceWriter.finish先重算event_counts，逐条通过后才发布complete；取消及回调失败不发布完整标记。
- TraceReader只读打开；query_events返回当前页list、count_events单独计数，iter_events在只读事务中分批流式读取并关闭连接。筛选使用事件类型、来源、稀有度/角色UUID、本次来源内位置和累计主抽位置；grant拒绝来源/来源位置/未命名筛选。position_counts只聚合draw，以稀有度ID动态计数，窗口最多1000位置。
- HistoryRepository只核v6 schema，不补建表；严格核对结果版本、两类快照、来源修订/作者、参数、目标、上下文、seed、计数、接受时间和限额。批量导入SimulationEvent与汇总同事务，重用相同流校验器，取消/授权失败回滚；历史删除级联事件，非Trace事件数0且不写明细。
- JSONL首行type=metadata、export_format_version=2、matched_event_count，后续type=event/event逐条输出。CLI export-trace已接通此格式，SQLite URI mode=ro访问显式历史库，不启动Django、不覆盖数据库/伴随文件或已有输出；临时文件原子发布。
- 网页下载复用同一JSONL迭代器，保持SessionGate、每批撤权、限额变化、原生下载、私有文件权限、流关闭/失败清理与下载槽释放。限额配置名称保留现有环境变量，数量含义改为事件，管理员仍不能绕过类型及int64边界。
- 用例迁移并补写两类事件、同总量但赠送数量1/3、错误目标/位置、磁盘损坏、批次回滚、完成/关闭生命周期、取消/回调失败、只读筛选、位置分母及store/history两类Reader的两次赠送。下载加入10000/10001事件边界；均未执行。

## 任务10：任务快照、worker与完整后端API契约

- RunParameters保存任务格式4/抽样2、冻结纯类型参数、规则/池、解析目标和初始上下文；to_dict显式序列化，不用asdict处理只读映射。JobState新增rule_source(id/revision/name/author)，核对来源与快照及total_units；实际工作量为总真实抽取＋赠送触发，与Trace开关无关。
- submit_job在既有全局接受锁及IMMEDIATE数据库事务中重新鉴权，核对池/规则两类revision、所有者关联权限、deleting、规范化初始历史、确认上下文和计数限额；接受时固定实际seed及完整快照。API嵌套初始计数和seed显式转换十进制文本，拒绝未知字段、bool修订和不规范数值。
- worker仅从接受时快照compile，调用完整simulate；Trace开启才创建writer，并把同一compiled、实际参数和counts交给finish，再原子保存历史。保留simulating/theory/validating/saving/committing、取消点、单任务锁、账号删除/提交屏障、残次清理、重存和重启调和，拒绝旧任务格式。
- 结果读取核对任务文件与接受快照，历史摘要核对模型列与JSON；重存仍在全局锁及数据库授权边界内执行。公开资源后续变化不修改已接受算法或旧历史。
- 新增规则collection/resource/copy/import-preview/import-confirm/export。导入只能创建当前用户隐藏私有规则；编辑/删除核revision，有引用时结构锁定，响应不泄露他人隐藏引用。结构锁状态与有权引用计数分开。
- 池API使用纯动态document和rule_ref；保存核当前规则revision，复制核源池/源规则/目标规则及明确映射。池导入预览接受严格原文件或document包装，确认核候选与revision，不自动提交。实验API接入初始上下文与两类revision，返回原参数及validation_errors/current_context/needs_confirmation；不可访问池使用原提示和固定不可用诊断，不泄露其新名称/目标。
- run/job结果、Trace、图表及管理列表统一经服务授权；序号/计数/seed使用十进制文本，版本及修订仍严格整数。分类图表最小改为冻结动态稀有度/角色/奖励/保底口径，支持抽取、赠送与获得来源；位置图只计本次source_index，保留有效轮数、最近位置提示和最多1000窗口。完整结果页面与大整数图形展示继续在任务14。
- 保留并迁移原会话撤权、丢响应通过jobs/mine找回、双用户隔离、并发单任务、管理员维护、删除账号提交屏障、取消无半条历史及下载清理场景。新增物理临时库30×2→80条历史事件、接受后共享规则修改仍用旧快照、下一任务使用新revision、旧revision409等用例，留任务16执行。

### 任务9、10实际检查与未验边界

- 主代理和子代理完成源码/调用路径复核，处理了赠送索引及目标键、重复序号公式、状态/概率流校验、导入事务、嵌套初始计数转换、旧字段筛选/重存、不可访问池上下文泄漏及测试夹具问题。独立只读复核未发现新的重要问题；不是运行验收。
- WSL Python -B：61个Python文件内存compile、19段嵌入验收脚本compile、16个相关测试模块导入通过；4个新增/修改路由解析、冻结参数往返与API大整数/未知字段边界接口检查通过。MigrationLoader(None)/MigrationAutodetector核对dashboard迁移与模型无差异，未打开数据库。
- 没有执行migrate、初始化、API CRUD、worker、模拟/理论循环或unittest，没有创建隔离工作树data目录。按计划集中功能验收仍在任务16；不把语法、导入、路由解析或源码复核当作端到端已验证。
- 原README、docs/local-usage.md和0001迁移无差异，主项目产品代码及真实v5库/原服务/服务器不变。实现只在隔离工作树，主目录同步进度文档；未提交、合并或推送。
- 旧固定图表辅助函数和其他未归属测试/前端调用继续在任务14/16迁移清理，不增加旧结果兼容层。当前后端契约已实现，前端页面尚未升级，不能将旧前端连接新版库验收。

待任务16集中执行新增及迁移用例：

```bash
"$LOTTERY_PYTHON" manage.py test tests.test_trace_store tests.test_trace_queries tests.test_job_models tests.test_limits tests.test_cli tests.test_dynamic_charts tests.web.test_owned_runs tests.web.test_owned_jobs tests.web.test_downloads tests.web.test_end_to_end tests.web.test_management tests.web.test_account_deletion tests.web.test_rules tests.web.test_pools tests.web.test_experiments tests.web.test_position_chart
```

任务9/10交付时的下一步为任务11；该项已在下方完成，任务12—14继续升级池、实验及结果页面。真实账号切换仍在另行授权的任务17。

## 任务11：共享前端类型与规则管理页面

- 新增RuleDocument/Rule、动态PoolDocument/Pool、ExperimentParameters、InitialContext及draw/character_grant判别联合；实验及事件计数、seed为十进制字符串，概率/权重为number。规则资源权限、修订及引用状态与纯定义document分开。默认JSON派生三个test-fixtures工厂。
- App增加受ProtectedLayout保护的规则导航与路由。Rules复用apiRequest及会话撤权机制，提供公共、本人、他人公开和管理员全部私有筛选，服务端先筛选再分页；后端限制普通用户访问全部私有范围。
- 实现查看、新建、编辑、复制、删除、原生导出及导入预览/确认。只读查看禁用输入；复制保留最初作者，导入确认提交原始JSON文本，新建当前账号隐藏私有规则。导出直接下载服务端原始文件，避免浏览器重序列化舍入整数。
- RuleEditor按设计分组，主池和首次赠送池均可配置概率及软/硬保底；展示大保底完整模式、目标由绑定池解析、关闭机制不生效、百分比/百分点及由配置派生的首增例子。关闭字段禁用并保留定义草稿。
- 稀有度以UUID为React key，新增/删除/上移/下移同步启用的赠送池ID及rank；已引用规则仅锁结构，参数可编辑并提示复制。兼容合法的关闭赠送池空定义与数组乱序，不假定数组位置代表同一ID。
- 数值输入保留本地十进制中间态，失焦换单位；非法文本、概率合计、非正软增幅及浏览器无法精确表示的规则整数阻止网页保存。服务端仍执行最终校验。修订冲突保留草稿，只在用户主动重新加载时替换；切换规则重置输入状态，加载请求取消防止旧页覆盖。
- 原固定池/实验页面仅将消费类型显式改名Legacy，保留过渡代码，未增加旧后端兼容层；这些页面和旧结果/任务类型仍须在任务12—14迁移。整体前端尚未可连接新版库验收。
- 新增规则页、编辑器用例及后端筛选用例，覆盖权限、结构锁、单位转换、无效输入、赠送池顺序、修订冲突、复制、分页和原文导入确认；未执行功能测试。

### 任务11实际检查与边界

- GPT-6-luna子代理分别实现类型、编辑器和页面，主代理复核实际接口及调用路径，修正只读元信息、引用结构、异步分页、测试夹具和文件整数精度问题。
- WSL TypeScript `tsc --noEmit`通过；新增后端筛选及测试文件以Python -B内存compile通过；Git diff --check通过。未运行Vitest、Django测试、浏览器验收或服务CRUD，集中验收仍在任务16。
- 原README、docs/local-usage.md和0001迁移无差异；隔离工作树无data目录。未提交、合并、推送、切换真实数据或重启已有服务。

任务11交付时的下一步为任务12；任务12—14已在下方实现。

## 任务12：动态角色池编辑与规则绑定

- Pools与PoolEditor改用动态PoolDocument/Rule，按基本信息、规则摘要、稀有度名单、机制目标、奖励及显示设置分组；概率与保底只读，规则摘要提供查看入口。名单默认来自JSON，各档角色保持UUID，支持新增、删除及排序，UP自动限定，权重明确是组内比例。
- 规则候选按池类型、可见性及所有者范围筛选；公共复制要求公共规则，管理员自身隐藏池的特例不用于绕过其他普通所有者权限。创建/修改携规则revision，修改另携池revision；复制核源池、源规则和目标规则修订，保留最初作者。
- 切换规则需确认映射或清空，每个删除档必须显式选择，不能合并到已占用档。角色、奖励和显示名按ID迁移；原位映射应用后先保存，再编辑名单，以符合后端对映射内容和顺序的校验。目标按实际角色ID解析，失效UP或选择绑定会阻止保存。
- 权重保留本地中间态，非法文本阻止保存；切换池或重新加载重置组件输入及映射状态。池文件两阶段导入提交原始JSON，原生导出保留数值。写入动态四档、权重、映射、权限、复制及修订冲突保留草稿用例，未执行。

## 任务13：初始条件与只读接受预览

- ExperimentForm及NewExperiment使用十进制参数文本；新增InitialConditions与SimulationPreview，保留保存配置和开始模拟独立动作。开始前先取得计数预览，核对后再接受任务，参数或上下文变化使原预览失效。
- 新增POST jobs/preview/，正式提交与预览共用_prepare_submission，重新读取权限、池/规则revision、编译规则及池、normalize和初始上下文；预览使用同一SimulationLimits/event_counts，不生成seed、不创建任务或写历史。返回每轮及全实验计数、当前上下文和下一赠送位置，整数均为十进制文本。
- 初始状态高级区域之外始终显示非零摘要及上下文变化提示。目标按最高档实际UP解析，获得后关闭与重新计数两种模式区别展示；关闭机制、旧档计数不静默丢弃，提供明确清除操作，数学非法值仍由服务端拒绝。
- 配置所有者池范围与管理员本人模拟池独立；配置与模拟上下文分别确认。保存、预览及接受pending锁输入，5xx或网络结果不明只查询本人任务，不自动重发；明确人工核对后才能开始新任务。大seed文件预览原文提交、导出原生下载。
- 写入目标变化不接受、预览后单次POST、保存不模拟、原始seed及不确定提交保护用例；后端补只读预览、未指定seed、H=0已获得拒绝、阈值下降拒绝、H=250已获得时下一赠送480及修订变化。未执行这些功能用例。

## 任务14：动态结果、历史与过程明细

- RunResult/RunSummary/JobDetail迁移实际冻结契约。概览显示主抽、轮数、赠送抽、真实总抽、直接赠送事件及角色数量、获得均值和理论期望，附双方快照修订、seed、耗时及事件数；分类按动态稀有度、角色、类别、奖励及保底比较模拟与理论，理论0相对误差不可用。
- 位置图仅聚合draw，支持动态多选、单档、主池/赠送来源、最多1000窗口、最近位置提示、有效轮数、自适应尺寸及50行表格分页。图形以窗口相对坐标定位，原始位置/计数保留十进制文本；计数轴超安全整数显示近似提示，表格保留精确值。
- TraceTable界面为过程明细，消费draw/grant判别联合。draw显示概率、奖励、保底及主状态变化；grant显示目标、数量及主抽位置，抽数/概率/奖励为不适用。grant清除并禁用来源位置筛选，保留稀有度/实际角色筛选。Trace总数改十进制文本，分页用BigInt，超API页上限提示缩小筛选。
- 原生Trace下载保留预开标签页、CSRF和服务端撤权/限额机制；非Trace明确不能事后补明细。历史汇总附件由授权后端输出原始完整JSON，避免浏览器重序列化快照整数。
- 历史显示两类快照；按当前池及规则重跑比较双方revision和初始上下文。上下文变化且非零时需要明确重置初始状态，取消停止重跑；真正提交参数重新预览和复验修订，不改旧历史。提交不确定封锁重发并人工核对，任务停止继续显示真实阶段、清理失败和历史保存状态，404停止旧轮询。
- 迁移并补结果、动态图表、过程事件、历史重跑及下载相关用例，覆盖grant、非Trace、单档、新档位、零值/大整数、目标变化、取消及404；功能运行仍待任务16。未使用的旧固定图表辅助函数和Legacy类型留任务16统一清理。

### 任务12—14实际检查与边界

- GPT-6-luna子代理分别实现三项任务，主代理复核调用路径与接口，修正所有者候选范围、非法输入保存、映射事务契约、初始模式、预览参数不一致、重跑确认及测试夹具。
- WSL TypeScript tsc --noEmit通过；7个相关Python文件和7段嵌入脚本内存compile通过；6个服务/API/测试模块导入和jobs/preview/路由解析通过，显式临时数据库路径未创建。Git diff --check通过。
- 未执行Vitest、Django测试、模拟/理论循环、迁移、服务CRUD或浏览器验收。隔离工作树无data目录；原README、本地使用手册和0001迁移无差异。主目录仅同步进度文档，真实v5数据、原服务和服务器不变，未提交/合并/推送。

任务12—14阶段交接已完成；任务15实施如下。


## 任务15：保留账号工具与v6部署、备份接口

- 新增 `import_v5_accounts --source` 与账号转移服务。源以SQLite只读连接和一致读事务读取；核对真实路径/samefile、版本5、完整旧迁移链和历史列、删除中账号/任何删除清单及可用管理员。目标必须是已完整迁移的独立v6文件，核对迁移记录、列与空账号/业务/会话等表，写事务内再复查。
- 原子保留完整User标量、LoginLimit及ID，auth_version递增；不迁Session、业务或旧迁移记录。命令仅返回数量，数据库错误不输出敏感内容；默认业务仍由独立初始化命令创建。
- Dockerfile、Compose、备份service使用v6库/jobs/exports及lottery-v6-前缀，保留systemd %%F。安装脚本要求完整规则默认文件，检查停止容器/已有卷、迁移前数据目录及初始化状态，升级迹象中文停止；原镜像、腾讯云配置流程、HTTPS、前端双目录挂载和已有.env保留流程维持。未运行真实安装。
- 编写独立文件型临时v5/v6用例：只迁账号/登录防护、原密码验证、旧会话不迁、源快照不变、删除中/清单拒绝、samefile、非空目标、无可用管理员、版本/迁移异常及写失败整笔回滚。假Docker用例与真实临时v6备份恢复用例按新接口更新，功能执行统一留任务16。
- Windows临时说明补备份→空v6 migrate→导入账号→init_business_defaults→路径配置→最终切换，说明备份私有内容及不自动恢复旧任务目录。原本地使用手册未修改。

### 任务15实际检查与边界

- WSL bash -n scripts/install.sh通过；6个Python文件及账号/假Docker/两段备份测试嵌入脚本内存compile通过；WSL 5个模块导入和命令参数解析通过，绑定的临时数据库路径未创建。
- 功能测试、迁移演练、worker与备份/恢复仍未执行；任务15为已实现、未集中验收。真实v5账号、服务和服务器不变，未提交/合并/推送。

下一步任务16集中验收与旧入口清理；任务17另行授权真实本地集成和切换。


## 任务16：集中验收、旧入口清理与操作文档

### 环境与实际命令

- 工作树仍为 `D:\Web_project\lottery_simulator\.worktrees\independent-rules-v6`，WSL路径为 `/mnt/d/Web_project/lottery_simulator/.worktrees/independent-rules-v6`。Linux解释器 `/home/lottery/.venvs/lottery-simulator/bin/python`，Node/npm `/usr/local/bin/`；未重装前端依赖。
- 用mktemp建立 `/tmp/lottery-v6-acceptance.taNdVb`，显式绑定history_v6.sqlite3、jobs_v6、exports_v6及解释器。各迁移/账号/备份探针另外使用自身独立临时文件；所有数据均为验收数据，未读取真实账号库。首轮日志的目录在后续WSL启动时未保留，后续同一路径重建并将日志写入工作树，再归档；不以目录存在推断测试成功。
- 最终执行 `manage.py test tests --verbosity 1`：242项通过，249.956秒。此前完整发现轮为277项、27失败/66错误；首次还因SchemaTests.run与unittest入口同名中断，修正后才得到完整失败列表。修复只重跑归属模块，随后完成上述全套回归。旧固定测试迁入动态契约后数量变化，不把删除旧接口用例当作修复通过。
- 全套回归后，补充账号全部标量对比发现UTC时间转换问题，修复后 `manage.py test tests.web.test_account_transfer --verbosity 1`：5项通过，23.825秒；另将阈值下降夹具的旧历史改为关闭软保底的可达状态，其归属1项通过，3.296秒。这两项后续变更未重跑无关模块。
- 前端 `npm --prefix frontend run test -- --run` 最终16文件、52项全部通过；`npm --prefix frontend run build` 的TypeScript与Vite构建通过。初轮45通过/6失败仅保留工具输出摘要，最终完整原始日志已归档；不将摘要冒充初轮完整日志。
- `bash -n scripts/install.sh`通过且脚本LF；`manage.py makemigrations --check --dry-run`显示No changes detected；showmigrations确认0001/0002已应用，临时库user_version=6、journal_mode=wal。

### 修复与旧入口清理

- 文件引用和规则/实验服务接受冻结定义的Mapping；边界仍校验ID/name的严格形状。TraceWriter设置sqlite3.Row，完成流校验不再把tuple误当映射；CLI文本输出按实际参数字典取历史计数；下载迭代器清理兼容可关闭及普通迭代器。
- 账号导入修复迁移记录dict/set比较、历史状态集合输入及UTC时间解释。User全部标量（除auth_version递增）和LoginLimit全部标量/ID按SQLite实际值比较；原密码可实际登录、旧会话不迁、默认业务可独立初始化，源快照不变，删除残留/同文件/版本异常与写失败回滚均通过。
- 理论按相同下一状态精确合并转移，缓存各角色/稀有度/类别边际与未命中质量，保留状态/分支限额、取消及质量守恒；不通过提高限额绕过默认240主抽失败。小树枚举、默认240和资源保护回归通过。
- SQLite连接启用WAL，下载的只读快照不再阻塞并发账号撤销；原IMMEDIATE写事务、busy错误和下载撤权检查保留。真实临时v6账号/会话/规则/池/历史事件的WAL备份恢复用例通过。
- 删除无调用方的Rule1/base/first_thirty_bonus/pool_config模块、旧固定默认文件和固定图表/显示名辅助入口。旧规则/池/图表测试的类型、权重、边界及布局用例迁入动态规则/定义/图表/配置/CLI测试；probability.py和原账号/会话安全用例保留。前端LegacyPool/LegacyExperiment类型已清理。
- 修复实验保存的规则加载等待、图表数值说明及结果页最近任务状态滞后；选中任务菜单直接使用匹配的实时详情，避免初始列表响应与终态轮询竞态，并有queued→completed回归。
- Git工作树指针原为Windows绝对路径，WSL不识别；改为等价相对路径，Windows与WSL均确认同一工作树，未改分支/索引/提交。node_modules为Linux依赖符号链接，忽略规则同时覆盖目录与链接，Git检查改核链接本身，私有文件忽略测试通过。

### 浏览器与实际产物

- 起始只读核对WSL及Windows端口，无8000/5173现有监听。Windows保留端口范围包含5173，因此直接localhost访问失败；私有WSL HTTP地址缺少crypto.randomUUID安全上下文。使用仅绑定127.0.0.1:18080的临时Node代理与临时Vite配置，未更改系统转发、浏览器安全策略或原Vite配置。
- CUA无可用浏览器；使用已有Windows bundled Playwright及已有Edge执行独立无头验收，未安装浏览器/包。临时库创建admin16/alice16，实际UI使用alice16，真实worker另进程运行。
- 实际DOM验证公共规则只读/引用提示、复制私有规则、结构编辑与池的显式档位映射；自有规则被池引用后Add rarity禁用，而概率与机制控件仍可编辑。
- 验证非零H=1且已获得目标的上下文明确确认；30×2预览与结果为主抽60、赠送20、总抽80。分类图与赠送来源/轮次/10位置筛选成功，数值表显示10行；原生汇总JSON与Trace JSONL成功，JSONL为export v2、嵌套event v3，80事件＋1元数据行。历史重跑实际接受新任务并显示链接。
- 默认240主抽、1轮、非Trace：预览240/10/250及直接赠送1，真实结果显示1次直接赠送、1个角色。另H=239、已获得目标、1主抽、Trace开启：显示2条事件；筛选直接赠送后仅1条、累计位置240、数量1，概率/奖励/保底不适用，来源和来源位置控件禁用。
- 大型非Trace任务实际提交后仅一次cancel POST，DOM到cancelled且无已保存历史链接；取消前后状态与工作单位计数已记录。
- 最后切换到最终dist预览；浏览器实际加载 `/assets/index-29lZozkw.js` 和 `index-ByJ5s0HX.css`，与dist/index.html一致且HTTP200；页面显示新建实验、zmd及正确completed菜单。不是仅凭build或服务启动判断新产物加载。

### 文档、证据与边界

- README、网页指南和部署指南补完整v6操作及账号保留/备份/回滚步骤，Windows临时说明记录本机验收与端口处理；原 `docs/local-usage.md` 和0001迁移保持原文。
- 完整日志、DOM输出、下载样本、截图与本轮临时辅助脚本归档在 `D:\Web_project\lottery-v6-acceptance-taNdVb`。辅助脚本仅记录本次实际环境，不作为部署入口；WSL地址须在以后使用时重新核对。
- Django保留RawSQL full_clean提示，数据库约束在用例中实际核对；Vite约1.22MB单包提示保留，未引入构建拆分工程。
- 验收结束已停止自己启动的WSL后端/预览和Windows代理，端口复查仅剩原DNS监听。真实v5库、原服务、服务器、GitHub均未变；未提交、合并、推送或执行真实切换。

任务16必需验收通过，状态为已验证但未合并。下一步任务17需明确真实账号来源后再做授权的本地集成和切换；不包含服务器升级。


### 2026-10-02收尾复核

上轮工具额度中断发生在额外检查残留浏览器子进程时，必需验收、证据归档及临时服务停止此前均已完成。本次只读确认Windows无本轮.task16 Node/无头浏览器残留，8000/5173/18080无监听；工作树无临时验收文件，归档中的后端、账号完整标量、前端与最终产物浏览器日志仍在。Git diff --check通过，原本地手册与0001迁移无差异。未重跑已通过且无代码变化的用例，未执行任务17。
