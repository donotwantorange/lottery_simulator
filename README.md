# 抽奖模拟器

项目由 Python 模拟核心、Django 5.2/DRF API 和 React/Vite 网页组成。新网页使用本地账号登录；账号、角色池、实验配置、历史和 Django 会话保存在 `data/history_v5.sqlite3`。规则 1 仍由 Python 核心实现。

## 本地开发

Python 3.11+ 与 Node.js 22.12+。从项目目录安装后，用两个终端分别启动 API 和前端：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci
.venv/bin/python manage.py migrate
.venv/bin/python manage.py init_admin --username 管理员用户名
```

终端一：`.venv/bin/python manage.py runserver 127.0.0.1:8000`；终端二：`npm --prefix frontend run dev`。浏览器访问 `http://127.0.0.1:5173`，只在本机开发时使用此服务。`init_admin` 交互创建首个管理员，不回显密码。

运行 CLI 示例：

```bash
.venv/bin/python -m lottery_simulator analyze --format json
.venv/bin/python -m lottery_simulator simulate --pool-config configs/pools/default.json --draws 100 --trials 1000 --seed 42
```

更多本地路径、登录和备份说明见[本地使用手册](docs/local-usage.md)，网页操作见[网页页面指南](docs/dashboard-guide.md)。

## 数据保护

新网页默认使用 `data/history_v5.sqlite3`、`data/jobs_v5/` 和 `data/exports_v5/`；路径可用 `LOTTERY_DATA_DIR`、`LOTTERY_DB_PATH`、`LOTTERY_JOBS_DIR`、`LOTTERY_EXPORTS_DIR` 设置。旧 Streamlit 代码入口已从本工作树移除，但原稳定目录及其旧数据库和任务目录仍保持原状。不得把旧数据路径直接交给新版程序。

数据库包含账号、密码哈希及会话。备份应限制访问，脚本创建的目标文件权限为 `0600`：

```bash
.venv/bin/python scripts/backup_db.py data/history_v5.sqlite3 backups/lottery-v5-$(date +%F-%H%M%S).sqlite3
```

恢复和生产服务配置见[部署说明](docs/deployment.md)。这里只描述接口，不代表已经进行真实服务器部署。

## 迁移状态

React/Django 是唯一网页入口；本地双账号浏览器验收结果见[记录](docs/changes/2026-09-29-user-pool-browser-acceptance.md)。旧 UI 清理依据见[覆盖审计](docs/changes/2026-09-29-legacy-ui-coverage-audit.md)。真实服务器部署与旧数据切换未执行；不要把本工作树当作真实数据迁移步骤。
