# 抽奖模拟器

抽奖模拟与理论分析工具。网页使用 React＋Django，提供独立规则、角色池、实验配置、历史与 Trace；Python CLI 可读取 JSON 配置独立分析和模拟，不写网页历史。

## 文档

| 文档 | 内容 |
|---|---|
| [本地使用手册](docs/local-usage.md) | 原有本地安装、启动、CLI 和维护说明 |
| [网页页面指南](docs/dashboard-guide.md) | 规则、角色池、实验和结果页操作 |
| [部署指南与运维说明](docs/deployment.md) | v6保留数据更新、旧版永久卸载重装、独立v5账号导入、备份与恢复 |
| [Windows/WSL临时说明](docs/windows-wsl-temporary.md) | 本机v6工作树、验收环境和切换顺序 |
| [长期开发规范](docs/standards/README.md) | 开发验证、变更记录、架构数据、权限、界面及部署约定 |
| [修改记录](docs/changes/README.md) | 设计、实施和验证记录 |

本地使用手册包含当前v6开发数据路径；其中标注的v5路径仅用于识别旧数据，不是当前默认值。

## 数据与版本

当前代码默认使用 `data/history_v6.sqlite3`、`data/jobs_v6/` 和 `data/exports_v6/`。v5 数据不会自动升级或被覆盖。部署选择分为两条：普通 `--upgrade` 仅更新标准v6并保留数据；明确放弃旧业务时，使用独立的旧版永久卸载重装流程。手动v5账号导入仍可作为独立保留账号的迁移路径，但不由更新菜单调用。步骤和限制见[部署指南](docs/deployment.md#版本更新)及[v5账号保留与v6切换](docs/deployment.md#v5账号保留与v6切换)。

规则决定抽取概率、保底与赠送；池绑定一条规则并保存角色、权重、UP分组和奖励；实验引用池并保存运行参数。结果冻结规则、池和参数快照。Trace 关闭时只保留汇总，开启时保存抽取与直接赠送事件。具体统计口径见[网页指南](docs/dashboard-guide.md)。

新版界面与接口已完成本机隔离验收；本轮全部实现位于`feature/reliability-ui-improvements`工作树，尚未合并，主目录运行环境未因此自动切换。真实Compose/systemd和由新流程备份进行的完整恢复仍未验。既有旧版手动部署不能证明本轮服务器功能或自动安装通过。验证边界见[部署验证状态](docs/deployment.md#验证状态)与[本轮实施记录](docs/changes/2026-10-07-current-update-legacy-reinstall.md)。
