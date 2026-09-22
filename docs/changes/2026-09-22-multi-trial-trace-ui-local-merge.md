# 多轮 Trace 与界面重组本地合并

合并日期：2026-09-22。

✅ 用户选择本地合并后，`feature/multi-trial-trace-ui` 已合并到本地 `master`。

- 功能提交：`3db0151`（`feat: add multi-trial trace dashboard`）
- 主工作区原文档保留提交：`380af0d`（`docs: preserve local planning updates`）
- 合并提交：`b35837c`（`Merge branch 'feature/multi-trial-trace-ui'`）

两份add/add冲突仅涉及多轮Trace的设计和计划文档。经对照确认，功能分支版本是在主工作区原版本基础上补充完成状态、最终测试和审查结论，因此合并采用实施完成版；主工作区其他概率核心文档由独立提交完整保留。

✅ 合并后在主目录 `/home/qykj/202607/test/lottery_simulator` 运行：

```bash
.venv/bin/python -m unittest discover -q
```

结果：385项测试通过，103.172秒，退出码0。测试中的预期CLI错误输出、Streamlit bare-mode提示及故障注入日志不代表测试失败。

## 当前状态

- 本地使用入口为项目主目录，无需进入功能工作树。
- 未在线推送；本地`master`领先远端。
- 默认新数据路径为`data/history_v4.sqlite3`和`data/jobs_v4/`。
- 旧v1/v2/v3数据库、旧任务、锁文件和日志均未删除或迁移。
- 未执行真实浏览器视觉验收、Docker/Caddy/OIDC/systemd现场部署、百万记录容量验收、备份恢复或实际v4切换清理。
- 功能工作树和本地功能分支暂时保留，因为工作树的忽略目录中仍有独立审查台账；未强制删除这些记录。

此前设计、计划和实施记录中的“未提交/未合并”属于相应阶段当时状态；本文件是当前本地Git集成状态的最新依据。
