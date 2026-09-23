# 网页使用体验与任务控制改进实施计划

> 执行者：使用 `superpowers:executing-plans` 按任务推进；如用户要求子代理分工，再使用 `superpowers:subagent-driven-development`。复选框仅在实际验收后勾选。本文件不授权立即实施或Git提交。

**目标：**精简概览、准确报告阶段并安全取消任务，整理三页面布局，使模拟与理论柱状图并排且数值可读。

**架构：**保留现有核心、worker、任务锁、SQLite事务及按需查询。以可选回调补充阶段和取消检查，页面复用原快照、筛选及图表投影，不引入恢复系统。

**技术：**Python、unittest、SQLite、Streamlit及其已安装图表能力；不新增无关依赖。

**设计：**[网页使用体验与任务控制改进设计](2026-09-22-dashboard-usability-task-control-design.md)。执行前完整阅读设计与本计划。

**状态：**已本地合并；任务10的真实浏览器检查仅部分完成，剩余项目由用户自行启动程序查看。任务5独立子代理审查受额度限制中断，已由主代理核对关键路径；未验边界见实施记录。

## 全局约束

- 项目主目录 `/home/qykj/202607/test/lottery_simulator`；解释器 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python`。下文 `$PY` 指该解释器，可先设置 `PY=/home/qykj/202607/test/lottery_simulator/.venv/bin/python`。
- 实施时先检查项目适用指令、分支及未提交修改，再建立隔离工作区；保留现有操作文档及新设计/计划。不能把当前脏工作区直接重置或覆盖。
- 不改变规则、抽样顺序、结果统计、v4数据库格式或既有历史；不清空数据。Trace上限、导出上限、分页和位置查询上限保持不变。
- 不新增模板、批量删除、续算、取消恢复、保存重试、置信区间或服务器部署。
- 保留旧API默认行为；新参数放在现有参数末尾且为可选关键字参数。抽样、结果、Trace及数据库版本保持不变；新增任务状态字段可缺省，旧完成任务仍可读。
- 每任务执行：补针对性失败测试 → 确认失败原因 → 最小实现 → 相关测试通过 → 更新实施记录。修复任务做安全的临时撤回对照，不能覆盖用户修改。
- 不进行SHA验证，不为布局搭建性能框架；只做功能检查和必要浏览器验收。任务结束不自动提交、合并或推送。
- 开始实施时创建同主题实施记录 `2026-09-22-dashboard-usability-task-control.md` 并将台账改为实施中；本轮不创建空实施记录。

## 文件与接口地图

| 文件 | 职责 |
|---|---|
| `dashboard/views/simulation.py`、`dashboard/app.py` | 概览、结果导航、快照和操作 |
| `lottery_simulator/control.py`（新增） | 共享取消异常、回调类型及取消检查，避免analysis与engine循环导入 |
| `lottery_simulator/analysis.py`、`engine.py` | 计算阶段通知和取消检查 |
| `dashboard/models.py`、`worker.py`、`jobs.py`、`views/job_status.py` | 阶段持久化、取消/提交协调和状态展示 |
| `dashboard/trace_store.py`、`repository.py` | 校验/导入进度及取消点 |
| `dashboard/charts.py` | 保留投影，增加共用带标签分组柱图构造函数 |
| `dashboard/views/new_experiment.py`、`configuration.py` | 参数、配置、启动摘要布局 |
| `dashboard/views/trace_details.py`、`history.py` | 筛选和历史操作布局 |
| 对应 `tests/test_*.py`、操作文档 | 回归及交付说明 |

任务按1→10执行；任务2定义任务3～5依赖的回调和状态约定，任务6的图表由结果页与历史比较共用。不要同时修改相互依赖的任务。

## 任务1：概览两行汇总与醒目轮数

**文件：**`dashboard/views/simulation.py`、`dashboard/app.py`；测试 `tests/test_simulation_view.py`、`tests/test_dashboard_app.py`。

**接口：**保持 `_render_overview(st, payload)`、`render_result(...)`；抽数取 `draws`、`bonus_draws`、`trials`，不能取新建草稿。

- [x] 在现有RecordingStreamlit测试中加入大轮数概览用例，不实际运行十万轮：

```python
ui = RecordingStreamlit()
_render_overview(ui, {"draws": 100, "bonus_draws": 10,
                     "total_draws": 110, "trials": 100_000})
assert len(ui.dataframes[0]) == 2
assert ui.dataframes[0][1]["总抽数"] == 11_000_000
```

- [x] 运行 `$PY -m unittest tests.test_simulation_view tests.test_dashboard_app -q`，确认旧逐轮表无法满足两行断言。
- [x] 用下述数据替换逐轮循环；核心三个指标提前，顶部规模摘要显示轮数，累计历史不计入新增抽数：

```python
rows = [
    {"范围": "每轮", "主池抽数": draws, "赠送抽数": bonus, "总抽数": draws + bonus},
    {"范围": f"全实验（{trials:,}轮）", "主池抽数": draws * trials,
     "赠送抽数": bonus * trials, "总抽数": (draws + bonus) * trials},
]
```

- [x] 添加初始29、1主抽、10赠送、3轮用例，断言总计33，不含假设历史；当前草稿改变不影响历史结果摘要。
- [x] 重跑上述两组；暂时撤回两行生成逻辑可重新触发失败后恢复。更新实施记录。

## 任务2：最小共享控制接口和兼容任务状态

**文件：**新增 `lottery_simulator/control.py`；修改 `engine.py`、`dashboard/models.py`；测试 `tests/test_engine.py`、`tests/test_dashboard_models.py`。

**提供的接口：**

```python
from collections.abc import Callable

CancelCheck = Callable[[], bool]
PhaseCallback = Callable[[str, int | None, int | None], None]
ProgressCallback = Callable[[int, int], None]

class SimulationCancelled(RuntimeError):
    pass

def check_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise SimulationCancelled("simulation cancelled")
```

`engine.py`导入同一异常，使原 `from lottery_simulator.engine import SimulationCancelled` 仍可用；analysis不得反向导入engine。查找所有调用者，避免两种异常类并存。

`JobState`保留原 `completed_units/total_units` 主抽含义，新增默认值：`phase_completed: int | None = None`、`phase_total: int | None = None`、`cancel_requested: bool = False`、`cleanup_error: str | None = None`。扩展phase允许 `theory`、`validating`、`committing`，保留 `simulating/saving/None`。

- [x] 先测旧状态缺少新增字段可读、新字段往返；拒绝bool计数、负数、完成数大于总数、只提供一个计数、非bool取消标记、非字符串清理错误。
- [x] 执行 `$PY -m unittest tests.test_dashboard_models tests.test_engine -q` 确认新增状态测试失败。
- [x] 实现上述接口和校验；两个阶段计数要么均为空，要么均为非负整数且完成数不大于总数，UI对总数0不用除法。结束任务清空phase和阶段计数。
- [x] 测试断言旧导入的异常与新异常是同一个对象；重跑两组通过。任务版本保持当前值，新旧worker不混跑。

## 任务3：理论计算与赠送循环可取消

**文件：**`lottery_simulator/analysis.py`、`engine.py`；测试 `tests/test_analysis.py`、`test_engine.py`、`test_cli.py`。

**接口增量：**`expected_pool_results`、`expected_simulation_results`增加关键字参数 `cancel_check=None`；`simulate`增加末尾关键字参数 `phase_callback=None`。原 `progress_callback(completed,total)` 仍只表示主抽进度。

- [x] 加入确定性理论取消测试，不依赖睡眠：

```python
from lottery_simulator.control import SimulationCancelled
with self.assertRaises(SimulationCancelled):
    expected_pool_results(Rule1(), 100, cancel_check=lambda: True)
```

- [x] 在simulate的阶段回调收到 `theory` 后置取消标志，断言模拟抛取消而不是返回结果；单独测试赠送期间取消。
- [x] 执行 `$PY -m unittest tests.test_analysis tests.test_engine -q` 确认失败。
- [x] simulate开始及理论入口分别调用 `phase_callback("simulating", None, None)`、`phase_callback("theory", None, None)`；理论先只报告名称，避免人为推算总工作量。
- [x] 理论每个抽次递推及赠送事件扫描检查取消；大的内部状态循环每1000个状态再检查；赠送抽循环逐抽检查。理论入口和返回前检查，子调用透传同一cancel_check。不重排任何浮点累加或随机调用。
- [x] 用相同seed对照无回调/带回调、非Trace/内存Trace/sink统计及记录，排除仅耗时等非确定字段；所有结果保持一致。
- [x] 重跑 `$PY -m unittest tests.test_analysis tests.test_engine tests.test_cli -q`，记录结果。

## 任务4：明细校验和历史导入报告进度

**文件：**`dashboard/trace_store.py`、`repository.py`；测试 `tests/test_trace_store.py`、`test_repository.py`。

**接口增量：**`TraceWriter.finish(..., cancel_check=None, progress_callback=None)`；`HistoryRepository.save_run(..., progress_callback=None)`。此处回调均为任务2的 `(completed:int,total:int)` 类型，阶段名由worker指定。

- [x] 在现有临时库测试中注入取消：finish入口、批次中、完成metadata前；导入批次中、最终提交前。断言取消传播、metadata没有complete=1、历史汇总和明细均未部分入库。
- [x] 测入口 `(0,total)`、中间批次、最终 `(total,total)`，总数包括赠送；使用小批量测试，不创建百万记录。
- [x] 运行 `$PY -m unittest tests.test_trace_store tests.test_repository -q` 确认新增测试失败。
- [x] 校验循环按现有batch_size检查并通知；开始flush前后及complete标记前也检查。完成通知在校验成功后发送。导入沿用现有批次和事务，每批通知，不改变SQL原子性。
- [x] 复用共享取消异常。取消和回调异常均让事务回滚；关闭连接由原生命周期负责。进度100%仅代表扫描/导入计数，不代表历史已提交。
- [x] 验证save_run幂等旧路径、参数验证、JSON投影检查仍有效，重跑两组通过。

## 任务5：worker阶段接线、安全停止及清理

**文件：**`dashboard/worker.py`、`jobs.py`、`views/job_status.py`，必要时 `models.py`；测试 `tests/test_jobs.py`、`test_trace_lifecycle.py`、`test_dashboard_app.py`。

**消费：**任务2状态字段、任务3/4回调。worker内使用 `publish_phase(phase, completed=None, total=None)`；阶段边界立即写，阶段内通知按单调时钟最多每0.5秒写一次，末次立即写。主抽旧计数保持独立。

- [x] 先增加worker集成断言：有Trace收到simulating→theory→validating→saving→committing；非Trace没有validating。各回调在实际进入对应代码时触发，不提前声明完成。
- [x] 增加取消/提交故障用例：理论取消、校验取消、保存中取消、提交后迟到取消、提交成功但状态写失败、读库失败无法确认、worker未退出、文件删除PermissionError。
- [x] 运行 `$PY -m unittest tests.test_jobs tests.test_trace_lifecycle tests.test_dashboard_app -q`，确认新行为未实现时失败。
- [x] 将simulate.phase_callback接publish_phase；理论返回后finish回调绑定validating；save_run回调绑定saving。现有commit_guard内最终检查取消后发布committing，再提交和发布终态。不能在持有任务锁时调用会再次获取同一锁的回调；锁内用当前状态直接write_json。
- [x] cancel在现有锁内标记cancel.request及cancel_requested。读历史失败不得当作“确定未提交”去删数据；最终清理由worker或确认退出后的manager执行。
- [x] 状态UI优先显示取消请求并禁用重复停止按钮；phase_total未知时只显示阶段文字，不沿用已100%的主抽进度冒充该阶段。保留耗时和主抽数说明。
- [x] 统一调用现有 `_clean_stopped_files(job_dir, partial_result=True)`，关闭writer/连接、回滚后才清理result/Trace及其伴随文件。保留state、parameters和日志；不glob删除未知临时文件。对确认拥有的临时输出，复用原写入函数finally清理。
- [x] 取消标记最后删除；若清理失败，保留标记并写cleanup_error，终态可为cancelled但UI必须显示“计算已停止，残次文件清理未完成”，不能声称全部清理完成。reaper/重启能识别已停止的取消任务并完成清理，不将取消误记为一般失败。
- [x] 已提交历史继续发布/校正completed，不删除完整结果；提交状态未知保留active与文件，不放行冲突任务。保存失败但计算完整沿用既有保护，不增加重试入口。
- [x] 重跑三组，使用临时目录确认其他任务、配置、日志和数据库旁文件不受影响；安全临时撤回关键取消检查使对应测试再次失败，恢复后通过。

## 任务6：五类统计统一带数值并排柱

**文件：**`dashboard/charts.py`、`views/simulation.py`；测试 `tests/test_charts.py`、`test_simulation_view.py`。

**接口：**新增 `comparison_bar_chart(rows, *, category_field, unit, horizontal=False)` 返回图表对象；`format_comparison_value(value: float) -> str` 生成标签。不修改原rarity_rows等投影数据或统计值。

- [x] 先确认虚拟环境已安装的图表能力：`$PY -c 'import altair; print(altair.__version__)'`；如不可用，停止选型并报告，不擅自新增依赖。本计划优先使用现有Altair，API以安装版本为准。
- [x] 添加格式化和图表规格测试：

```python
assert format_comparison_value(0) == "0"
assert format_comparison_value(1.25) == "1.2500"
assert "e" in format_comparison_value(0.000001)
```

- [x] 运行 `$PY -m unittest tests.test_charts tests.test_simulation_view -q` 确认失败。
- [x] 将每类别转换成两条长表记录，字段为 `类别/系列/值/标签`，系列固定模拟均值、理论期望。Altair使用xOffset（横向yOffset）分组、明确 `stack=None`，bar层与text层复用相同偏移和顺序；显式设置颜色域和图例顺序。
- [x] 标签使用4位小数，小非零值用科学计数法；tooltip及数值表显示12位有效数字。绘图区保留标签空间；多角色（超过8个）或名称超过8字符采用横向，按角色数增加高度，不截掉角色。零/相同值每根柱有自己的标签。
- [x] `_render_category`五个分支调用同一个构造函数；图表下仍显示原数据表，无奖励显示空状态；历史比较自动复用。
- [x] 检查生成图表规格包含分组偏移、text层、确定系列顺序、单位及完整类别；组件假对象增加altair_chart记录接口。重跑两组；实际文字拥挤留任务10浏览器验收。

## 任务7：新建实验与结果页布局

**文件：**`views/new_experiment.py`、`configuration.py`、`simulation.py`、`app.py`；测试 `test_dashboard_app.py`、`test_configuration_view.py`、`test_simulation_view.py`。

**接口：**沿用DRAFT_KEY、_widget_key、配置编辑器基线及result_owner；不能用展示标题替代稳定组件key。

- [x] AppTest新增参数草稿跨页、连续编辑、复用回新建、无效配置禁止启动、结果快照不随草稿变化的断言；更新新Trace标签断言。
- [x] 运行 `$PY -m unittest tests.test_dashboard_app tests.test_configuration_view tests.test_simulation_view -q` 记录基线及新增失败。
- [x] 主抽/轮数并排，长初始保底名称独占行；参数与运行摘要桌面两列，下方配置/高级/规则预览全宽；Trace标签改为“保存逐抽明细（Trace）”，内部字段不变。
- [x] 运行摘要必须使用本轮渲染得到的有效配置。可先创建布局容器、渲染配置再回填摘要及开始按钮，不能为挪按钮而用上一轮session快照启动。错误同步到启动区域。
- [x] 结果页使用 `st.radio("结果视图", ..., horizontal=True, key=原key)` 或已安装版本等价单选控件，保留if/elif惰性渲染；顶端集中复用与下载，避免出现两个同key下载按钮。
- [x] 顶部结果身份、规模与保存状态保持清楚，详细快照折叠；横向布局窄屏可堆叠/换行，不编写依赖私有DOM的CSS。
- [x] 重跑三组；断言概览/分类不调用TraceReader，切换页面不启动新任务；必要时更新RecordingStreamlit对新控件的记录支持。

## 任务8：Trace筛选、分页和下载布局

**文件：**`dashboard/views/trace_details.py`；测试 `tests/test_trace_details.py`、`test_dashboard_app.py`。

**接口：**保持TraceFilter、reader查询、result_owner、下载signature与原筛选参数；仅组织容器和说明。

- [x] 测试默认第1轮、指定轮/范围/全部、无名单角色、匹配数超过下载上限、切换结果清缓存、基础/完整列及第81位置不回归。
- [x] 运行 `$PY -m unittest tests.test_trace_details tests.test_dashboard_app -q`。
- [x] 将轮次/来源/星级分组，角色及位置限制次级展示；表格上方集中匹配数/页大小/列模式，下方集中翻页/下载。保留先准备后下载；分页选择不改变下载匹配范围。
- [x] 按抽次分析显示来源、横轴定义和比例分母常驻文案，不与明细筛选联动；未Trace不查询。概率完整列继续使用0～1数值并明确说明，本轮不引入额外格式切换。
- [x] 更新控件布局测试并重跑两组；验证缩小筛选后页码合法、下载缓存失效、源位置上限和页大小未变化。

## 任务9：历史统一选择与操作栏

**文件：**`dashboard/views/history.py`；测试 `tests/test_history_navigation.py`、`test_dashboard_app.py`。

**接口：**继续使用 `selected_history_ids` 存完整UUID、`pending_reuse_id/pending_delete_id`、`selected_result=("history", id)`；共享删除缓存清理函数不复制。

- [x] 先测零选项无单条操作、一条可查看/复用/删除、两条仅比较、超过两条拒绝；翻页和筛选清除不在当前页的选项；短ID相同的两条记录仍精确区分。
- [x] 运行 `$PY -m unittest tests.test_history_navigation tests.test_dashboard_app -q` 确认新增操作行为失败。
- [x] 使用一个multiselect作为唯一选择源，删除逐条查看按钮。集中“查看结果”“复用参数”“删除历史”，零条/两条时禁用单条操作并提示；两条复用现有汇总比较。
- [x] 短ID只用于展示，选择标签结合时间/规模，完整UUID仍可复制；内部查询删除全用完整值。删除二次确认显示ID和规模，选择/筛选改变时取消旧待删除目标，避免删除上次选择。
- [x] 删除后清选择、结果引用、下载缓存；旧job不能复活该历史。保持每页20条、UTC筛选，不增加批量删除或数据库表。
- [x] 重跑两组并核对并排比较使用任务6新图表，无全量Trace查询。

## 任务10：联合验收、文档和台账

2026-09-23 用户明确要求跳过剩余浏览器检查并本地合并；未完成的视觉、键盘及交互验收保持未勾选，不视为已通过。

**文件：**现有相关tests，必要时扩展 `tests/test_trace_lifecycle.py`；`README.md`、`docs/local-usage.md`、`docs/dashboard-guide.md`，部署文档仅更新相关未来验收文案；本计划、台账及同主题实施记录。

- [x] 用临时库运行3轮×2主抽、初始29、seed42、Trace开启：共36条记录。检查每轮2主抽+10赠送，总主抽6、总赠送30、总实际36；轮数顶部为3。另跑非Trace对照，汇总一致（排除Trace元数据/耗时）。
- [x] 将任务5的可控取消点覆盖到真实worker集成，使用事件/回调控制而非固定sleep赌时序；断言历史不存在、残次文件已清、日志参数状态仍在。另测保存成功后停止不删历史、删除历史后不能复活。
- [x] 运行相关回归后运行一次 `$PY -m unittest discover -q`；失败则修复并重跑相关测试，最终再跑全套。记录实际数量、结果与未验边界，不照抄旧385项。
- [ ] 在独立临时数据目录、本地回环地址启动网页，真实浏览器检查宽/窄窗口、完整中文标签、Tab焦点顺序、三页切换、图表标签及五类空/零/长名称案例、逐抽下载内容、历史复用删除和停止状态。只停止本次创建的服务，不触碰用户正在运行的实例。
- [x] 浏览器验收未全部完成时写明已验和未验范围，不声称剩余项目合格；用户明确跳过后仍记录待其自行查看。
- [x] 更新操作文档为实际新入口，说明阶段100%含义、取消不可恢复、保存失败仍保留完整结果、并排柱标签精度与明细概率尺度。
- [x] 实施记录填写各任务证据、未验项和Git状态；按用户确认的交付范围更新台账，并记录本地合并提交。执行 `git diff --check` 和本地文档链接检查。用户已另行授权本地提交与合并；不推送、不删除真实数据。

## 设计覆盖与交付检查

| 设计范围 | 对应任务 |
|---|---|
| 醒目轮数、概览两行 | 1、7 |
| 阶段状态与旧任务可读 | 2、5 |
| 核心/理论/赠送取消 | 3 |
| 校验/保存进度与事务 | 4、5 |
| 安全删除、取消提交竞争、异常退出 | 5、10 |
| 五类并排数值柱、角色长名称 | 6、10 |
| 三页布局、草稿、惰性查询 | 7、8、9 |
| Trace边界及历史UI管理 | 8、9 |
| 功能验收、浏览器、操作文档和统一记录 | 10 |

本计划拆分已确认设计。用户已授权实施任务1～5；任务6～10仍待后续指令，复选框按实际任务验收更新。
