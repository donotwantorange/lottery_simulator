# 本地开发与使用

本文描述工作树中已实现的 Django API、React 前端和命令行入口。旧 Streamlit 页面入口及依赖已从本工作树移除；原稳定目录和旧数据没有因此被修改。

## 环境与首次初始化

在项目根目录使用 Python 3.11+、Node.js 22.12+：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci
```

数据库默认是 `data/history_v5.sqlite3`，任务目录和导出临时目录分别是 `data/jobs_v5/`、`data/exports_v5/`。第一次启动前迁移并交互创建首个管理员：

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py init_admin --username 管理员用户名
```

创建过程要求输入用户名和密码，密码不会回显。没有网页注册或默认账号。

## 启动开发服务

开两个终端，均在项目根目录运行：

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

```bash
npm --prefix frontend run dev
```

访问 `http://127.0.0.1:5173`。Vite 将 `/api` 请求代理至 `127.0.0.1:8000`，浏览器使用同源 Cookie 和 CSRF 流程。停止时分别在两个终端按 `Ctrl+C`。Django 开发服务器仅监听回环地址，不用于公网服务。

修改后端代码需重启 Django；前端开发服务器通常会热更新。Django 服务重启不等于主动停止已接受的模拟任务；任务以独立 worker 执行。正常退出网页登录不会取消 worker。

## 登录后的基本流程

1. 首个管理员登录后可在管理员页面创建普通账号。管理员设置的初始密码会要求用户首次登录时修改。
2. 在“角色池”创建或导入角色池；公共池由管理员管理，私有池按所有者和公开/隐藏状态授权。
3. 在“新建实验”选择有权使用的池，保存实验配置并填写轮数、主抽数、初始保底进度、种子及 Trace 选项，然后显式提交模拟。
4. 在“实验结果”查看任务状态、汇总、图表和逐抽记录；在“历史记录”查看已完成运行、按当前角色池确认重跑或删除记录。
5. 管理员页面提供账号、实验配置和任务管理。前端按钮不是授权边界，服务端会再次校验权限。

Trace 默认关闭。逐抽记录下载由历史页面提供，使用 JSONL；具体页面行为和稀有度映射见[网页页面指南](dashboard-guide.md)。

## 数据路径隔离

默认路径为：

```text
data/history_v5.sqlite3
data/jobs_v5/
data/exports_v5/
```

可以在启动两个进程前设置绝对路径；以下示例只使用独立临时目录：

```bash
export LOTTERY_DATA_DIR=/tmp/lottery-local
export LOTTERY_DB_PATH=/tmp/lottery-local/history_v5.sqlite3
export LOTTERY_JOBS_DIR=/tmp/lottery-local/jobs_v5
export LOTTERY_EXPORTS_DIR=/tmp/lottery-local/exports_v5
```

这些变量由 Django/worker 读取；CLI 的独立模拟不写网页历史。新网页不自动导入或迁移旧数据库。使用旧 Streamlit 程序的稳定目录和数据时，保持其原环境与路径，不要把旧数据库路径传给新工作树。

生产环境必须通过 `LOTTERY_ENV=production` 并设置高熵 `SECRET_KEY`；缺失密钥会拒绝启动。不要使用 `VITE_` 前缀存放任何密钥，因为该变量会进入浏览器可见的构建产物。

## CLI

CLI 是本机命令行模拟/分析工具，不会写入网页登录的历史：

```bash
.venv/bin/python -m lottery_simulator analyze --format json
.venv/bin/python -m lottery_simulator simulate --pool-config configs/pools/default.json --draws 30 --trials 1000 --seed 42
```

配置格式和更多参数以当前 `python -m lottery_simulator --help`、子命令 `--help` 及 `configs/` 示例为准。网页运行使用用户有权访问的数据库角色池快照，不是 CLI 文件路径。

## 备份与恢复

数据库内含用户资料、密码哈希、会话、配置和历史。备份目录应为受控私有目录，备份文件权限为 `0600`，不得公开或提交：

```bash
install -d -m 700 backups
.venv/bin/python scripts/backup_db.py data/history_v5.sqlite3 backups/lottery-v5-$(date +%F-%H%M%S).sqlite3
```

成功时脚本打印 `Backup integrity_check: ok` 并以状态码0退出。SQLite 在线备份包含已提交数据；它不包含 `jobs_v5/` 中的运行状态/暂存文件或 `exports_v5/` 临时文件。重要备份应存放在访问受控的异机位置。

恢复会替换数据库。先停 Django 与相关 worker，保护当前库，然后将选定备份恢复到目标路径并检查完整性：

正式覆盖前，建议先在独立临时目录演练备份、恢复、历史与Trace读取和小规模写入；数据库和任务目录都必须隔离。此前的[v4隔离演练记录](changes/2026-09-23-backup-restore-drill.md)仅为历史参考，新版应按v5结构验证。临时副本不是长期备份。

```bash
.venv/bin/python scripts/backup_db.py data/history_v5.sqlite3 backups/pre-restore-v5-$(date +%F-%H%M%S).sqlite3
.venv/bin/python scripts/backup_db.py backups/lottery-v5-YYYY-MM-DD-HHMMSS.sqlite3 data/history_v5.sqlite3
.venv/bin/python -c "import sqlite3; c=sqlite3.connect('file:data/history_v5.sqlite3?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchall()); c.close()"
```

每一步都必须成功；完整性结果应为 `[('ok',)]`。随后启动服务并用登录、历史读取和小型模拟确认可用。任务状态目录不随 SQLite 备份恢复，不要因此盲目删除。详细的生产恢复流程见[部署说明](deployment.md)。

## 当前未覆盖

本地双账号浏览器验收已完成，观察记录见[任务14浏览器验收](changes/2026-09-29-user-pool-browser-acceptance.md)。旧入口测试替代关系见[覆盖审计](changes/2026-09-29-legacy-ui-coverage-audit.md)。真实生产部署和真实旧数据切换仍未执行。
