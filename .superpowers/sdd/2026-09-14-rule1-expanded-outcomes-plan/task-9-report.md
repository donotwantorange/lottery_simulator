# Task 9 报告：新结果图表与 Trace 展示

## 状态

✅ 已验证完成。

## 实现内容

- 新增星级、六星类别、具体角色、动态奖励、奖励分布和保底触发的纯数据行转换 helper。
- 角色与奖励顺序由 payload 中的 `pool_config` 驱动；角色表包含六星内实际/理论占比，零六星时实际占比为 `None`。
- 奖励分布把 JSON 数字键转为数值并按数值排序。
- `render_result()` 改为 `总览 / 六星构成 / 具体角色 / 附赠奖励 / 保底统计 / Trace` 六区布局，提供 `主池 / 赠送 / 总计` 来源切换且默认总计。
- Trace 直接展示 Tasks 1–8 提供的结构化记录；非 Trace 时不把 `records` 传给 dataframe。
- 保留 15 个原有总览指标、主池概率曲线、历史快照提示和 UTF-8 JSON 下载。
- 历史页同时展示多个结果时，来源和奖励控件使用运行 ID 隔离 key。

## 变更文件

- `dashboard/charts.py`
- `dashboard/views/simulation.py`
- `tests/test_charts.py`
- `tests/test_simulation_view.py`
- `tests/test_dashboard_app.py`
- `.superpowers/sdd/2026-09-14-rule1-expanded-outcomes-plan/task-9-report.md`

## RED / GREEN 证据

### 1. 图表纯数据映射

RED 命令：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_charts -v
```

关键失败：

```text
ImportError: cannot import name 'character_rows' from 'dashboard.charts'
FAILED (errors=1)
```

失败原因：测试先导入并调用任务要求的新 helper，生产模块尚未实现这些接口。

GREEN 命令：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_charts -v
```

结果：`Ran 10 tests ... OK`。覆盖星级、类别、9 名角色及占比、动态奖励配置顺序、奖励分布数值排序和五星/六星保底映射；期望均由测试字面量独立推导。

### 2. 六区结果渲染与来源切换

RED 命令：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_simulation_view SimulationResultViewTest -v
```

关键预期失败：

```text
('汇总', '主池与赠送拆分') !=
('总览', '六星构成', '具体角色', '附赠奖励', '保底统计', 'Trace')
StopIteration: 未找到“星级”结果表
```

同轮命令末尾额外的裸模块名 `SimulationResultViewTest` 产生一个无关 `ModuleNotFoundError`；随后用正确模块路径执行 GREEN。

真实 Streamlit RED 命令：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_dashboard_app.ResultRenderingRegressionTest.test_real_renderer_exposes_six_result_regions_and_source_switch -v
```

关键失败：实际标签页仍为 `['汇总', '主池与赠送拆分']`，未出现六区布局。

GREEN 命令：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_simulation_view -v
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_dashboard_app.ResultRenderingRegressionTest -v
```

结果：分别 `Ran 3 tests ... OK` 和 `Ran 3 tests ... OK`。覆盖六区标题、三来源切换、9 行角色、奖励 A/B、奖励分布、保底指标、Trace 新字段、非 Trace records 隔离与 UTF-8 下载；真实 Streamlit 无异常和弃用参数警告。

## 最终测试

简报指定关联套件：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_charts tests.test_simulation_view tests.test_dashboard_app -v
```

结果：最终复跑 `Ran 47 tests in 8.764s — OK`。只有允许的 Streamlit 裸模式 `missing ScriptRunContext` 提示，无弃用参数警告。

全量回归：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest discover
```

结果：`Ran 226 tests in 87.416s — OK`。

## 突变 / 恢复证据

临时把 `dashboard/views/simulation.py` 的来源映射从 `"总计": "total"` 改为 `"总计": "main"`，运行：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_simulation_view.SimulationResultViewTest.test_renderer_switches_all_summary_tables_between_sources -v
```

结果：✅ 按预期失败；`source='总计'` 子用例实际得到 `[2.0, 0.0, 0.0]`，期望 `[9.0, 3.0, 0.0]`。

恢复 `"总计": "total"` 后运行同一命令，结果：`Ran 1 test ... OK`。突变未提交。

## 自审

- ✅ 已验证：生产代码只消费既有 payload、`PoolConfig` 与分析接口，没有复制验证、模拟或理论计算逻辑。
- ✅ 已验证：动态角色和奖励遍历配置顺序；测试故意让奖励汇总字典顺序与配置相反，能捕获错误遍历源。
- ✅ 已验证：真实 dashboard payload 使用的 `mean_*` 理论字段和简报示例的短字段都能被纯转换 helper 消费，不改变 payload。
- ✅ 已验证：`records` 仅在 Trace 开启且记录非空时传给 dataframe；非 Trace 覆盖测试通过。
- ✅ 已验证：历史页两个快照的控件 key 按运行 ID 隔离，关联历史工作流测试通过。
- ✅ 已验证：`git diff --check` 无空白错误；未添加依赖、未修改范围外生产文件、未实现 Task 10、未推送。
- ⚠️ 作用边界：六区标签页仍遵循 Streamlit 的全脚本执行模型，切换标签不减少后端行转换；本任务数据量小且没有引入额外模拟计算。

## Commit

- `feat: visualize rarity roles and rewards`

## Concerns

无阻塞问题。
