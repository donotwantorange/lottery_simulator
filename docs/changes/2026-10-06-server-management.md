# 统一服务器管理菜单实施记录

- 日期：2026-10-06。用户要求统一安装/卸载/运维/更新菜单，明确永久删除需二次确认。
- 基准：master `2612b08`；包含同工作区[旧镜像预检](2026-10-06-upgrade-image-preflight.md)后续联动。[设计](2026-10-06-server-management-design.md) · [计划](2026-10-06-server-management-plan.md) · [使用说明](../deployment.md#统一管理菜单)。
- 状态：实现及约定隔离验证完成；实现与文档随本提交纳入；实际服务器部署未执行。原本地使用手册、Compose/Caddy、业务实现、依赖、迁移及真实数据不修改。

## 改动与步骤

install.sh保留实际安装/升级流程，无参数委派source的manage.sh菜单，直接首次安装为--install，--upgrade沿用。菜单Git更新先检查干净master和预期origin，快进拉取后exec新版升级入口；拉取失败不进入维护。新增--restore接原构建流程，先验证原命名卷及无人使用，v6数据预检和快照成功后才迁移，不执行管理员初始化。

manage.sh核对实际原app/Caddy及挂载/版本，运维只操作原容器，暂停恢复额外确认；停止/重启暂停备份和网站入口，旧任务检查拒绝未知/活动状态。备份读取实际v5/v6数据库路径，快照同时留备份卷和私有宿主机目录。每日备份配置只自动处理标准目录及unit、保存旧unit，实际备份成功后启用timer。

卸载保留模式保存原容器/环境元数据，不删除持久卷或.env；永久删除展示四个卷和私有备份目录/.env，经UNINSTALL及DELETE-项目名确认再删除。严格检查卷标签、其它容器使用、项目网络及备份路径，删除只针对已核对项目；代码、Docker和外部备份保留，timer停用而unit定义保留。读取容器列表失败直接停止，不把读取失败当作空部署。临时测试中的删除使用替身，不针对真实/var/backups或/etc执行变更。

涉及文件：scripts/install.sh、scripts/manage.sh、scripts/upgrade.sh、tests/test_installer.py、tests/test_upgrader.py、docs/deployment.md、docs/windows-wsl-temporary.md、修改台账及本主题三份文档。

## 验证

第一轮菜单/原安装36项通过，32.829秒；第二轮合并原数据/部署检查共62项通过，51.540秒。其后补读取失败拒绝与timer归属检查，最终四组63项全部通过，51.597秒；三个Shell语法及入口帮助检查通过。修改文档84处本地链接/锚点无异常，代码块成对，diff检查通过。原本地使用手册及Compose/Caddy、requirements对HEAD无差异。以上为隔离控制流及原临时SQLite检查，不能当作服务器实机结果。

运行命令：

```bash
cd /mnt/d/Web_project/lottery_simulator
/home/lottery/.venvs/lottery-simulator/bin/python -B -m unittest tests.test_upgrader tests.test_installer tests.test_upgrade_probe tests.test_deployment_files
bash -n scripts/manage.sh
bash -n scripts/install.sh
bash -n scripts/upgrade.sh
bash scripts/install.sh --help
```

菜单回归覆盖取消/退出、v5原容器启动、暂停恢复、停止/重启与活动任务拒绝、v5/v6备份路径、保留卸载、永久删除双确认及范围、外来/共享卷与重定向备份拒绝、越界删除路径拒绝、Git快进与拉取失败/脏树、只读状态日志、v6保留卷重装的备份顺序及无初始化、残留容器/坏数据拒绝、定时备份v6及标准位置限制、备份失败/drop-in不启用timer，以及Docker列表读取失败拒绝。

完整服务器安装/更新/卸载、保留卷真实重装、正式HTTPS、生产systemd配置和实际删除未验证。本机18080/8000服务及账号数据保持原运行状态；此前服务器旧镜像不可用的原因仍需服务器只读输出，本轮不代替其恢复。

## 文档整理与发布准备

部署指南改为菜单优先，补充停止/重启后的timer恢复、保留卷重装与备份恢复的区别及首页导航；手动备份命令移至附录，测试数量集中放在验证状态。文档链接、入站章节锚点、三个Shell及26段文档Bash语法检查通过，原本地使用手册未改。此次发布包含同工作区的菜单实现、旧镜像预检、对应测试和配套文档；Git提交号与远端状态以实际Git记录为准。

提交前重新运行上述四组测试：63项通过，53.304秒；仅隔离测试，未执行真实管理菜单。
