# 多轮 Trace 与界面重组实施记录

验收日期：2026-09-21。关联：[设计](2026-09-18-multi-trial-trace-ui-design.md)、[计划](2026-09-20-multi-trial-trace-ui-plan.md)。

## 状态与实际功能

✅已验证：最终修复后的全套385项通过（104.670秒、退出0）；独立Luna复审已关闭I1～I7及M1～M2，结论为Approved、无阻断项。初次371项和修复阶段149项记录作为历史证据保留，详见[最终修复报告](../../.superpowers/sdd/2026-09-20-multi-trial-trace-ui-plan/final-fixes-report.md)。工作树为 `/home/qykj/202607/test/lottery_simulator/.worktrees/multi-trial-trace-ui`，未提交、合并或推送；主工作区数据未写入、未删除，真实服务未停止，未清真实 session，未启动真实 v4 生产实验。既有用户文档改动保留。

- ✅ 多轮 Trace 保存 `trial_index`、轮内 `draw_index` 和来源 `source_index`；每轮保底与赠送状态独立，同一次模拟只初始化一次随机数生成器。
- ✅ 网页 worker 通过 sink 分批写暂存库，完成校验后单事务导入 v4 历史；保存成功清暂存，保存失败保留完整暂存供当前结果读取，删除历史后不会从任务结果复活。
- ✅ 三页面为新建实验、实验结果、历史记录；结果分为概览、分类统计、按抽次分析、逐抽明细。草稿保持、复用、汇总对比、分页筛选及删除缓存联动已接入。
- ✅ 主池/赠送位置按各自 `source_index` 聚合观察轮数及四五六星频率，可显示第81抽；网页明细按需查询，JSONL下载覆盖全部匹配记录。
- ✅ Trace默认关闭；网页实际记录默认上限1,000,000，单次下载10,000，均包括赠送。CLI保留小规模内存Trace，并提供已保存历史的本地 `export-trace`。
- ✅ 本地默认 `data/history_v4.sqlite3`、`data/jobs_v4`，容器默认 `/app/data/lottery_v4.sqlite3`；部署与备份静态合同已同步。版本为规则2.0、配置/抽样1、记录/结果/任务2、数据库4、暂存/导出1。

## 最终审查修复与证据更正

✅本次先将审查复现转为失败测试，再修复reaper按job_id恢复、确认worker退出后清理、稳定(kind,id)下载归属、即时分页、任意合法位置起点/最多1000宽度、单轮/轮次范围及只读源库导出。补齐保存阶段说明、历史Trace记录数和结果快照/复用入口。无法确认退出或读取历史提交状态时保留active与文件，不放行冲突任务。

✅10项因果检查在临时撤回关键修复后全部重现失败（3.635秒、退出1），原样恢复修复后执行jobs、dashboard_app、trace_details、simulation_view、history_navigation、trace_export、repository、trace_lifecycle、trace_queries九组：149项、21.143秒、退出0。实际命令、逐项断言和边界见最终修复报告。

✅最新最终全套命令为 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest discover -q`，在上述隔离工作树运行：`Ran 385 tests in 104.670s`、`OK`、退出0。独立Luna复审确认I1～I7/M1～M2全部关闭，Approved、不阻断交付；审批与测试均不替代下面列出的浏览器、部署、容量和实际切换验收。

⚠️更正此前恢复覆盖表述：原restart案例绕过reaper，原47项jobs/models/lifecycle通过不能证明等待退出、清半成品或所有commit/state发布故障窗口。新增测试才覆盖reaper先于restart的已提交36记录窗口、退出确认顺序、拒绝信号/不可读proc保留活动、伴随文件清理。仍不声称穷尽现场进程调度与文件系统故障。

⚠️原371项测试日志 `/tmp/lottery-task12-IqxNEG/unittest.log` 在本次环境已不存在，无法重新核验该原始日志；下列371项及CLI/健康检查保留为初次任务12执行记录，不作为本次修改或新增契约的证明。

## 初次任务12修改与验证记录

✅ 初次任务12仅增强 `tests/test_trace_lifecycle.py` 的既有端到端验收，并更新记录、计划、设计状态与台账；当时没有生产代码修复。先跑生命周期4项（0.261秒，退出0），再跑一次全套。后续最终审查修复及新验证以上节为准。

```sh
cd /home/qykj/202607/test/lottery_simulator/.worktrees/multi-trial-trace-ui
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest discover -v
```

✅ 原执行记录：`Ran 371 tests in 96.462s`、`OK`、退出码0；外层命令墙钟97.00秒。包含 `tests.test_dashboard_app` 43项；原日志路径为 `/tmp/lottery-task12-IqxNEG/unittest.log`，现已不存在。故障注入用例中的预期异常日志和 Streamlit bare-mode提示不代表测试失败。该耗时仅为此次测试执行记录，不是容量或性能承诺。

| 验证范围 | 实际证据与边界 |
|---|---|
| ✅ 临时完整链路 | 非空四五星名单、主抽2/轮数3/初始29/种子42；真实worker保存前观察到暂存complete=1和36记录，再调用真实历史导入。历史与任务汇总逐字段一致；三轮各12条、主1+赠10+主1，分页及姓名/星级筛选符合记录；主/赠每个位置的四五六计数和频率均与逐条结果核对。 |
| ✅ 导出与删除 | JSONL为1条metadata+36条record，记录顺序/完整对象及汇总与历史一致。删除临时历史后repository、manager结果、manager reader均失效，已持有reader再次查询也拒绝。 |
| ✅ 非Trace对照 | 相同参数关闭Trace后汇总相等（排除耗时、Trace开关、记录数）；用构造器断言证明没有构造DrawRecord或TraceWriter，任务目录无暂存库，汇总无records。 |
| ✅ 真实异步worker | 未mock的 `JobManager.start()` 启动真实子进程，完成并保存历史，三轮36记录；额外3轮×81主抽实验第81位置观察数3，四/五/六计数1/2/0，频率1/3、2/3、0。均使用临时目录，不能据此推断百万记录容量。 |
| ✅ sampling1 | 全套中的固定seed序列、跨轮单一rng、Trace关闭/内存/sink对照及sink异常传播通过；无随机协议变更证据，不声明跨任意未来运行环境的二进制一致性。 |
| ✅ 静态检查 | 页面/仓库无旧include_records全量路径，无单轮Trace门槛，无v1/v2/v3默认历史或旧jobs目录。CLI `_simulation_payload(..., include_records=...)` 是按设计保留的内存序列化参数。旧历史文档说明未误删。`git diff --check`退出0。 |

✅ 真实CLI均通过子进程调用，退出0，并解析输出核对：

```sh
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator analyze --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 2 --trials 3 --initial-pity 29 --seed 42 --trace --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator simulate --draws 2 --trials 3 --initial-pity 29 --seed 42 --format json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m lottery_simulator export-trace --database /tmp/lottery-task12-IqxNEG/real-cli-a2unweza/history_v4.sqlite3 --run-id e63eb9a8-b75f-4bcb-9d39-6f8fc7732328 --output /tmp/lottery-task12-IqxNEG/real-cli-a2unweza/export.jsonl
```

✅ analyze返回80位置概率表；simulate Trace返回36记录，非Trace不含records，其余汇总相等；export返回37行，与真实异步worker历史一致。上述数据库、任务和导出文件仅位于临时目录，检查退出后已清理；重现export须先创建新的临时实验及run-id。

## 页面与启动验收边界

- ✅ AppTest及页面组件测试：导航/草稿、连续配置编辑、多轮Trace、结果视图、筛选/下载、历史复用/删除联动通过全套。数据层另已验证第81位置。
- ✅ 临时Streamlit启动：仅绑定 `127.0.0.1:57409`，`/_stcore/health`返回200与`ok`，`/`返回200与页面壳；数据目录为 `/tmp/lottery-task12-IqxNEG/health-55ara_yk`。首次因沙箱禁止socket创建而失败，获准在本地环回执行后通过；只停止本次创建的PID 242424，退出0，临时目录已清理。
- ⚠️未验：没有可调用的浏览器执行工具，故导航、草稿、3轮Trace、第81位置图、筛选、下载、复用/删除的真实浏览器交互和视觉验收尚未完成。AppTest和HTTP页面壳不能证明浏览器渲染或下载交互正常。
- ⚠️未验：真实OIDC会话与过期流程、Docker/Caddy/systemd/服务器部署、真实卷备份恢复、百万记录运行及总内存上限。批次写入约束的是Trace记录缓冲，不能消除现有汇总分布随取值规模增长的内存。

## 旧数据只读盘点：全部未删除

✅ 以下为主项目 `/home/qykj/202607/test/lottery_simulator/data` 中的实际文件。SQLite使用只读不可变连接查询版本和计数；盘点时不存在数据库的 `-wal`、`-shm`、`-journal` 伴随文件。所有数据库、jobs/jobs_v3目录归属 `qykj:qykj`，属于主项目数据，未迁移或删除。

| 确切数据库路径 | PRAGMA user_version | 历史/明细行数 | 大小 |
|---|---:|---:|---:|
| `/home/qykj/202607/test/lottery_simulator/data/history.sqlite3` | 1 | 2 / 110 | 45,056字节 |
| `/home/qykj/202607/test/lottery_simulator/data/history_v2.sqlite3` | 2 | 4 / 130 | 172,032字节 |
| `/home/qykj/202607/test/lottery_simulator/data/history_v3.sqlite3` | 3 | 2 / 0 | 36,864字节 |

✅ 三库验收前后大小和mtime_ns相同，依次为 `1789370155051904369`、`1789615106291387952`、`1789730736748067474`。这支持盘点期间未发生可见文件修改；未做SHA或全内容比对，不据此扩展为外部存储的完整性结论。

| 确切任务目录 | 任务/结果/抽样版本 | 状态 | 记录的PID |
|---|---|---|---:|
| `/home/qykj/202607/test/lottery_simulator/data/jobs/23925704-7458-44fc-9402-a6dfcd0bcdcb` | 均未标注 | completed | 27574 |
| `/home/qykj/202607/test/lottery_simulator/data/jobs/6e0fa8fe-0219-400e-ac1f-c556c7e9a375` | 均未标注 | completed | 76296 |
| `/home/qykj/202607/test/lottery_simulator/data/jobs/6f91b66b-3739-4e30-b033-a8e46c60bc7d` | 均未标注 | completed | 10656 |
| `/home/qykj/202607/test/lottery_simulator/data/jobs/7b6a66c1-155c-42a1-8563-d93f4e35e614` | 均未标注 | completed | 25801 |
| `/home/qykj/202607/test/lottery_simulator/data/jobs/850fd74f-2d96-48eb-ab41-fc00422b4058` | 均未标注 | completed | 76213 |
| `/home/qykj/202607/test/lottery_simulator/data/jobs/d3485b61-6834-42c2-a0b3-0959ca435846` | 均未标注 | completed | 27168 |
| `/home/qykj/202607/test/lottery_simulator/data/jobs_v3/3ac25455-1a0c-48f2-a9ff-4bfb729debb3` | 1 / 1 / 1 | completed | 113226 |
| `/home/qykj/202607/test/lottery_simulator/data/jobs_v3/460d6a4b-f1be-48ec-b014-f73071343a4e` | 1 / 1 / 1 | completed | 110455 |

✅ 八个任务各自保留 `parameters.json`、`state.json`、`result.json`、`worker.log`；未发现取消标记或暂存库。`data/jobs/active.lock`、`data/jobs_v3/active.lock`各0字节，均保留。盘点时上述记录PID的 `/proc/<pid>` 均不存在；这不构成之后停止服务的依据，切换时必须重新确认归属。

✅ 在主项目范围（排除 `.git`、`.venv`、隔离工作树）按backup/备份后缀/SQLite文件盘点，仅发现这三库与备份脚本、service/timer，没有实际备份文件。⚠️ 项目外、远端或容器卷中的备份未核实，备份脚本存在不能视为已有可恢复备份；不得假定旧数据删除后可恢复。

## 待现场步骤

1. ⚠️ 在可用真实浏览器中补做上述交互及视觉验收；真实部署、认证、备份恢复另行现场验证。
2. ⚠️ 未获实际合并切换授权。本轮到只读盘点为止；计划中“实际切换后清理”保持未勾选。
3. ⚠️ 授权切换后重新确认网页/worker归属、旧文件清单及备份，再执行明确的停止与逐文件清理；保留配置、日志、备份和未知文件，清session并运行v4小型多轮实验验证保存/读取/删除。当前未执行任何这些真实切换操作。
