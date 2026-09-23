# 网页使用体验与任务控制改进实施记录

日期：2026-09-22

状态：已本地合并（浏览器仅部分验收；剩余项目由用户自行查看）

本阶段独立审查：任务1～4经子代理逐项审查及修复复审。任务5的独立审查因子代理额度中断，改由主代理核对关键状态、锁和清理路径；不将其称为已完成独立复审。

## 任务2：共享控制接口与兼容任务状态

新增 `lottery_simulator/control.py` 统一取消异常及回调类型，`engine` 保留旧导入身份；`JobState` 增加可缺省的阶段进度、取消请求和清理错误字段，严格校验类型、范围与成对关系。旧状态缺字段仍可读，任务版本不变。初审发现终态 `dataclasses.replace` 会保留阶段计数，修复轮补齐 worker、manager、reaper 的 completed/cancelled/failed 清空路径。专项先 RED 9/10，修复后 10/10；`tests.test_dashboard_models tests.test_engine tests.test_jobs tests.test_trace_lifecycle` 共107项通过，独立复审通过。

## 任务1：概览两行汇总与醒目轮数

目的：概览抽数固定显示“每轮”和“全实验（T轮）”两行；结果页顶部从当前结果快照显示轮数、主池／赠送规模和全实验总抽数。不读取新建实验草稿，不改变抽样、统计、Trace或历史格式。

涉及文件：

- `dashboard/views/simulation.py`
- `dashboard/app.py`
- `tests/test_simulation_view.py`
- `tests/test_dashboard_app.py`

验证过程：

1. RED：先加入大轮数、初始29且1主抽/10赠送/3轮的概览测试及顶部轮数断言；旧实现失败。十万轮用例生成 `100001 != 2` 行，初始历史用例得到 `11 != 33`，顶部摘要断言失败。
2. GREEN：将逐轮循环替换为两行 `rows`，全实验行使用 `draws * trials`、`bonus * trials` 和 `(draws + bonus) * trials`；顶部摘要使用 payload 的 `draws`、`bonus_draws`、`trials`。命令 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_simulation_view tests.test_dashboard_app -q`：57项通过，退出0。
3. 因果对照：临时撤回两行生成逻辑后，只运行两项新增概览测试，重新失败：`100001 != 2`、`11 != 33`，退出1；随后恢复两行实现并再次运行上述57项测试，全部通过，退出0。

自检：

- 结果摘要只取 payload 快照字段；初始假设历史抽数不加入新增抽数。
- `_render_overview` 与 `render_result` 接口保持不变；未访问 Trace reader。
- 未新增依赖、未改规则／随机顺序／统计／v4格式；未提交、合并或推送。

未验事项：真实浏览器视觉布局、窄屏和键盘验收留后续任务；完整测试套件不在本任务范围内。

Git状态：未提交、未合并、未推送。

## 任务3：理论计算与赠送循环可取消

目的：理论 DP 与赠送抽循环响应同一取消信号；模拟入口报告“模拟中”和“理论计算”两个阶段，但不改变主抽进度回调、浮点累加顺序、随机数消耗、结果或 Trace。

涉及文件：

- `lottery_simulator/analysis.py`
- `lottery_simulator/engine.py`
- `tests/test_analysis.py`
- `tests/test_engine.py`

验证过程：

1. RED：先增加理论取消、理论阶段取消、赠送第 2 抽取消和固定 seed 的 callback／Trace 对照。运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_analysis tests.test_engine -q`：77 项中新增 4 个接口 `TypeError`，赠送取消测试未抛出异常，退出 1。
2. GREEN：理论入口与返回前、每次抽次递推、每 1000 个 DP 状态及赠送事件扫描均复用 `lottery_simulator.control.check_cancelled`；子理论调用透传同一检查。`simulate` 在模拟和理论入口分别报告阶段，理论计算透传取消检查，赠送每抽检查。针对性 5 项测试：通过，退出 0。
3. 确定性对照：固定 seed=42、30 主抽、2 轮；无回调非 Trace 与带回调非 Trace `SimulationResult` 相等；带回调的内存 Trace（80 条）与 sink Trace 的统计相等，sink 逐条记录等于内存记录。此测试覆盖理论统计，故也确认没有改变浮点累加结果；记录相等确认没有改变抽样或 Trace 顺序。
4. 最终回归：`/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_analysis tests.test_engine tests.test_cli -q`：106 项通过，退出 0，耗时 85.308 秒；`git diff --check` 通过。

自检：

- ✅ 新参数都位于原接口末尾并为关键字可选参数；`progress_callback(completed, total)` 仍只反映主抽进度。
- ✅ 取消异常与回调类型复用任务2的共享 `control` 接口；不新增依赖。
- ✅ 代码不重排随机调用或浮点累加；未提交、合并或推送。
- ⚠️ 取消检查回调本身由调用方提供，其执行时间不在此任务的确定性数据对照范围内。

### 任务3修复轮1：无回调 Trace 基线

审查发现原确定性测试的无回调基线未开启 Trace，无法证明 callback 不改变逐条记录。RED 时先直接比较带回调内存 Trace 的 80 条记录与该空基线，单项测试按预期失败。GREEN 后基线改为相同 seed=42、30 主抽、2 轮、`collect_records=True` 且完全不传回调的内存 Trace；其记录直接等于同时带 phase/progress 回调的内存 Trace，后者又逐条等于带回调 sink 的记录。聚合对照规范化 Trace 存储字段；`SimulationResult` 无墙钟耗时字段，故不比较 worker payload 的 `duration_seconds`。最终命令 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_analysis tests.test_engine tests.test_cli -q`：106 项通过，退出 0，耗时 84.569 秒。

## 任务4：明细校验与历史导入进度

目的：Trace 明细校验和历史导入均报告统一的 `(completed, total)` 进度；取消或进度回调异常时不发布完整 Trace metadata，也不留下半份历史。进度总数包含赠送抽数，100% 仅表示扫描／导入完成，不能表示历史已经提交。

涉及文件：

- `dashboard/trace_store.py`
- `dashboard/repository.py`
- `tests/test_trace_store.py`
- `tests/test_repository.py`

验证过程：

1. RED：先增加带初始29、2主抽、10赠送（共12条）的进度、取消和回调异常测试。运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_trace_store tests.test_repository -q`：50 项中新增 4 项报 `TypeError`，两个接口均不接受 `progress_callback`，`TraceWriter.finish` 也不接受 `cancel_check`，退出 1。
2. GREEN：`finish` 在入口、flush 前后、每个既有 `batch_size` 校验边界及 complete 标记前检查共享取消信号；校验通过的中间批次报告进度，全部语义校验后才报告 `(total, total)`，随后仍在标记 complete 前再次取消检查。逐行读取仍保留原有“读取下一行前先校验当前行”约束。
3. 历史导入沿用原批次和一个 SQLite 事务：导入开始报告 `(0,total)`，每批插入后报告进度；最终 `(total,total)` 出现在 `connection.commit()` 前。观察者连接在 100% 回调中仍只能看到 0 条 `simulation_runs`，取消或进度回调异常后汇总和明细均为 `(0,0)`。
4. 最终回归：同一命令 50 项通过，退出 0；`git diff --check` 无输出且退出 0。

自检：

- ✅ 复用 `lottery_simulator.control.ProgressCallback` 和 `check_cancelled`；未改变 v4 schema、事务边界、save_run 幂等路径、参数验证或 JSON 投影重验。
- ✅ Trace 的完成 metadata 只在所有校验、最终进度回调和最终取消检查后写入；异常回滚该 metadata 更新。
- ✅ 历史导入的 progress 异常／取消会由原有事务异常路径回滚，连接关闭路径保持不变。
- ⚠️ `TraceWriter` 的 append 已在 finish 前按原有批次落盘；取消时该私有 trace 仍可能含未发布记录，但 `complete=0`，`TraceReader` 拒绝读取。它不是可见历史数据。

### 任务4修复轮1：批次后、下一边界取消

审查指出原批次取消计数会在循环第一条记录前触发，未能证明已完整校验一批之后仍有取消点。测试改用 `batch_size=2` 和第5次取消检查：前三次为入口／flush 前后，第4次是首批开始，首批两条校验并通知 `(2,12)` 后，第5次才在下一批边界取消。临时删除循环的周期检查后，专项测试按预期失败，实际进度错误地走到 `[(0,12), (2,12), (4,12), (6,12), (8,12), (10,12), (12,12)]`；因此也能阻止实现退化为只在入口检查。恢复该唯一检查后，专项单测和 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_trace_store tests.test_repository -q`（50项）均通过，`git diff --check` 通过。

Deferred Minor：损坏 trace 的校验可能在最终回滚前短暂报告 `completed > total`；本轮不扩大范围，原子回滚与不发布 complete metadata 的保障不变。

## 任务5：worker 阶段、安全停止与清理

✅ 已验证：Trace worker 阶段为 `simulating → theory → validating → saving → committing`，非 Trace 跳过 validating。共用 publish_phase，在阶段边界及末次通知立即写盘，同阶段中间通知按单调时钟0.5秒节流。主抽 completed_units / total_units 不混入 Trace 明细数。提交锁内直接写 committing 和 completed，不重入回调锁。

✅ 已验证：cancel 在任务锁内同时记录取消文件和 cancel_requested；UI 优先显示停止请求并禁用重复按钮，未知阶段进度不借用已完成主抽条。worker / 已确认退出的 manager 共用停止清理路径，关闭writer及回滚/关闭历史连接后才清理。明确清理 result（仅部分结果）、Trace与伴随文件，保留参数、状态、日志及未知临时文件；取消标记最后删除。

✅ 已验证：PermissionError 时终态可 cancelled，但保留标记和 cleanup_error；UI显示“计算已停止，残次文件清理未完成”。reaper/重启可识别错误或仅存标记并重试，不误改为普通失败。提交已成功时保留完整结果并校正 completed；探测读库失败时保留 active 和文件，继续阻止冲突任务。原保存失败完整结果保护继续通过。

测试先行与对照：

1. 新增 worker/manager/AppTest 后，三组107项首轮 RED：11个断言失败、1个未处理 PermissionError；阶段接线/清理后全部通过。
2. 确定性时钟节流专项先 RED（实际主抽写盘 `[1,2,3,4]`，期望 `[3,4]`），统一主抽进度后通过。终态仅有取消标记的重试、无效参数残留伴随文件也先观察失败再修复。
3. 使用 Event 控制提交完成到终态发布之间的取消竞争；真实回调控制理论、校验和导入取消。覆盖提交成功但首次状态写失败、历史读库不可用、worker未退出、删除权限错误、reaper幂等及保存失败保护。新增测试不使用固定sleep。
4. 在隔离worktree暂时移除 worker→finish 的取消检查；取消集成测试按预期失败：请求停止后仍出现第二次 validating 通知。finally立即恢复，确认不是仅靠最后发布 cancelled 掩盖中途继续工作。
5. 最终命令 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_jobs tests.test_trace_lifecycle tests.test_dashboard_app -q`：111项通过，20.672秒，退出0；`git diff --check` 通过。临时目录断言其他任务、配置、日志和数据库旁文件均保留。

⚠️ 作用边界：0.5秒只约束中间状态写入频率，不保证外部I/O或协作取消的总延迟。未知提交保留active是保守保护；权限错误须待权限恢复后才可能真正清理。测试耗时不是性能优化结论。未提交、合并、推送或新增依赖；完整任务报告位于同主题 `.superpowers/sdd/2026-09-22-dashboard-usability-task-control-plan/task-5-report.md`。

### 任务5补充审查：历史库暂时不可见

主代理复核 `_recover_committed` 时发现：历史库路径暂时不存在被当作“确定未提交”，使 reaper 把活动任务标为 failed 并清理本地结果。新增临时库测试先 RED（实际 `failed != running`）；将“库不存在”归入提交状态未知，保留 active 和输出，库恢复后再确认已提交并校正 completed。另一条启动恢复测试原意是验证已存在空库下的未提交任务，因此明确在测试中初始化该空库。两种定向测试通过；任务1～5相关十组共289项通过，退出0。此结论仅覆盖测试中的库暂缺/恢复与空库情形，不证明所有外部文件系统故障都可恢复。

任务5独立审查未完成（子代理额度中断）；主代理核对了提交锁、状态持久化、清理顺序和未知提交保护。该审查限制不等于功能测试失败，后续最终整体验收仍需覆盖任务6～10。

## 任务6：五类统计统一带数值并排柱

目的：五类分类统计统一展示模拟均值与理论期望的分组并排柱、可读标签和高精度提示；不改变已有统计投影、统计值、JSON 原始数值或历史数据。历史比较继续复用结果页分类渲染，不查询 Trace。

涉及文件：

- `dashboard/charts.py`
- `dashboard/views/simulation.py`
- `tests/test_charts.py`
- `tests/test_simulation_view.py`
- `.superpowers/sdd/2026-09-22-dashboard-usability-task-control-plan/task-6-report.md`

验证过程：

1. RED：先加入 `format_comparison_value`、长表/规格、五分支 Altair 记录和未配置奖励测试；指定两组测试先因新接口不存在导入失败，旧渲染没有 Altair 图和空奖励提示，退出1。
2. GREEN：实现共享 `comparison_bar_chart` 和五分支接线。长表固定为 `类别/系列/值/标签`，系列固定“模拟均值”“理论期望”；使用 xOffset/yOffset 分组、显式颜色与图例顺序、bar/text 同偏移与顺序、`stack=None`、12 位有效数字 tooltip。角色超过8项或名称超过8字符时横向并增加高度；未配置奖励显示空状态，数值表仍在图表下方。
3. 格式边界覆盖 `0 → "0"`、`1.25 → "1.2500"`、`0.000001` 科学计数法；零值、相同值、差距值及长角色名均检查规格中的标签和类别保留。
4. 最终指定命令 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_charts tests.test_simulation_view -q`：23项通过，退出0；`git diff --check` 通过。

自检：

- ✅ Altair 版本为6.2.2，未新增依赖；既有 rarity/character/reward/pity 投影和角色无六星时的 `None` 占比保持不变。
- ✅ `RecordingStreamlit.altair_chart` 已记录图表，历史 `_render_category` 路径继续复用。
- ⚠️ 未进行真实浏览器视觉验收；标签拥挤、窄屏和键盘检查留任务10。仅运行 brief 指定测试，未将局部 GREEN 推广为完整回归结论。

未提交、未合并、未推送。

### 任务8修复轮1：轮次输入列归属与缺失断言

审查发现指定轮次／轮次范围的数字输入仍调用根 `st`，没有落在第一组轮次列，焦点顺序与布局契约不符。将 focused fake 改为可区分的列代理后先观察 RED：14项中指定轮次和轮次范围两个子用例失败，失败点均为输入未记录在列0。

最小修复将“指定轮次”“轮次起”“轮次止”改为 `primary[0].number_input`，保留原 key、范围和筛选值；补充默认第1轮、基础列不含概率字段、未Trace早退不进入明细查询的断言。指定命令 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_trace_details tests.test_dashboard_app -q`：73项通过，退出0。⚠️ 真实浏览器焦点/视觉验收仍留任务10；未提交、未合并、未推送。

### 任务8修复轮2：列组编号测试严谨性

审查指出此前列代理只记录局部列号，若误放到第二组的第0列，断言仍可能通过。测试替身现记录 `columns()` 组号和组内列号；将断言故意改为第二组第0列 `(1, 0, ...)` 后，指定轮次与轮次范围两个子用例均按预期 RED，恢复为第一组第0列 `(0, 0, ...)` 后，指定命令 73项通过。仅增强测试替身与断言，生产代码未改；未提交、未合并、未推送。

### 任务6修复轮1：数值列精度与图表值域头部空间

审查发现两项 Important，均已按 TDD 修复：

1. 分类图下方的数值表原先未传 `column_config`，无法明确约12位有效数字展示。现在仅对实际数值列传入 Streamlit 1.63.0 公共 `st.column_config.NumberColumn(format="%.12g")`；原始 Python 数值、汇总表数据和下载 JSON 不变。RecordingStreamlit 增加 dataframe kwargs 与最小列配置替身，并有规格断言。
2. 量化轴原先只有 `Scale(padding=0.15)`，不能证明最大柱标签有值域空间。现在根据长表数值设置显式 domain：非负正值为 `[0, 1.2×最大值]`，全零为 `[0,1]`，极小值不足以放大时使用 `nextafter`；分类轴留白仍独立保留。新增规格测试覆盖 tiny nonzero 和全零。

验证过程：

- RED：新增两项测试后，指定命令报 `KeyError: column_config` 与 `KeyError: domain`，退出1。
- GREEN：`/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_charts tests.test_simulation_view -q`：25项通过，退出0；`git diff --check` 通过。

作用边界：值域测试证明规格为最大值保留量化头部空间，不替代任务10的真实浏览器拥挤/窄屏验收。未提交、未合并、未推送。

## 任务7：新建实验与结果页布局

✅ 已验证：新建实验使用公共列布局，主池抽数和实验轮数并列，完整“假设主池已累计多少抽仍未出6星”标签独占一行；启动摘要位于较窄列，奖池配置、高级设置和规则预览保持全宽。Trace 展示为“保存逐抽明细（Trace）”，内部草稿字段与稳定 widget key 不变。

✅ 已验证：启动参数只由本轮配置编辑器返回的有效 `PoolConfig` 构造并验证。无效配置、种子、参数或 Trace 上限会在启动区域显示并禁用开始按钮；草稿跨页、多次编辑、历史复用回新建页而不启动、以及结果快照不受后续草稿编辑影响均由 AppTest 覆盖。结果公共区显示身份、规模、保存状态、复用和唯一汇总下载；快照仍折叠。结果选择为保留既有 owner key 的横向 radio，四个结果分支继续惰性渲染，概览/分类不触碰 TraceReader。

测试先行与对照：先添加 AppTest 和 RecordingStreamlit 断言，旧实现运行 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_dashboard_app tests.test_configuration_view tests.test_simulation_view -q` 后为 1 个失败、9 个错误（79 项，退出1）：结果仍为 selectbox、Trace 标签未更新、无效参数未禁用启动。实现后通过；再临时将结果 radio 的 `horizontal=True` 撤为 `False`，同一命令仅横向 radio 断言失败，恢复后最终 79 项通过、16.662 秒、退出0。

⚠️ Streamlit bare-mode `missing ScriptRunContext` 与既有故障注入历史库日志仍出现在测试输出，但没有失败。未进行浏览器窄窗口、文字换行或焦点顺序验收，按任务边界留任务10；不以本轮单元/AppTest 结果宣称视觉验收。未提交、未合并、未推送；详细证据见 `.superpowers/sdd/2026-09-22-dashboard-usability-task-control-plan/task-7-report.md`。

### 任务7修复轮1：启动摘要实验轮数

审查发现启动摘要遗漏设计 §3.2 的“实验轮数”。先新增 AppTest，将当前草稿轮数从3改到7，分别断言摘要显示 `实验轮数：3` 与 `实验轮数：7`；旧实现指定三组测试中仅此断言失败（80项，退出1）。最小修复在已有每轮摘要 caption 前加入本轮 `trials`，不改变草稿、配置验证、按钮状态或布局。恢复后 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_dashboard_app tests.test_configuration_view tests.test_simulation_view -q`：80项通过、16.916秒、退出0。⚠️ 既有 bare-mode 警告仍在，真实浏览器窄屏/焦点验收继续留任务10；未提交、未合并、未推送。

## 任务8：Trace筛选、分页和下载布局

目的：保持既有 TraceFilter、按需 reader 查询、结果归属、下载签名/缓存、上限和分页契约，仅整理明细筛选与操作布局，并补充位置分析和概率尺度说明。

涉及文件：

- `dashboard/views/trace_details.py`
- `tests/test_trace_details.py`
- `tests/test_dashboard_app.py`（本任务未需新增改动；既有 AppTest 覆盖结果切换、分页、筛选和位置上限）
- `.superpowers/sdd/2026-09-22-dashboard-usability-task-control-plan/task-8-report.md`

验证过程：

1. RED：先加入筛选/操作分组、完整列概率尺度、位置分析轴与分母说明断言；在生产代码未改时运行 focused Trace 测试，7项中2项按预期失败（缺少列分组、缺少说明）。同时修正 focused fake 的结果视图 radio 未返回所选视图问题，避免把替身缺陷误判为生产回归。
2. GREEN：轮次/来源/星级改为第一组公共 `columns`，角色与可折叠来源位置范围为第二组；匹配数、页大小、基础/完整列集中在表格上方，上一页/下一页与准备/下载集中在表格下方。位置分析常驻说明横轴是每轮来源序号而非保底进度，比例分母是实际观察次数；完整列明确概率保持 0～1 数值尺度。未改变 TraceFilter 字段、query_records/iter_jsonl 参数、下载上限、50/100/200 页大小、缓存签名或非Trace早退。
3. 追加测试覆盖全部轮次、未配置角色、下载超上限及上述布局/说明。指定命令 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_trace_details tests.test_dashboard_app -q`：69项通过，退出0；`git diff --check` 通过。

自检：

- ✅ 已验证：按需查询、下载全匹配记录、分页边界、结果/筛选缓存失效、位置81抽以后及上限路径的既有测试保持通过。
- ✅ 已验证：仅使用 Streamlit 公共 columns/expander 控件，未改数据库、依赖、TraceFilter、查询或导出格式。
- ⚠️ 未验：真实浏览器视觉、窄屏和键盘焦点验收留任务10；本轮命令输出仍有既有 bare-mode `missing ScriptRunContext` 警告，但无测试失败。

未提交、未合并、未推送。

### 任务8修复轮1：轮次输入列归属与缺失断言

审查发现指定轮次／轮次范围的数字输入仍调用根 `st`，没有落在第一组轮次列，焦点顺序与布局契约不符。将 focused fake 改为可区分的列代理后先观察 RED：14项中指定轮次和轮次范围两个子用例失败，失败点均为输入未记录在列0。

最小修复将“指定轮次”“轮次起”“轮次止”改为 `primary[0].number_input`，保留原 key、范围和筛选值；补充默认第1轮、基础列不含概率字段、未Trace早退不进入明细查询的断言。指定命令 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_trace_details tests.test_dashboard_app -q`：73项通过，退出0。⚠️ 真实浏览器焦点/视觉验收仍留任务10；未提交、未合并、未推送。
## 任务9：历史统一选择与操作栏

目的：以一个多选框作为历史操作的唯一选择来源，集中查看、复用、删除和双记录比较，避免逐行长UUID按钮与过期删除目标。

涉及文件：

- `dashboard/views/history.py`
- `tests/test_history_navigation.py`
- `tests/test_dashboard_app.py`
- `.superpowers/sdd/2026-09-22-dashboard-usability-task-control-plan/task-9-report.md`

验证过程：

1. RED：子代理先加入0/1/2/>2条选择、短ID碰撞、选择变化清旧删除目标及统一操作按钮测试，随后因额度和沙箱中断。生产历史页未修改时，指定71项出现7个失败、4个错误，均来自旧逐行按钮、完整ID展示及缺少选择约束。
2. GREEN：表格改为短ID；一个multiselect保存完整UUID并显示短ID/时间/规模；0或2条时禁用单条操作，1条时集中查看/复用/删除，完整UUID可复制。筛选/翻页裁剪选择，选择变化取消旧确认；确认文字含完整ID和规模，删除复用共享状态/缓存清理函数。指定命令第一次恢复为71项通过。
3. 审查修复：两个运行可同时碰撞短ID、时间和规模。基础标签重复时追加完整UUID；测试直接调用multiselect的 `format_func`，确认标签不同且分别包含完整ID。专项1项及最终指定71项均通过，退出0；`git diff --check`通过。
4. 历史比较继续调用共享概览/分类统计，只读取汇总，不获取TraceReader；任务6并排图随 `_render_category` 自动复用。

边界：无效UTC日期范围在历史列表操作前返回，该次渲染没有删除按钮，但旧选择会保留到下次有效筛选；记录为非阻断Minor。真实浏览器视觉、窄屏和焦点验收留任务10。未提交、未合并、未推送。

## 任务10：联合验收与交付说明

✅ 已验证：临时库中以初始主抽29、每轮2主抽、3轮、seed 42运行真实同步worker。Trace共36条，概览固定两行：每轮主抽2／赠送10／总计12，全实验主抽6／赠送30／总计36；顶部轮数为3。非Trace汇总与Trace对照一致且没有明细入库。既有逐轮顺序和JSONL导出断言继续通过。

✅ 已验证：在真实worker的Trace校验入口用事件控制停止，确认取消异常在校验过程中发生、历史没有该运行、残次结果与Trace及取消标记已清，参数、取消状态和日志保留。已有worker测试覆盖保存后迟到的停止不会删除历史；新增删除后执行停止及重启协调的断言，确认历史不能被旧任务复活。测试使用同步worker线程，未覆盖独立子进程的实际信号时序。

✅ 已验证：新增集成用例后，`tests.test_trace_lifecycle tests.test_jobs -q` 共60项通过。全套回归先为451项通过；最终审查发现历史双记录比较的控件key会共用先前 `selected_result`。修复为每条历史传独立owner，相关历史测试13项通过，普通结果页key测试通过；最终 `$PY -m unittest discover -q` 为452项通过、退出0。故障注入用例中的异常日志为预期输出，不代表测试失败。`git diff --check`通过。

✅ 已核对：README、本地使用手册、页面详细说明和部署文档的未来验收条目已更新。说明实际页面入口、当前阶段100%的含义、停止不可续算、保存失败时完整结果仍可查看、并排柱数值精度，以及逐抽概率使用0～1。文档本地链接检查未发现失效目标。

⚠️ 原待验项已做部分本地检查，结果和未验边界见下文；不以此宣称全部浏览器验收通过。服务器现场部署和真实OIDC不在本次范围。

Git状态：功能提交 `9e33670`；本地合并至 `master` 的提交 `b085d33`；未推送、未部署，未删除真实数据。

### 2026-09-23 本地浏览器抽查与范围调整

✅ 使用本机 Firefox、临时目录 `/tmp/lottery-browser-55j79g` 与回环地址运行3轮、每轮2主抽、初始累计29、seed 42、Trace开启的网页实验。启动预览和完成结果均显示每轮12抽、全实验36抽、Trace 36条；历史页可筛选并打开该记录。宽屏1440像素与窄屏500像素下检查了新建、结果、历史导航和Trace基础明细布局，未见整页水平溢出。五类默认分类图均实际打开，零值标签可见；这不覆盖自定义长角色名或空奖励场景。

✅ 宽屏截图发现概览顶部理论期望长小数被省略号截断。新增显示回归先失败，随后复用 `format_comparison_value` 将顶部模拟均值和理论期望显示为4位小数，小非零值仍使用科学计数法；原始汇总与下载精度不变。修复后 Firefox 显示 `0.3333`、`0.0960`，无截断。最终 `$PY -m unittest discover -q`：453项通过，退出0；故障注入日志为预期输出。

⚠️ 用户明确要求跳过剩余浏览器检查，自己启动程序查看。因此未完成Tab焦点顺序、长角色名/空奖励、实际下载内容、历史复用/删除以及网页停止交互验收；计划相应复选框保留未勾选。停止本次网页和Firefox会话后，临时 geckodriver 进程PID 97807因本机权限拒绝未能关闭，用户需自行清理。此进程不属于应用服务。

### 2026-09-23 本地合并

✅ 功能分支提交 `9e33670` 已合并到本地 `master`，合并提交 `b085d33`；合并后的主工作树执行 `$PY -m unittest discover -q`，453项通过、退出0。未推送到远端，未执行服务器部署，未删除真实历史数据。

✅ 合并前主工作树已有未提交的README、`dashboard/app.py`和操作文档改动。它们的内容已被功能实现覆盖或扩展；原状态另存为stash提交 `aa5e5b2`（描述：`pre-merge dashboard-usability 2026-09-23`），保留供恢复核对，不重新应用以免回退新页面。剩余浏览器项目按用户要求由用户自行验收。
