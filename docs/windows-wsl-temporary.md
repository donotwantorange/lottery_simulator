# Windows＋WSL临时开发说明

日期：2026-10-01。本文件仅记录当前电脑续接开发所需的环境与命令；仓库原有README和[本地使用手册](local-usage.md)保持原文。页面功能和服务器运维仍以原有文档为准。

项目来源：[donotwantorange/lottery_simulator](https://github.com/donotwantorange/lottery_simulator)，与本地`origin`地址一致。审查开始时本地master及保存的origin/master均为`a0b575f`；没有fetch，不以本地引用判断GitHub当前最新提交。设计与计划的本次整理尚未提交，审查阶段任务1—17未开始；当前准备进度见末节。

## 本机环境

| 项目 | 2026-10-01实际核对结果 |
|---|---|
| Windows源码 | `D:\Web_project\lottery_simulator` |
| WSL源码 | `/mnt/d/Web_project/lottery_simulator`，与Windows是同一份文件 |
| Linux环境 | `Ubuntu-24.04`，运行用户`lottery` |
| Python | `/home/lottery/.venvs/lottery-simulator/bin/python`，3.12.3 |
| 后端依赖 | Django 5.2.17、DRF 3.18.1、Altair 6.2.2、Gunicorn 26.2.0 |
| Node/npm | `/usr/local/bin/node` 22.23.3、`/usr/local/bin/npm` 10.9.9 |
| 前端依赖 | `frontend/node_modules`链接到`/home/lottery/frontend-deps/node_modules` |
| 当前数据 | `data/history_v5.sqlite3`、`data/jobs_v5/`、`data/exports_v5/`，相对于上述源码目录 |

后端、worker和Linux专用检查使用WSL解释器；Windows目录内的`.venv`是另一套环境。本机已经安装依赖并初始化v5库，无需重跑首次安装、migrate或init_admin。

## 日常启动与停止

8000和5173在审查时已有服务监听。已有本项目服务时直接访问[本地网页](http://127.0.0.1:5173)，不要重复启动或终止不明进程。

需要启动时，在两个PowerShell终端分别执行：

后端：

```powershell
wsl -d Ubuntu-24.04 -u lottery --cd /mnt/d/Web_project/lottery_simulator --exec /home/lottery/.venvs/lottery-simulator/bin/python manage.py runserver 127.0.0.1:8000
```

前端：

```powershell
wsl -d Ubuntu-24.04 -u lottery --cd /mnt/d/Web_project/lottery_simulator --exec /usr/local/bin/npm --prefix frontend run dev -- --strictPort
```

完整停机前在网页等待或取消模拟并确认worker退出，再在自己启动的服务终端按Ctrl+C。关闭网页、退出登录或停止Web不会自动取消独立worker。

## Linux终端、CLI与实施验收

在PowerShell进入WSL：

```powershell
wsl -d Ubuntu-24.04 -u lottery
```

在WSL设置本机目录和解释器，然后使用CLI：

```bash
cd /mnt/d/Web_project/lottery_simulator
export LOTTERY_PYTHON=/home/lottery/.venvs/lottery-simulator/bin/python
"$LOTTERY_PYTHON" -m lottery_simulator simulate --help
```

原手册中Linux `.venv/bin/python`命令在本机使用`"$LOTTERY_PYTHON"`前缀；npm使用`/usr/local/bin/npm`。前端依赖更新在Linux目录`/home/lottery/frontend-deps/`按对应锁文件安装，再复用node_modules链接；不要把依赖目录提交Git。

新版实施在任务1记录的隔离工作树进行，进入它的WSL路径并设置`LOTTERY_WORKTREE`；复用上面的Linux解释器。任务16的独立v6验收目录和数据变量仍以[实施计划](changes/2026-09-30-independent-rules-rarities-plan.md)为准，当前真实v5库不作为新版中间阶段测试库。

## Git与换行

当前共享检出由Windows Git生成CRLF。Windows的`core.autocrlf=true`，WSL未启用该配置，因此WSL原始Git曾把184个文件显示为纯换行修改。主检出的Git操作统一使用Windows Git；WSL只读查看可使用命令级配置：

```bash
git -c core.autocrlf=true status --short
git -c core.autocrlf=true diff
```

该配置用于正确比较，不转换工作区文件。不要把换行差异当作产品改动，也不要批量重写主检出或修改Git全局配置。

当前`install.sh`的CRLF导致WSL `bash -n scripts/install.sh`退出2。Linux实施与Shell验收需先准备LF隔离工作树；创建时可使用命令级`core.autocrlf=input`，实际目录/分支按任务1核对。该脚本用于服务器首次安装，当前本机无需执行它。

## 数据与验证边界

本机v5库已应用`0001_initial`，有1个账号、1个池，实验配置/历史/逐抽均0；有1个可用管理员，无删除中账号、删除清单或任务状态文件。旧Ubuntu电脑的数据不会随Git自动迁入；需要保留旧账号或历史时先明确备份来源，不能把本机库当作完整旧数据集合。

CSRF入口及前端首页在审查时均返回HTTP 200。本次只核对环境、路径、数量摘要、入口响应、Bash语法及内存SQLite示例，未执行实际登录、模拟、取消、Trace下载或备份恢复验收，也未执行安装、启停服务或迁移真实数据。原Ubuntu验收记录保留原时点。


## 2026-10-01执行准备结果

已在基准提交`a0b575f`创建独立的detached HEAD工作树，主分支保持不变。已复制最新设计、计划、台账及本临时说明，均使用LF；未提交文档仍保留在主工作区。

- Windows目录：`D:\Web_project\lottery_simulator\.worktrees\independent-rules-v6`。
- WSL目录：`/mnt/d/Web_project/lottery_simulator/.worktrees/independent-rules-v6`。
- 隔离工作树的Git在WSL执行；Windows只读查看时使用命令级`core.autocrlf=input`，不沿用主检出的CRLF策略。
- Python复用本机Linux环境；前端node_modules链接到已有Linux依赖目录，14项前端依赖版本与package.json一致，无重新安装。
- `pip check`通过；Linux的fcntl可导入；隔离工作树`install.sh`为LF，`bash -n`通过。
- 未复制data目录，未运行产品测试、迁移或初始化数据库，未启动/停止服务，未提交或推送。

进入实施工作树时在WSL设置：

```bash
export LOTTERY_WORKTREE=/mnt/d/Web_project/lottery_simulator/.worktrees/independent-rules-v6
export LOTTERY_PYTHON=/home/lottery/.venvs/lottery-simulator/bin/python
cd "$LOTTERY_WORKTREE"
```

2026-10-01：该工作树中任务1—5的配置类型、默认文件、通用内核、模拟事件、理论与CLI及对应测试已实现，语法/默认加载/初始状态与JSON往返检查通过；集中验收留任务16。进度见[实施记录](changes/2026-09-30-independent-rules-rarities.md)，后续从任务6继续推进；任务内可按用户授权拆分子代理。真实v5账号库及服务器仍保持现状。


2026-10-01任务4/5续接：工作树已提供新格式analyze/simulate入口；语法/导入及参数解析已检查，理论/等待/完整模拟的功能验收留任务16。使用上面的WSL工作树和解释器；不要在真实v5目录启动新版服务。export-trace准备了v6筛选参数，流式实现须等任务9。本段只记录实施进度，不改原本地使用手册。


2026-10-01任务6—8续接：隔离工作树已实现v6模型/迁移、默认初始化、规则/池/实验及初始条件服务；语法、模块导入与无数据库的迁移状态检查通过。功能验收留任务16，后续从任务9继续；新API/worker等任务10连通前不启动新服务，不让新代码读取真实v5库。原本地使用手册不变。


2026-10-01任务9/10续接：隔离工作树已实现通用事件Trace、历史/导出、任务快照、worker与后端API契约，语法/导入/路由及迁移内存状态检查通过，未运行功能验收。下一步任务11；旧前端尚未升级，集中隔离库验收仍在任务16。不要把新代码连接真实v5库，也不据此切换已有服务；原本地使用手册不改。

2026-10-01任务11续接：共享动态类型及独立规则页面已实现，WSL TypeScript静态检查通过；功能测试仍留任务16。下一步任务12角色池页面，旧池/实验/结果页面暂待迁移，不能据此切换服务或真实数据库。规则导入确认保留原始JSON，导出使用原生下载；浏览器无法精确表示的规则整数不允许网页保存。

2026-10-01任务12—14续接：动态池编辑、实验初始条件及只读预览、结果/历史/过程明细与动态图表已实现，TypeScript和Python静态检查通过，未做功能验收或启动新服务。下一步任务15账号转移及部署接口；集中验收仍在任务16，真实切换另属任务17。原本地使用手册不改，真实v5库保持原状。


## v5账号保留与v6切换顺序（任务15工具，尚未演练）

以下步骤供任务16隔离演练及任务17授权后使用，当前不执行真实切换。先明确旧Ubuntu备份或本机v5库是哪一份账号来源，并停止受控服务及任务、完成私有备份。备份包含密码散列、账号、会话、规则与其他私有数据，须限制访问；数据库备份不会自动恢复旧任务目录。

1. 保留v5源库作为只读来源，不复制到v6路径，也不让新版migrate处理它。
2. 为独立空目标显式配置 `LOTTERY_DB_PATH`、`LOTTERY_JOBS_DIR`、`LOTTERY_EXPORTS_DIR` 为v6路径；使用本页WSL解释器运行 `manage.py migrate`，完成完整迁移链。
3. 运行 `manage.py import_v5_accounts --source /明确的绝对路径/history_v5.sqlite3`。目标使用当前Django设置；已有账号或业务、未完成删除、异常迁移状态会停止。只迁完整账号标量与LoginLimit，旧会话不迁入，auth_version递增，用户需用原密码重新登录。
4. 运行 `manage.py init_business_defaults`。保留账号后不要运行 `init_admin`；它只供全新安装创建首个管理员。
5. 核对目标账号、默认规则/池及备份恢复，再配置配套新版代码与前端、v6库/jobs/exports路径，完成最终切换和登录验收。失败保持旧来源与备份，按原配置回滚，不让旧代码打开v6。

安装脚本只处理全新安装。发现v5、已有库或升级迹象时按中文提示停止，不能用新建账号绕过保留流程。服务器使用 `/app/data/history_v6.sqlite3`、`jobs_v6`、`exports_v6`，备份前缀为 `lottery-v6-`；无服务器部署或真实账号迁移记录。


## 任务16验收完成（2026-10-01）

隔离工作树后端全套242项、前端52项与构建通过；账号UTC完整标量5项和阈值夹具1项后续回归通过。浏览器实际验证规则/池/初始条件、30×2=80、240赠送、图表、JSON/JSONL、历史重跑及取消，并加载最终dist哈希资源。完整证据见[实施记录](changes/2026-09-30-independent-rules-rarities.md)，本机归档 `D:\Web_project\lottery-v6-acceptance-taNdVb`。

本轮临时数据为 `/tmp/lottery-v6-acceptance.taNdVb` 的history_v6/jobs_v6/exports_v6；各源/目标及备份探针另用自己的临时库。此路径不是任务17真实账号来源。原使用手册、真实v5和服务器保持原状，未提交/合并。

Windows保留端口范围包含5173，本轮使用WSL虚拟网卡绑定和127.0.0.1:18080临时代理，保持localhost安全上下文；未修改系统网络配置，原Vite配置未改。已停止本轮所有临时服务，不再使用上述浏览器地址。后续启动先只读核对监听和保留端口，不能盲停服务。工作树Git指针已改相对路径，Windows/WSL均可识别；Shell保持LF。

下一步任务17：先明确选用本机v5库还是旧Ubuntu备份作为真实账号来源，再进行经授权的本地集成与切换。不得把本轮临时账号/库迁入正式环境。
