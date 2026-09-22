# 概率核心重构本地合并

✅ 用户授权后，`feature/probability-core` 已快进合并到本地 `master`，实现提交为 `63b59f1`。

✅ 合并后在主目录运行 `.venv/bin/python -m unittest discover -q`：311 项测试，89.164 秒，结果 OK。日志位于 `/tmp/probability-core-merged-tests.log`。

主目录原有 README、本地使用手册、页面指南及设计计划共六份文档已备份到 Git stash，名称为 `pre-probability-core-merge original local docs`；合并结果包含它们的更新版本。未把旧文档备份重新覆盖到新实现上。

后续本地使用入口为 `/home/qykj/202607/test/lottery_simulator`，无需进入工作树。此前实施记录中的“未提交、未合并”描述属于各阶段当时状态，以本记录为最新状态。

未在线推送。旧历史库与旧任务文件保留；新应用默认使用 `data/history_v3.sqlite3` 和 `data/jobs_v3/`。本次未执行旧数据清理、服务器部署或真实浏览器点击验收。开发工作树及审查记录暂保留。

## 合并后的文档补充

已将 README 的变更入口更新为本次概率核心重构及最新合并记录；同步计划顶部与交接入口、设计和实施记录顶部的当前状态。历史阶段原文保留，避免改写当时事实。本次仅修改 Markdown，检查本地链接目标和差异格式，不重复运行代码测试。
