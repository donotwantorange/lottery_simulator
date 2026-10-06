# Compose交互式升级实施记录

- 日期：2026-10-06；用户要求按旧安装脚本增加升级功能并更新文档。
- 状态：已实现并通过隔离控制流程/数据预检与原生Docker探针；整机服务器升级和正式HTTPS仍未实测。不将模拟检查标作已部署。
- 源码：基于本地master `7ea72c9c03716e243e3286f9a98dc85c9d9bf331`；升级实现、测试与文档随本提交纳入，尚未推送。
- [设计](2026-10-06-compose-upgrade-design.md) · [实施计划](2026-10-06-compose-upgrade-plan.md) · [部署操作](../deployment.md#脚本升级)。

## 实际改动

新增 `bash scripts/install.sh --upgrade`，无参数首次安装保持原保护。复用原前后端构建、网络预检、迁移和启动；准备/收尾由被source的upgrade.sh处理，upgrade_probe.py经stdin在旧镜像内执行，使用旧镜像自己的任务验证器，避免v5被新v6解析器误判。

升级核对同机标准Docker Unix socket、Compose项目/目录/服务、旧镜像ID、健康状态、数据路径和命名卷/前端绑定；远程或rootless上下文、非标准配置、其它项目容器、停止/部分安装均在维护前拒绝。DOCKER_CONTEXT优先于DOCKER_HOST解析，不能用本机路由去证明远程daemon没有冲突。

交互确认后暂停已有备份timer、确认备份服务未活动、停止Caddy、检查任务及worker。进一步冻结旧app并以无网络旧镜像读只读数据卷重新检查，防止晚到请求在检查后提交；复用backup_db快照接口，主机副本再次integrity_check。辅助容器最长600秒，失败按CID文件只清理本次辅助容器、解除本次app暂停；不自行重启Caddy或timer。

主机私有备份包含源库快照、整个旧data、前端、原.env、原容器inspect及新Compose配置，路径为`/var/backups/lottery/<项目>/upgrade-<时间>-<随机值>`，仅所有者可访问，目录0700。原备份卷中保留同名快照，真实密钥/账号不会打印或提交Git。备份齐全后才移除已核对的旧app容器并compose down重建网络；没有-v、remove-orphans、volume rm或全局清理。

v6只migrate并保留全部业务；v5拒绝已有目标库/非空目标任务、空v6 migrate后执行import_v5_accounts和init_business_defaults。v5只迁账号及登录限制，旧业务/会话不迁，旧库和目录保持原位。不重置管理员、密钥，不自动Git拉取、数据库覆盖或续跑。

升级启动用up --wait确认app健康；已有systemd unit可能定制，脚本提示手动对照更新，文档补标准unit备份/安装/daemon-reload及先验证备份后恢复timer。没有timer不新建。原本地使用手册未改，无新迁移/格式版本/依赖。

## 验证结果与命令

源码冻结后的集中定向检查：45项通过，35.336秒（5项真实SQLite/文件预检、10项模拟升级、原安装/部署30项）。最后调整远程上下文优先级及fixture环境隔离后，只重跑受影响的升级10项，12.805秒全部通过；安装/部署与数据预检范围未再变更。两个Shell语法检查通过。

```bash
cd /mnt/d/Web_project/lottery_simulator
/home/lottery/.venvs/lottery-simulator/bin/python -B -m unittest tests.test_upgrade_probe tests.test_upgrader tests.test_installer tests.test_deployment_files
/home/lottery/.venvs/lottery-simulator/bin/python -B -m unittest tests.test_upgrader
bash -n scripts/install.sh
bash -n scripts/upgrade.sh
bash scripts/install.sh --help
```

测试全部使用临时项目、PTY、假Docker/systemctl及临时SQLite；备份相关假命令将/var/backups重映射到TemporaryDirectory。覆盖v5/v6顺序、原.env保持、未知来源/卷/挂载/发布端口/其它容器/未确认早停、备份或任务检查失败不移除旧app、失败解冻及辅助容器清理、网络冲突不迁移/启动、migrate/import失败不重启、timer暂停/缺失/活动service和远程上下文拒绝。没有在真实机器调用升级入口。

额外验证：

- 从旧提交a20a893导出仓库外源码，显式创建完整迁移的临时v5库和假账号；旧v5验证器接受合法cancelled任务、拒绝running任务。新探针没有用v6模型解析旧任务。
- 仅使用缓存官方Python镜像，创建独立无网络/无数据卷测试容器；实际pause、暂停时docker cp、rm --force通过。该测试容器已删除，没有测试卷或网络留下；不是完整Compose升级。
- 原业务实现未改，不重复之前271/65业务全套；不推断真实账号导入、下载网络、正式证书或生产备份unit已在线通过。

第一次测试fixture缺少json导入、容器ID不是Docker十六进制、网络预检配置/脚本遗漏，在运行最终组前修正；未以这些搭建错误修改产品语义。子代理Windows端缺termios、普通WSL调用受权限限制，主执行者随后在已有授权的WSL中完成回归。没有因为环境限制安装新依赖。

证据：`D:\Web_project\lottery-upgrade-tests-20261006`中的final-tests.log、upgrader-final.log、legacy-probe-result.json、help说明、最终差异检查final-audit.json；旧源码、临时v5库/脚本也在此仓库外目录。初轮基准/升级日志在`D:\Web_project\lottery-local-integration-20261006`，不混入Git。原生Docker暂停/复制/移除实测命令与结果摘要保留于本轮证据；暂停测试使用缓存镜像，不是镜像拉取成功证明。

## Git与真实环境边界

最终diff --check与本地文档链接/锚点检查通过；修改仅为安装升级脚本、对应测试及文档。原docs/local-usage.md、业务源码、Compose/Caddy配置、迁移、依赖清单/锁文件和真实.env/data均未改；测试输出不在待提交清单。Git状态与文件清单见仓库外final-audit.json。

服务器需取得包含新入口和两个辅助脚本的完整版本才能使用。没有连接或升级真实服务器，没有恢复真实备份timer、覆盖系统unit、修改本机18080/8000服务、账号或数据。旧v5业务不会自动出现在v6中，升级前应明确接受此范围。实际服务器升级成功后，应补充该服务器的来源、备份、步骤、业务/HTTPS及备份验证证据。

## 2026-10-06提交前复核

复核安装入口、升级准备/迁移/收尾、旧镜像数据探针及配套文档，未发现阻止本次提交的问题。重新执行上述四组unittest，45项全部通过，35.190秒；两个Shell的bash -n及安装入口--help通过。原本地使用手册对HEAD无差异，未执行真实升级。此前原生Docker及旧v5探针结果沿用已有记录，本次未重跑。

本地提交准备包含升级脚本、测试和相关文档，不包含私有数据或仓库外测试产物。GitHub只读查询发生连接错误，未据此确认远端版本，未推送；实际提交号以Git记录为准。
