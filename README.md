# 抽奖模拟器

用于本地多轮抽奖模拟、理论概率分析和逐抽结果查看。Python实现模拟核心，React提供网页，Django负责本地账号、角色池、实验配置和历史记录管理。

## 日常启动

本机主项目已完成依赖安装、v5数据库和首个管理员初始化。已有环境直接启动，不必重复安装或运行初始化命令。

在两个终端分别执行：

终端一：

```bash
cd /home/qykj/202607/test/lottery_simulator
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

终端二：

```bash
cd /home/qykj/202607/test/lottery_simulator
npm --prefix frontend run dev
```

访问 [本地网页](http://127.0.0.1:5173)，使用已有账号登录。选择默认角色池即可模拟，不必先创建池或保存实验配置。若端口已占用，先确认是否已有服务运行，不要盲目启动第二份服务。

以上服务仅供本机开发使用，不用于公网。新机器安装请从[首次安装](docs/local-usage.md#首次安装仅新环境需要)开始。

## 文档导航

| 文档 | 解决的问题 |
|---|---|
| [本地使用手册](docs/local-usage.md) | 安装、启动、CLI、常见问题、本地备份与恢复 |
| [网页页面指南](docs/dashboard-guide.md) | 角色池、实验配置、结果图表、Trace和权限管理 |
| [部署接口与运维说明](docs/deployment.md) | 生产配置、发布顺序、服务生命周期和服务器备份 |
| [修改记录](docs/changes/README.md) | 设计、计划、实施及验收证据 |

## 当前支持范围

- 按抽次分析支持自适应折线图、共享悬停读数和分页数值表；已有Trace记录可直接使用，无需重新模拟。操作见[网页指南](docs/dashboard-guide.md#按抽次分析)，本次验证及尚未提交的修改见[图表修改记录](docs/changes/2026-09-29-position-chart-usability.md)。
- React＋Django是唯一网页入口，旧Streamlit已移除；新版不支持旧历史导入。
- 网页数据默认保存在私有的 `data/history_v5.sqlite3`，包含账号、配置、会话和历史，不能公开或提交Git。
- 本机CLI可独立分析和模拟，但不会自动写入网页历史。
- React＋Django基础版本已本地验收并合并；后续图表及文档修改已验证但尚未提交或合并。未推送GitHub、未做公网部署。基础版本证据见[实施记录](docs/changes/2026-09-24-user-pool-experiment.md)，后续状态见[修改台账](docs/changes/README.md)，本地验收不等于生产部署通过。
