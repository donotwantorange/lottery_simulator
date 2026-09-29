# 旧 Streamlit 入口覆盖迁移审计

任务14覆盖核对与清理记录，2026-09-29。目标是辨别哪些旧测试验证仍需保留的行为，哪些只验证已退役框架机制。用户随后明确授权清理旧版本；清理仅发生在隔离工作树，没有触碰原稳定目录或真实数据。

| 旧测试/代码范围 | 新架构证据或决策 | 当前结论 |
|---|---|---|
| `tests/test_auth.py`、`dashboard/auth.py`、`.streamlit/` | 旧OIDC和免登录模式不属于已确认的本地账号设计。新版登录、限流、CSRF、会话、维护入口由`tests/web/test_accounts.py`、`test_sessions.py`和双账号浏览器流程验收。 | 旧认证合同应退役；真实凭据和私有secrets不在清理范围。 |
| `tests/test_configuration_view.py`、旧Streamlit配置编辑 | 角色表/奖励/名称输入由`PoolEditor.test.tsx`、`Pools.test.tsx`、`ImportDialog.test.tsx`与Pool/Experiment API测试覆盖；文件格式、重复键、非有限数值及版本由核心配置测试覆盖。旧`st.data_editor` widget状态不是React合同。 | 用户可见配置行为已有新证据；框架widget细节不迁移。 |
| `tests/test_simulation_view.py`、`tests/test_trace_view.py`、`tests/test_trace_details.py` | 四个结果视图、五类图和三来源由`Results.test.tsx`、`ChartPanel.test.tsx`、`tests/test_charts.py`与浏览器观察覆盖；Trace筛选、分页、列/稀有度显示由`TraceTable.test.tsx`、API下载测试及浏览器观察覆盖。 | 旧渲染控件测试不继续运行；共享Trace格式/校验测试须保留。 |
| `tests/test_history_navigation.py` | 历史列表筛选、本人隔离、选择快照、重跑revision二次确认、删除确认由`History.test.tsx`、`tests/web/test_owned_runs.py`、端到端流程覆盖。旧双记录并排比较未列入新版已确认设计，不擅自重建。 | 旧比较widget行为退役，历史权限与快照行为保留。 |
| `tests/test_dashboard_app.py`、`dashboard/app.py`和`dashboard/views/` | 新五页React路由、用户切换、任务状态/停止、配置和Trace由前端14文件29项、Django63项、核心181项及本地浏览器记录共同覆盖；旧`AppTest`、sidebar fragment与Streamlit会话机制不属于新合同。 | 范围替代已核对，不声称旧用例逐行等价；旧入口已从本工作树删除。 |
| `tests/test_trace_lifecycle.py`、`tests/test_jobs.py`、`tests/test_repository.py`、`tests/test_trace_export.py` | 旧用例使用任意v4库路径及旧`JobManager.start`调用；在新仓库下连同旧模型测试定向运行114项得到103个错误、5个失败，主要根因是v5仅允许Django settings数据库和新任务归属契约。新版`tests.web`63项、真实临时v5备份/端到端及共享Trace存储测试覆盖新合同。 | 移除旧v4夹具测试；保留独立的`tests/test_trace_store.py`、`test_trace_queries.py`四项及图表/规则测试。 |
| `tests/test_dashboard_models.py` | 旧文件混有过时限额/版本断言，但也包含现用`dashboard.job_models`的序列化、控制字段及JSON写入可读/无临时残留检查。独立复核指出新web测试未直接覆盖这些边界。 | 删除旧文件后迁移为`tests/test_job_models.py`六项当前v5契约测试，定向运行通过；未继续沿用旧上限假设。写入测试不单独证明故障注入时的原子性。 |

实际清理范围：`dashboard/app.py`、`dashboard/auth.py`、`dashboard/views/`中的六个页面文件和空`__init__.py`；`.streamlit/`中两个示例/配置文件；上述纯旧UI测试、四个旧v4仓库/任务夹具文件及过时模型测试（由新六项替代）；`requirements.txt`中的`streamlit[auth]`。`altair`仍被新版`dashboard/charts.py`引用，故保留。`tests/test_trace_queries.py`只删除旧v4历史工厂用例，保留四项独立Trace查询测试。所有历史设计文档保留原始记载，不机械改写。无真实历史、备份或任务目录删除。

`configs/rule1_default.json`仍由`tests/test_config_documents.py`作为“旧格式必须拒绝”的输入夹具使用，不是新版默认池，也不会被新版入口自动加载；当前默认池是`configs/pools/default.json`。
