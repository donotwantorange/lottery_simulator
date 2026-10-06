# 升级旧镜像可用性预检修复

- 日期：2026-10-06；基准：本地master `2612b08`。
- 问题：用户服务器v5升级在停止Caddy、检查任务并暂停旧app后，启动旧镜像备份辅助容器失败，Docker报告 `No such image`。源库备份尚未完成，脚本未进入旧app移除及数据库迁移阶段。镜像为何不可用尚待服务器只读检查；本机没有服务器访问权限。
- 方案与步骤：保留原旧镜像要求；在维护前用其启动无网络、无数据卷的临时Python容器并导入旧任务验证器及备份模块。失败明确提示保留旧app，尚未停止网站或timer；预检及备份辅助容器均使用 `--pull never`，不隐式拉取替代镜像。不增加镜像自动恢复、commit或新依赖。
- 文件：`scripts/upgrade.sh`、`tests/test_upgrader.py`、`docs/deployment.md`及本记录与台账。原本地使用手册及业务代码不修改。
- 验证：WSL运行 `python -B -m unittest tests.test_upgrader tests.test_upgrade_probe tests.test_installer tests.test_deployment_files`，46项通过，34.584秒；`bash -n scripts/upgrade.sh`及diff检查通过。新增v5/v6旧镜像不可启动回归，要求在timer、网站停止、app暂停、备份目录创建或数据库操作之前退出。实际Docker失败依据用户日志，本轮未另做真实镜像删除或真实升级。
- 未验：服务器旧镜像恢复、真实升级和公网HTTPS；现有临时容器与假Docker测试不能替代这些验收。
- Git：随统一管理菜单提交纳入，未实际部署；原升级实现及用户部署文档重写已提交。对应[升级记录](2026-10-06-compose-upgrade.md)、[恢复说明](../deployment.md#升级备份提示-no-such-image)。
