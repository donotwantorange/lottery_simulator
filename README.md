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

以上服务仅供本机开发使用，不用于公网。新电脑的本机安装请从[首次安装](docs/local-usage.md#首次安装仅新环境需要)开始；服务器部署见下一节。

## 服务器安装

先按[部署指南](docs/deployment.md#准备服务器)准备 Ubuntu 24.04、域名与端口，再[获取完整项目](docs/deployment.md#获取项目)。项目包含安装脚本时，可在服务器项目根目录执行：

```bash
bash scripts/install.sh
```

当前腾讯云服务器已通过手动指令完成部署（用户确认）。新服务器建议先参考[手动安装](docs/deployment.md#手动安装)；上述自动安装脚本已纳入master，但尚未进行实机安装测试，既有手动部署不作为脚本验证证据。脚本按中文提示安装和配置，已有运行服务时退出。首次安装完成后按[上线验收](docs/deployment.md#上线验收)检查；已有服务器更新用[日常运维](docs/deployment.md#日常运维)，不重新安装。

## 文档导航

| 文档 | 解决的问题 |
|---|---|
| [本地使用手册](docs/local-usage.md) | 安装、启动、CLI、常见问题、本地备份与恢复 |
| [网页页面指南](docs/dashboard-guide.md) | 角色池、实验配置、结果图表、Trace和权限管理 |
| [部署指南与运维说明](docs/deployment.md) | 服务器准备、脚本或手动安装、验收、更新、备份和排障 |
| [修改记录](docs/changes/README.md) | 设计、计划、实施及验收证据 |

## 当前支持范围

- 按抽次分析支持自适应折线图、共享悬停读数和分页数值表；已有Trace记录可直接使用，无需重新模拟。操作见[网页指南](docs/dashboard-guide.md#按抽次分析)，验证证据见[图表修改记录](docs/changes/2026-09-29-position-chart-usability.md)。
- React＋Django是唯一网页入口，旧Streamlit已移除；新版不支持旧历史导入。
- 网页数据默认保存在私有的 `data/history_v5.sqlite3`，包含账号、配置、会话和历史，不能公开或提交Git。
- 本机CLI可独立分析和模拟，但不会自动写入网页历史。
- React＋Django、图表和安装脚本已纳入master。2026-09-30用户确认腾讯云服务器已使用手动指令部署，提供日志显示后端健康和正式HTTPS证书签发；自动安装尚未实机测试，已有隔离检查不等于实机验收。服务器逐项业务验收与脚本实机验收的边界见[验证状态](docs/deployment.md#验证状态)，后续修改见[台账](docs/changes/README.md)。
