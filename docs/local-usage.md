# 本地使用手册

本手册负责本机开发环境的安装、启动与维护。页面操作见[网页页面指南](dashboard-guide.md)，服务器安装和运维见[部署指南](deployment.md)，项目入口见[README](../README.md)。`scripts/install.sh` 用于服务器首次部署，不代替本文的本机开发步骤。

项目目录为 `/home/qykj/202607/test/lottery_simulator`。本机已完成依赖、数据库和管理员初始化，日常使用从下一节开始；新机器才需要“首次安装”。本文命令均在项目根目录执行。

## 日常启动与停止

两个终端先分别进入项目目录：

```bash
cd /home/qykj/202607/test/lottery_simulator
```

终端一启动API：

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

终端二启动网页：

```bash
npm --prefix frontend run dev
```

访问 [http://127.0.0.1:5173](http://127.0.0.1:5173)。前端将API请求转发到8000端口；两个服务都要运行。它们仅监听本机，不用于公网。

停止模拟请在网页点击“停止任务”并等待取消完成。退出登录、关闭网页或停止Web服务不会自动取消独立worker。准备完整停机时，先等待模拟完成或明确取消，再分别在两个服务终端按 `Ctrl+C`。

Django默认开发模式通常会自动重载Python代码，Vite通常会热更新前端；修改环境变量、依赖或需要确认新配置生效时，应重新启动相应服务。

## 首次安装（仅新环境需要）

需要Python 3.11+、Node.js 22.12+。安装前确认当前目录和数据路径，已有环境不要重复初始化账号。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci
.venv/bin/python manage.py migrate
.venv/bin/python manage.py init_admin --username 你的管理员用户名
```

将用户名占位内容替换为实际用户名。密码交互输入、不回显，至少6个字符，建议使用更长的密码；不要把密码写入命令或聊天。初始化同时创建默认公共池，不提供默认密码或网页注册。已有账号/池的数据库会拒绝重复初始化。

完成后按“日常启动”打开网页。管理员创建的其他账号首次登录需修改初始密码。

## 完成一次小型实验

已有开启Trace的历史也可直接用于查看新版图表，无需重跑。按前节启动后端和前端、刷新页面即可加载修改；不用迁移数据库或重新初始化管理员。服务器静态资源的更新方式另见[版本更新](deployment.md#版本更新)。

登录后直接使用默认角色池，设置每轮30主抽、2轮、两种初始保底均为0、种子42、开启Trace。无需先保存实验配置。

点击“开始模拟”，等待完成并确认已写入历史。默认赠送规则下，每轮30主抽加10赠送，两轮共60主抽、20赠送、80条Trace。在“历史记录”可再次查看、下载或删除。具体结果页解释见[网页指南](dashboard-guide.md)。

在“按抽次分析”中缩放窗口检查图表联动，将鼠标移到某个抽次附近查看各星级次数/比例及有效轮数；也可展开“查看数值表”精确读取。这里展示模拟观察比例，不是理论条件概率。

## 常见问题

### 虚拟环境不存在或缺少pip

先确认位于主项目目录，而不是已删除的工作树。若首次创建环境提示缺少ensurepip，Debian/Ubuntu通常需安装与Python版本匹配的venv包；例如Python 3.12对应 `sudo apt install python3.12-venv`。安装后重新执行首次安装步骤，不要删除数据库。

### 端口已占用、网页打不开或API不可用

先尝试访问已有网页并检查两个终端日志。确认8000为本项目API、5173为本项目前端；Vite若自动改用其他端口，不要直接将它视为等价配置，先解决端口冲突。不要随意终止不明进程。只有前端运行时，登录和模拟仍不可用。

### 忘记管理员密码或账号被锁

本机受信任维护者可交互重置已有管理员密码：

```bash
.venv/bin/python manage.py reset_admin_password --username 你的管理员用户名
```

重置会撤销旧会话，并要求登录后改密。普通账号可由管理员在网页重置密码。

清除账号登录失败计数：

```bash
.venv/bin/python manage.py unlock_login --username 要解锁的用户名
```

这不会启用被禁用的账号，也不会清除来源限制。维护命令必须使用正确的数据路径，不能靠重新初始化或删除库找回账号。

### 登录后看不到原来的账号或历史

检查终端是否遗留 `LOTTERY_*` 路径变量，是否启动了临时目录中的另一套数据库。先核对路径，不要立即创建新管理员或清空数据。

## CLI：独立分析与模拟

CLI不需要网页登录，也不会自动写入网页历史；角色池来自配置文件，不是网页数据库中的池。

```bash
.venv/bin/python -m lottery_simulator analyze --format json
.venv/bin/python -m lottery_simulator simulate --pool-config configs/pools/default.json --draws 30 --trials 1000 --seed 42
.venv/bin/python -m lottery_simulator simulate --help
```

`--draws`为每轮新增主抽数，`--trials`为轮数，`--seed`为种子，`--trace`开启逐抽记录。`--format text`输出便于阅读的中文文本，`--format json`输出结构化JSON，不改变概率或模拟规则。输出和文件配置的完整选项以中文 `--help` 为准；`configs/pools/`、`configs/experiments/`提供示例。需要网页历史管理时，请从网页提交模拟。

## 数据路径与隔离

默认使用以下位置：

| 位置 | 用途 |
|---|---|
| `data/history_v5.sqlite3` | 账号、会话、角色池、实验配置、历史及Trace |
| `data/jobs_v5/` | 任务状态及暂存文件 |
| `data/exports_v5/` | 下载临时文件 |

仅在确实需要独立试验环境时设置以下变量：

```bash
export LOTTERY_DATA_DIR=/tmp/lottery-local
export LOTTERY_DB_PATH=/tmp/lottery-local/history_v5.sqlite3
export LOTTERY_JOBS_DIR=/tmp/lottery-local/jobs_v5
export LOTTERY_EXPORTS_DIR=/tmp/lottery-local/exports_v5
```

**切换路径就是使用另一套数据，不会自动带入原账号或历史。** 空库需在相同环境变量下执行迁移和初始化，再启动后端；worker继承后端环境。`/tmp`不是长期存储。返回主项目时应恢复预期路径并重启后端，不要将新代码指向旧版数据库。

## 本地备份与恢复

备份含密码哈希、会话和历史，必须私有保存，不得提交Git或公开下载。在线SQLite备份包含已提交数据，不包含任务/导出目录；重要备份应另存受控异机位置。

以下命令针对默认库；使用自定义路径时须替换为实际源库：

```bash
install -d -m 700 backups
.venv/bin/python scripts/backup_db.py data/history_v5.sqlite3 backups/lottery-v5-$(date +%F-%H%M%S).sqlite3
```

成功输出 `Backup integrity_check: ok`，退出码0，文件权限0600。每次使用新的备份文件名。

恢复会覆盖目标库。先停止接收新任务，等待或取消worker并确认退出，停止Web及定时备份；核对源和目标，再保留当前库副本。建议先在独立目录验证选定备份，不能直接把恢复当作排障试探。

```bash
.venv/bin/python scripts/backup_db.py data/history_v5.sqlite3 backups/pre-restore-v5-$(date +%F-%H%M%S).sqlite3
.venv/bin/python scripts/backup_db.py backups/lottery-v5-YYYY-MM-DD-HHMMSS.sqlite3 data/history_v5.sqlite3
.venv/bin/python -c "import sqlite3; c=sqlite3.connect('file:data/history_v5.sqlite3?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchall()); c.close()"
```

将示例备份名替换为实际文件，每一步成功后才继续；完整性结果应为 `[('ok',)]`。恢复后启动服务，确认登录、历史读取和小型模拟写入。恢复不会同步任务目录；若状态不一致，保留现场调查，不要递归删除数据目录。服务器定时备份和容器路径见[运维说明](deployment.md)。

## 验证范围与历史记录

本地功能和真实v5库切换已完成，证据见[实施记录](changes/2026-09-24-user-pool-experiment.md)及[浏览器验收](changes/2026-09-29-user-pool-browser-acceptance.md)。旧数据清理是已完成的历史操作，不是日常使用步骤。2026-09-30用户确认腾讯云服务器已使用手动指令部署；自动安装脚本尚未实机测试，已有隔离检查不能代替实机验收。服务器证据和未验事项统一见[部署验证状态](deployment.md#验证状态)。此前[v4恢复演练](changes/2026-09-23-backup-restore-drill.md)仅为历史参考。
