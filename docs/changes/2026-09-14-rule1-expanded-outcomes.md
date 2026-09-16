# 规则 1 扩展结果：实现与本地验收记录

日期：2026-09-16
状态：✅ 本地自动化、部署路径和三项 CLI 验收完成；⚠️ 服务器现场部署验收未执行。
设计： [规则 1 多星级、角色池、五星保底与附赠奖励设计](2026-09-14-rule1-expanded-outcomes-design.md)

## 范围与数据库路径

规则 1 已升级为 `2.0`：四/五/六星结果、独立五星保底、配置化多 UP 与具体角色、按星级多奖励、主池/赠送临时池双保底、结构化汇总/Trace、精确期望、v2 历史快照和网页编辑均已进入本地代码。

默认开发历史库为 `data/history_v2.sqlite3`；Compose、网页 worker 与 systemd 每日备份统一使用 `/app/data/lottery_v2.sqlite3`。旧 `lottery.sqlite3`（包括 `data/history.sqlite3` 和卷中的 `/app/data/lottery.sqlite3`）不读取、不迁移、不覆盖、不删除。它们是并存旧数据，不是本次升级目标。

## 提交与任务证据

下表是同目录 `progress.md`、Task 1–9 报告中的已有证据摘要；它们是各任务当时的报告，不被重新表述为本次现场验证。

| 任务 | 提交 | RED → GREEN | 突变 → 恢复 |
| --- | --- | --- | --- |
| 1 配置模型 | `8acf756 feat: add configurable lottery pool` | `pool_config` 模块缺失而 RED；4 项目标测试 GREEN，随后 146 项全绿。 | 删除“UP 必须限定”校验后无效组合测试失败；恢复后通过。 |
| 2 双保底与单抽 | `fee9080 feat: add rarity outcomes and five star pity`; `29de97f fix: validate reachable rarity probabilities` | 缺 `RarityProbabilities`、`DrawOutcome`/`draw_once` 分别 RED；关联 33 项 GREEN。 | 五星保底分支强制为基础 8% 后边界测试失败；恢复后通过。 |
| 3 赠送临时池 | `f2fd0bd feat: run bonus draws in a temporary pool` | 缺 `five_star_hard_pity`/`for_bonus()` 的 13 个预期错误 RED；bonus+engine 27 项 GREEN。 | 用主池状态取代新的临时 `DrawState()` 后主池隔离测试失败；恢复后通过。 |
| 4 流式汇总/Trace | `b63d9cf feat: aggregate structured lottery outcomes`; `1669b5b fix: stabilize reward distribution buckets` | 缺来源汇总/结构字段 RED；engine 26 项、修复后 27 项 GREEN。 | 在非 Trace 路径强塞一条记录后内存边界测试失败；恢复为空记录。 |
| 5 双状态精确期望 | `3bd0f11 feat: analyze double pity expectations` | 缺 `PoolExpectations` 和理论摘要字段 RED；analysis+engine 47 项 GREEN。 | DP 五星分支不清零五星状态后，独立 `Fraction` 穷举 7 个子用例失败；恢复后通过。 |
| 6 CLI | `b7051f5 feat: expose configurable pools in cli`; `9a0e47b fix: localize cli configuration errors`; `57c1f80 fix: keep cli errors localized and generic`; `e3ec9f9 fix: distinguish cli pity and simulation errors` | 新参数、JSON 字段和中文输出缺失 RED；CLI 最终 24 项 GREEN。 | 理论 `rarity_counts` 改错字段名后 CLI 测试失败；恢复后通过。 |
| 7 v2 历史 | `b31d2ed feat: store rich results in v2 history`; `cfbf938 fix: inspect legacy history without writes`; `57b0fae fix: stabilize read-only history inspection`; `3a922f6 fix: recover rollback journals in private history snapshots`; `a1e6f35 fix: isolate history snapshot candidates` | v2 列/Trace/旧库拒绝先 7 FAIL、1 ERROR；目标套件 GREEN。后续 WAL、journal、私有快照 RED 均有对应恢复。 | 临时接受 schema v1 后，旧库拒绝测试未抛错；恢复只接受 v2 后通过。 |
| 8 网页配置/快照 | `9708c0d feat: edit pool configuration in dashboard`; `c90b683 fix: avoid cold config reads and empty editor columns`; `ea80fa9 fix: type empty reward editor columns` | 编辑、快照和历史复用先 RED；配置/仪表盘相关 114 项 GREEN，随后全量 217 项 GREEN。 | 删除空奖励表的 `TextColumn` 后真实 AppTest 失败；恢复后通过。 |
| 9 结果图表 | `f949f83 feat: visualize rarity roles and rewards`; `214fdc2 fix: complete result chart coverage` | 缺 chart helper/六区布局 RED；chart 与视图 GREEN，关联 47 项 GREEN。 | 将“总计”错误映射到主池后来源切换失败；恢复总计映射后通过。 |

## 已记录裁定（Ruling）

这些裁定保留原有适用范围和代价说明：

1. **Task 2 范围裁定**：仅改列出的五个文件。仓储尚未保存新增状态、仪表盘仍断言规则 `1.2` 的三个全量失败归 Task 7/8；代价是分支在下游完成前暂时不全绿。
2. **Task 5 测试替身裁定**：把调用次数敏感的 `OrderedRarityRule` 替换为真实 `Rule1` 加固定 RNG；代价是不得弱化固定星级顺序、奖励桶和字面量断言。
3. **Task 5 浮点裁定**：仅 `tests/test_simulation_view.py` 的理论浮点叶子使用 `assertAlmostEqual`，标签、形状、字段和模拟值仍精确断言；代价是容差过宽会掩盖映射错误，因此限于数值叶子且不在生产代码舍入或复制 DP。
4. **Task 8 编辑器裁定**：Streamlit AppTest 验证真实编辑器渲染和提交链路，增删行/无效行/JSON 的转换由纯 `editor_rows_to_config` 边界覆盖；代价是浏览器内动态表格交互仍需现场人工验收。
5. **Task 8 冷启动裁定**：允许修改 `rule_1.py`，将类体默认配置读取改为惰性实例加载，以保证 worker 只消费序列化快照；代价是必须保留未调用 `super().__init__()` 的旧子类兼容并有测试。
6. **Task 10 文字 Trace 裁定**：指定 CLI 验收稳定复现文字 Trace 缺少星级、角色、奖励和双状态，而 JSON record 完整；因此扩展 Task 10 到 `lottery_simulator/cli.py` 和 `tests/test_cli.py`，修复共享 formatter，不新增 DrawRecord/引擎字段、不改 JSON。代价是文字输出新增列可能影响外部文本解析器，故旧列保持原顺序并只追加新列。

## Task 10 本地证据

### 部署路径合同

- **RED**：先更新 `tests.test_deployment_files.DeploymentFilesTest.test_compose_and_backup_use_v2_database_path`，用项目内 YAML 映射、`configparser` 和 `shlex` 读取实际 Compose 环境变量与 systemd `ExecStart` 边界。旧 Compose 值 `/app/data/lottery.sqlite3` 与期望 `/app/data/lottery_v2.sqlite3` 不同，单测失败。
- **GREEN**：仅将 Compose 和备份服务改为 `/app/data/lottery_v2.sqlite3`，备份名改为 `lottery-v2-$(date +%%F).sqlite3`；同一测试 1/1 通过。
- **突变/恢复**：把 Compose 路径临时改回旧值，合同再次失败；恢复 v2 路径后同一测试再次通过。该证据能排除“测试只会通过”的风险，不能验证 Docker 实际加载、卷权限或 systemd 已安装。

### 自动化与文档

- `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest discover -v`：初次路径/文档验证为 227 项通过；文字 Trace 修复后的新鲜最终结果为 ✅ `Ran 228 tests in 89.376s`，`OK`。
- 完整回归首跑曾因本任务测试辅助函数把 services 映射又索引一次而报 `KeyError: 'services'`；根因已定位为无关重构的返回层级不匹配，撤销该重构后 `tests.test_deployment_files` 9/9 通过，再进行上述完整 GREEN。该错误未触及产品部署路径。
- **文字 Trace RED/GREEN**：先以真实 `simulate --draws 30 --trials 1 --seed 42 --trace` 输出的 4/5/6 星、主池/赠送、角色、奖励、概率、状态和触发标记字面量写测试；旧 formatter 缺扩展表头而 RED。最小修复只消费已有 record 字段并追加列，目标测试 GREEN，完整 CLI 25 项和部署 9 项均通过。
- **文字 Trace 突变/恢复**：临时把六星角色显示为 `—`，目标测试只在第 20 抽六星字面量失败；恢复角色字段后通过。该实验验证文字层不会静默丢失具体角色，不能替代引擎/JSON 字段本身的测试。
- 设计文档仅在 Trace 修复后的完整测试和三项验收通过后更新为“已实现”。

## 本地功能验收与守恒检查

本次按下列命令执行；结果和限制在命令后记录：

```bash
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator analyze --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1000 --seed 42 --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1 --seed 42 --trace
```

实际结果：

- `analyze`：✅ `rule_version=2.0`，默认 9 名角色、2 种奖励，`probability_table` 为 80 行。
- 1000 轮 JSON 模拟：✅ `main/bonus/total=30/10/40`；每个来源的星级均值之和等于 draws，具体角色均值之和等于六星均值，按默认奖励规则由星级均值重算的奖励与输出一致。
- 文字 Trace：✅ 共 40 条，主池 30 条后紧接 10 条赠送，10 条赠送的 `main_draws_completed` 都是 30，主池状态保持不变。表头与记录均包含星级、角色、按星级奖励、4/5/6 星概率、主池抽后双保底、来源池抽前/后双保底、五星保底触发和六星硬保底触发；第 20 抽为六星 `常驻-F`，第 31/40 抽分别显示赠送四/五星及独立来源池状态。

这些命令用于检查规则 `2.0`、默认 9 角色/2 奖励配置、每轮 30 主抽加 10 赠送、星级/角色/奖励守恒和 Trace 的赠送状态隔离。它们不能替代概率正确性的穷举测试，也不验证网页、部署或真实服务器。

## 已知盲区与未执行现场验收

- ⚠️ 未执行 Docker build、`docker compose config` 官方解析/运行、Caddy、systemd 安装、卷权限、备份定时器、真实卷停机恢复、DNS、自动证书、真实 HTTPS/HSTS 或 OIDC。文档中的服务器命令是未来现场步骤，不是本次成功记录。
- ⚠️ 本地 SQLite 备份测试证明隔离临时库的 backup/restore 行为；不证明容器卷路径上的恢复流程。
- ⚠️ AppTest 不提供 data editor 动态增删行的公开浏览器 API；转换和提交流程已自动化，真实浏览器新增/删除行仍待人工验收。
- ⚠️ Task 2 仍有公共 `advance_rarity()` 对无效 rarity/不可能强制保底 miss 转换缺少硬化的 Minor；内部抽取路径不会产生这些输入。
- ⚠️ Task 4 非 Trace 测试证明结果不保留记录，不能独立证明内部从未临时构造 `DrawRecord`。
- ⚠️ Task 8 的界面联合五/六星概率校验错误详情仍是英文，阻断行为已验证。
- ⚠️ Task 9 Trace 回归测试尚未显式命名 `probabilities` 和 `source` 字段；生产数据透传已覆盖，最终审查应评估是否补强。

## 结论

✅ 已验证：本地自动化、配置/CLI/网页测试与部署静态合同通过，且 v2 路径与新文档一致。
⚠️ 推断边界：上述结论不扩展为 Docker/Caddy/OIDC/公网或真实服务器部署已经成功；这些需要按部署手册逐项现场观察后补记。
