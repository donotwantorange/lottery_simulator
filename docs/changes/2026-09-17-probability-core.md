# 概率核心重构实施记录

## 状态与授权范围

✅ 任务1～12已完成并独立审查通过。完整目标见[design](2026-09-17-probability-core-design.md)和[计划](2026-09-17-probability-core-plan.md)。下文保留各阶段当时事实，最终结果见文末。

## 工作位置

- 分支：`feature/probability-core`。
- 隔离工作树：`/home/qykj/202607/test/lottery_simulator/.worktrees/probability-core`。
- 主目录master和已有未提交文档保持不变，文档已完整复制进工作树。
- 本阶段不提交、合并、推送或删除用户数据。

## 任务进度

| 任务 | 内容 | 状态 |
|---|---|---|
| 1 | 版本校验与采样环境信息 | 已完成，独立审查通过 |
| 2 | 通用概率执行器 | 已完成，独立审查通过 |
| 3 | 新配置、可选四五星名单、角色份额 | 已完成，独立审查通过 |
| 4 | 规则职责、显式硬保底及合法转换 | 已完成，独立审查通过 |
| 5 | 具名单抽、全星级选角及新Trace | 已完成，独立审查通过 |
| 6 | 理论递推及旧advance删除 | 已完成，独立审查通过 |
| 7 | 配置编辑保留四五星名单 | 已完成，独立审查通过 |
| 8 | 新结果、CLI及v3历史库 | 已完成，独立审查通过 |
| 9 | 中文Trace及运行信息 | 已完成，独立审查通过 |
| 10 | 任务版本、worker与旧结果隔离 | 已完成，独立审查通过 |
| 11 | v3路径静态合同与使用文档 | 已完成，独立审查通过 |
| 12 | 集成回归、全套CLI/UI验收与只读清理盘点 | 已完成，独立审查通过；现场项明确未验 |

## 功能基线

✅ 在隔离工作树运行主venv的 `python -m unittest discover -q`：238 tests，91.605s，OK，exit0。输出包含现有CLI拒绝用例的错误信息和Streamlit bare-mode提示，不是本次修改引入。

该结果证明重构开始前现有测试通过，不证明新功能或浏览器已通过。

## 阶段边界与裁定

- 只完成任务1～3，不提前接入任务4～12。任务3启用新配置版本后，网页编辑重建配置由任务7补齐；隔离分支不是当前可直接替换主服务的完成版本。
- 不建立Git提交，审查使用任务范围工作树差异；恢复依据台账、报告与未提交工作树。
- 中文任务标题不为脚本改名，精确简报由计划原文提取并用apply_patch写入；提供给审查者的差异包含新增文件。
- 完整计划尚未结束，保留本计划独立审计目录，后续从任务4继续而不是重做已完成任务。

## 具体实现、验证与Git

任务1新增formats.py、test_formats.py：缺接口RED exit1，最小实现GREEN exit0；type变异为isinstance导致True拒绝检查失败exit1，恢复后3tests exit0。主代理独立运行同组3tests exit0；Terra独立规格与质量审查Approved，无问题。

本阶段所有改动均未提交，未合并到master或推送。

任务2新增probability.py与test_probability.py，9tests exit0；<=阈值变异导致失败exit1，恢复exit0。另以bytes概率/roll获得两个行为失败，再用既有Real数值边界拒绝后通过。主代理独立formats+probability共12tests exit0，Terra规格/质量审查Approved，无问题。

### 任务3实际内容

修改pool_config.py、默认配置JSON、analysis.py、charts.py和Rule1临时角色选择入口；更新pool_config/charts测试及engine的完整配置快照fixture。

- 新配置format_version整数1必填，不兼容旧无版本配置。
- 新增不可变WeightedCharacter及四五星空名单预留，按对应名单正权重归一化；同星级重名拒绝，跨星级同名允许。
- 角色概率统一character_probabilities(rarity)，角色按配置顺序；删除原配置六星专用函数，不保留别名。
- 大有限权重先按最大权重缩放，避免求和溢出。
- rarity必须整数4/5/6，拒绝bool、4.0、字符串及其它值。

前Terra实现者额度中断，由Luna收尾。初始名单RED/顺序变异的交接摘要不冒充后代理实测；后代理实际记录权重分母破坏导致OverflowError、图表旧接口恢复导致AttributeError、rarity4.0校验行为RED后最小修复GREEN。一个仅将fsum变sum的无效变异没有被当作因果证据。最后22项目标测试恢复通过，Sol独立规格/质量审查Approved，无问题。

### 阶段最终功能检查

| 主代理检查 | 结果 |
|---|---|
| formats/probability/pool_config/charts | 34tests，0.005s，exit0 |
| rule_1/bonus_rule/analysis | 37tests，0.232s，exit0 |
| engine完整配置快照、汇总守恒、赠送Trace | 3tests，0.017s，exit0 |
| CLI初始29主抽1单轮Trace | 1主抽+10赠送、累计30、11条记录、配置v1，exit0 |

✅ 以上74项不同测试及CLI功能检查通过，三个任务的独立审查均无问题。⚠️ 这不是重构后全套功能验收，也不是浏览器验收。完整网页配置链路、通用四五星实际选角及数据库v3仍待后续任务，不应启动该隔离分支替换主服务。

无数据库升级、旧历史删除、依赖安装、服务器变更、Git提交、合并或在线推送。后续从任务4继续，本计划审计台账保留在隔离工作树中。

## 第二阶段：任务4、5、6

三项按序由Sol高强度实现并独立审查，规格与质量均Approved，无未解决问题；完成任务6后暂停。

- 任务4新增角色概率委托、显式六星硬保底和合法转换校验。主池六星计数0～79，固定池仅要求非负且无80硬保底；四星余量只允许1e-12内舍入归0，赠送继承三类名单/奖励/UP。
- 任务5统一执行器每抽先选星级再选角色，四五星名单正式生效；返回DrawResult，角色使用character_name。Trace嵌套来源池结果并独立记录主池前后状态，默认False、拒None、仍单轮；删除pick_six_star和旧字段。批量角色统计仍仅六星。
- 任务6等待时间只追踪六星进度（offset0），有限期望保留真实双状态分支；模拟/理论共用显式硬保底。expected_six_stars委托联合DP，固定池周期拒绝、有限期望可用；删除旧advance。

| 任务 | 最终测试及因果验证 |
|---|---|
| 4 | 指定29tests、扩展98tests均exit0；硬标记计数变异3处失败后恢复GREEN |
| 5 | 指定47tests、77.766s、exit0；跳过单人角色roll及赠送污染主状态均失败后恢复GREEN |
| 6 | 指定103tests、78.155s、exit0；理论计数硬标记变异3处失败后恢复GREEN |

任务4首次扩展回归发现既有子类未调用super构造导致AttributeError，正面复现后沿用原getattr缺省主池行为修复，扩展回归恢复通过。任务4审查Minor指出unused main_state断言无效；任务5删除并以真实simulate链和状态污染变异证明隔离，已闭合。

✅ 主代理最终快速核心组126tests、0.678s、exit0；唯一100001主抽测试已包含任务6完整组。阶段共覆盖127项不同测试，不是全仓测试。另独立规则29、赠送9、分析/规则46项均exit0，git diff --check exit0。

✅ 带四五星名单seed42、初始29、主抽1功能检查exit0：10赠送、11记录、累计30、具名角色、record版本1、唯一嵌套字段、双池隔离、Trace一致、等待质量1、固定池79位六星硬触发0。

第一次功能检查命令误清空无记录结果后与带记录结果比较，断言失败；逐字段诊断确认除records外无差异，纠正为清空带记录结果后比较，完整检查exit0。未因此修改生产代码或隐去失败。

本阶段裁定：任务6同步更新test_rule_1.py三处旧advance消费者（Files未列但指定组含它，全局交接要求同步新契约）；代价为多改一个测试文件，没有扩展功能。沿用隔离树与审计台账，不重做1～3，不提交、合并、推送、删历史或干扰服务。

⚠️ 未全应用、浏览器或服务器验收。网页配置任务7、CLI/新库任务8、中文Trace任务9、新任务文件任务10、路径/手册任务11及最终验收任务12未实施。不能以该隔离分支替换主服务；master代码未受影响。后续从任务7继续。

## 第三阶段：任务7、8、9（2026-09-18）

✅ 三项按序实施并独立审查，规格与质量均Approved，无阻断项。完成任务9后暂停，不继续10。

- 任务7由Luna实现：editor_rows_to_config增加两份默认空名单和格式版本；session统一set、render重建、导入/导出/历史复用不丢四五星名单，默认恢复清空。保留稳定data_editor baseline，不增加四五星表格；摘要显示人数和JSON修改方式。
- 任务8由Sol实现：模拟结果加入result_format_version、sampling_version及随机源/Python环境，rule_version仍字符串2.0；非Trace不输出records，文字Trace读取嵌套字段。仓库user_version及schema_version改3，保持两表、级联和同事务；保存前严格检查版本及必要嵌套类型，读取时验证，拒绝旧库、不迁移。
- 任务9由Luna起步、Sol收尾：新增纯trace_rows展开完整中文列，主/来源池状态独立、角色与奖励顺序正确。当前与历史共render_result，使用NumberColumn公开percent格式，JSON仍0～1；运行采样环境信息放折叠区，下载保持嵌套原JSON。

| 任务 | 实际最终验证 | 干预与恢复 |
|---|---|---|
| 7 | configuration_view 9tests，exit0；controller独立9tests exit0 | 删四星名单转交，目标断言失败，恢复GREEN |
| 8 | CLI/models/repository 67tests，exit0；相关203tests/80.262s/exit0；controller67tests exit0 | 删除sampling版本校验，bool测试失败，恢复GREEN |
| 9 | trace_view/simulation_view 9tests，exit0；controller9tests exit0 | main读source映射失败、撤回percent格式失败，恢复GREEN |

任务9原Luna长时间未回复验证进度，controller暂停后由Sol接手，未同时运行两名实现者。接手时正确percent实现已存在，保留代码。报告明确区分前代理初始RED自述与接手者亲见证据，未虚构接手者test-first日志。

✅ 安装版Streamlit前端formatNumber函数正面实测0→0%、0.008→0.8%、0.08→8%、0.912→91.2%、1→100%，exit0。前两次Node环境准备失败（不支持flag、缺window）均记录为环境失败，不冒充业务RED。这不代表浏览器/部署实测。

### 主代理最终功能检查

- 14个相关模块快速组211tests、2.673s、exit0；唯一100001抽已包含任务8扩大回归，不另重复。本阶段覆盖212项不同测试，不能称全仓验收。
- CLI初始29主抽1+赠送10单轮Trace：11记录、累计30、格式/采样1及环境信息；非Trace30抽10轮无records；analyze格式1且无sampling。三条实际CLI检查exit0。
- TemporaryDirectory功能链：EditorBoundary非空四五星名单→修改UP/奖励→导出保留→统一set默认清空→模拟→新payload→v3临时库保存读取→中文Trace→历史模式原JSON下载，exit0。确认11记录、累计30、来源池计数0与主池计数30各归其列，输入payload不变。
- git diff --check exit0；主目录master仍只有此前用户文档改动，代码未被本分支修改。

任务7审查有两项Minor覆盖建议：持久测试增强非空五星及非空名单连续编辑/默认重置。这些实际行为已在上述功能链正面验证；持久回归测试增强留任务12，不隐去审查意见。任务8/9审查无问题。详细命令、失败输出及恢复证据在本计划scratch报告/审查包，台账保留便于恢复。

⚠️ 未运行全应用、浏览器或服务器验收；任务10的新job版本/jobs_v3与app默认库路径、任务11部署合同/使用手册、任务12整体验收/受控切换仍待实施。库结构虽然已v3，用户实际库未升级、删除或迁移；不能用该隔离分支直接替换主服务。

无Git提交、合并、推送、历史清理或运行服务改动。后续从任务10继续。

## 第四阶段：任务10、11、12（2026-09-18）

✅ 三项按序完成并经独立审查，任务10和11各有一轮审查修复，任务12集成测试的Minor也已闭合。

- 任务10为RunParameters/JobState加入显式job_format_version与sampling_version文件校验；worker在queued转running前验证参数。JobManager跳过无效state，旧PID不能驱动kill；结果同时校验result/sampling版本。app默认切到history_v3.sqlite3和jobs_v3，并清理失效任务、历史选择、复用和删除引用。审查要求恢复“已停用规则可筛选但不可复用”的既有业务回归，并真实观察非法参数不会写running状态，修复后79项指定测试通过。
- 任务11统一本机、Compose、Dockerfile和systemd备份的v3路径；备份源为lottery_v3.sqlite3、文件名前缀lottery-v3-，镜像只预建jobs_v3。README、本地使用、页面指南和部署手册补齐Trace、sampling/rule复现条件及完整四五星名单JSON示例。指定部署测试9项通过，配置示例和12个文档链接验证通过；没有改变认证、端口、卷或secrets机制。
- 任务12新增真实端到端回归：EditorBoundary非空四星1:3/五星单人名单，经UP和奖励编辑后启动同步worker，初始29主抽1触发10赠送，11条嵌套记录、主池累计30、赠送不改变主状态；config/result/record/sampling均为1，SQLite user/schema为3，两次同seed结果及两条历史持久化一致。丢弃四星名单及第二次保存失败的定向变异均使测试失败，恢复后审查Approved。

### 最终验证

- ✅ 最终文件状态运行 `python -m unittest discover -q`：311 tests，93.933s，OK；总耗时94.58s，exit0。CLI负例stderr与Streamlit bare-mode提示为预期测试输出。
- ✅ 三条真实CLI命令exit0：analyze为rule 2.0/result1且无sampling；30抽×1000轮非Trace为result/sampling1且无records；初始29、主抽1的Trace为1主+10赠送、11records、final_main_draws=30。
- ✅ Rule1边界：第65抽0.8%、第66抽5.8%、第79抽70.8%、第80抽100%且显式硬保底为True。
- ✅ 临时目录启动Streamlit于127.0.0.1:8765，健康端点返回ok后正常停止；全套AppTest覆盖连续配置编辑、模拟、中文Trace、历史复用/下载/删除。
- ✅ `git diff --check`与旧接口/旧Trace键扫描通过；没有加入多轮Trace、位置图、新依赖、认证变化或迁移fallback。

### 旧数据与未验边界

只读盘点确认主目录现有 `data/history.sqlite3` 为user_version 1、`data/history_v2.sqlite3` 为user_version 2；`data/jobs/`有6个completed旧任务，均缺job_format_version/sampling_version，另有各自worker.log和active.lock。未发现运行中的本项目Streamlit或worker，未发现实际history_v3库。当前隔离分支尚未合并，因此删除清单为空：没有停止用户服务、删除旧库/任务、清session或在用户目录创建v3数据。旧文件目前仍在，可由现存文件用于旧版本恢复；是否另有备份未核实。

⚠️ 当前环境没有可用的交互浏览器控制接口，所以没有把AppTest冒充真实浏览器点击验收；Docker/Caddy/OIDC/systemd、公网域名、卷权限和现场旧数据清理同样未执行。它们属于合并后的实际切换步骤。无Git提交、合并或推送。

### 最终整分支审查

最高强度独立整分支审查核对全部production/test差异和12项计划，未发现Critical或Important。唯一Minor是CLI Trace文本测试曾删掉第30主抽与第40赠送的五星保底触发为“是”断言；已按新嵌套字段恢复两条完整输出断言，定向把触发标记置False时测试失败，恢复后复审为clean Approved。

✅ 最终修复后的新鲜全套运行：311 tests，92.177s，OK；总耗时92.79s，exit0。`git diff --check`通过。最终审查与修复报告保存在本计划的SDD审计目录；因计划禁止自动提交且工作树仍含全部未提交实现，未删除该审计目录。
