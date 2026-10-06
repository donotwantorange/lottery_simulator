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

## 任务17本机启动入口（2026-10-02，真实账号验收已完成）

实现已合并本地master，主检出v6库已保留本机原管理员并初始化默认资源。本次切换使用入口 http://127.0.0.1:18080/ （不表示服务始终在线） ，使用原账号密码登录；新版history_v6/jobs_v6/exports_v6路径均在主检出data。前端静态资源与CSRF实际200，用户已确认原账号10抽1轮Trace成功；历史和Trace访问已核对。源history_v5仍保留，私有备份位于WSL `/home/lottery/lottery-backups/cutover-20261002-1010/`。原本地使用手册未改，未推送或升级服务器。

临时前端启动器及PID在 `data/local-v6-runtime/`，后端PID和日志在WSL `/home/lottery/lottery-runtime-v6/`。均为本机运行文件，不提交Git。WSL关闭或地址变化后需重新核对启动，当前地址172.26.88.182。回滚边界见实施记录任务17进度。


## 2026-10-02完整回归及WSL运行注意事项

最近理论阶段进度和取消文件检查修复已提交`9832bc0`。本轮隔离后端244项、前端52项及构建通过；8组240/480抽、10轮、Trace开关、Linux/Windows目录任务全部完成，数值一致。480抽10轮Trace在Windows目录66.486秒、Linux临时目录55.498秒，均为单次测量。

Windows挂载目录的状态文件更新过程中实测偶发FileNotFoundError/OSError(61)；当前代码会误报404，而页面对404停止轮询。此问题尚未修复。另有超长参数异常、轮询旧错误残留、保存/提交显示回跳及可信代理共享来源限流风险，详见[实施记录最新测试节](changes/2026-09-30-independent-rules-rarities.md#2026-10-02最近修改完整测试与待处理问题)。不要据此把无更新页面直接当作worker已停止。

测试证据在 `D:\Web_project\lottery-tests-20261002`；本轮8001后端、18081代理和测试标签页已关闭，Linux临时数据已清理。真实v6路径与账号不是本轮临时账号/数据。启动或恢复实际页面需先核对WSL地址、监听、PID和日志；本页保存的地址是当次测量值，不能保证重启后有效。原本地使用手册不改，未推送或升级服务器。

## 2026-10-02补齐Docker环境

用户明确授权后，在WSL Ubuntu-24.04中通过[Docker官方APT源](https://docs.docker.com/engine/install/ubuntu/)安装Docker Engine 29.8.2、containerd 2.3.6、Compose 5.5.1及Buildx 0.37.1；docker/containerd服务已启用。没有安装Windows Docker Desktop，没有修改Windows代理、防火墙或WSL网络模式，也没有将普通用户加入docker组。

从PowerShell调用：

```powershell
wsl -d Ubuntu-24.04 -u root -- docker version
wsl -d Ubuntu-24.04 -u root -- docker compose version
wsl -d Ubuntu-24.04 -u root -- docker run --rm --pull=never caddy:2.11.4-alpine caddy version
```

Docker在WSL内，Windows本身不新增docker命令。Caddy使用项目指定的容器镜像，不需要另装WSL内的独立caddy程序。实际hello-world运行、Caddy 2.11.4运行及项目Caddyfile校验均通过；原手册、真实数据库、账号和.env未改，修复源码仍保留于隔离工作树，未合并或部署。

本机网络仍限制WSL直连Docker Hub。Windows已有代理127.0.0.1:7897可访问官方仓库，但仅绑定Windows回环地址，WSL NAT无法直接使用。本轮通过该现有代理下载官方linux/amd64镜像，校验manifest/config/layer SHA-256及解压后的layer diff ID，再导入Docker。Windows原生curl保持系统TLS校验；没有关闭证书校验、配置非官方镜像源或改变系统证书信任。当时已备齐Python基础镜像及项目既有依赖wheel用于离线构建；wheel随后已按用户要求清理，当前不能直接复用该离线构建材料。

本轮原临时目录`D:\Web_project\lottery-environment-20261002`已按用户要求整体删除，下载档案、wheel、脚本、日志和临时证书不再保留；安装及验证结果摘要见[实施记录](changes/2026-10-02-v6-runtime-reliability-fixes.md)。后续直接pull仍需可达的WSL网络/代理，不能将本轮离线导入当作直连成功。测试容器、网络、卷、验收镜像和构建缓存均已清除，仅保留Docker服务与官方Caddy/Python运行镜像；重新验收需重新准备独立配置和证书。

真实容器验收另发现先启动的app会占用原Caddy固定地址`.2`。隔离工作树已为backend设置独立动态范围`LOTTERY_PROXY_DYNAMIC_RANGE`（默认172.30.96.128/25），与Caddy地址分开，新增范围、显式网关（LOTTERY_PROXY_GATEWAY，默认172.30.96.1）及内置null网络处理，部署/安装30项定向回归通过。自定义子网时需同步调整范围、固定地址与网关。本地HTTPS/来源桶分离/重建已实测通过，但可信公网HTTPS证书验证失败，任务11仍有网络验证缺口；详细证据见新一轮实施记录。

## 2026-10-06修复交付状态

新一轮修复任务1—10、12、13完成，任务11本地代理拓扑/临时证书HTTPS通过，可信公网HTTPS仍待补。产品修复在 `D:\Web_project\lottery_simulator\.worktrees\v6-reliability-fixes`（WSL路径 `/mnt/d/Web_project/lottery_simulator/.worktrees/v6-reliability-fixes`），主目录master仍为 `9832bc0`，没有提交、合并或实际服务切换。前文“问题尚未修复”描述主目录基准代码；隔离工作树已修复并验收，不表示当前主目录运行服务已使用修复。

当前Git主操作使用Windows Git，修复树使用命令级 `-c core.autocrlf=input`；不要套用旧工作树的Git指针说明。业务测试证据保留于 `D:\Web_project\lottery-repair-tests-20261002`，本次文档差异检查在其 `task13-20261006` 子目录。安装/拓扑临时材料已清理，重新验收需准备新配置、依赖与证书。后续本地集成/部署另行核对目标，原本地使用手册保持不变。详见[最终交付记录](changes/2026-10-02-v6-runtime-reliability-fixes.md#2026-10-06任务13文档与最终交付完成)。

## 2026-10-06已完成本地集成与当前入口

用户授权继续后，修复353cab0已合并到master（ca545d6），主目录前端已构建并切换本机服务。使用 http://127.0.0.1:18080/ ，原账号由用户亲自登录，连续10抽1轮和480抽10轮Trace均完成；第二项4920事件，取消测试也通过。前文未合并/未切换描述历史阶段；最新Git与验收见[本地集成记录](changes/2026-10-02-v6-runtime-reliability-fixes.md#2026-10-06授权本地集成备份与原账号验收)。

本轮私有备份在WSL `/home/lottery/lottery-backups/local-repair-20261006`，不在Git或网站目录。验收保留两条新增完整历史，原账号/资源/旧历史均保持。后端PID为626，Windows前端PID为22296，仅为当次观察值；PID文件/本轮日志沿用上文运行目录。服务保留运行，关闭WSL或地址变化后需核对再启动，不盲停进程。当前WSL地址172.26.88.182，原忽略路径server.cjs仍指向该地址。Windows的Shell检出可为CRLF，当前install.sh保持物理LF且语法通过，未改Git全局配置。

本轮未推送、未部署服务器，任务11可信公网HTTPS仍待补。部署/恢复前核对目标与活动任务；不要直接覆盖当前v6库或删除验收历史。原本地使用手册保持不变。

## 2026-10-06服务器升级脚本

完整新版项目提供 `bash scripts/install.sh --upgrade`，仅用于已有健康的标准Docker Compose app/Caddy部署，支持v5账号保留及v6更新。当前本机18080/8000由Node和WSL runserver运行，并非该Compose部署，不使用这个入口切换本机服务。没有安装Windows Docker Desktop或更改本机网络；本轮仅编写与隔离验证，真实账号库、运行服务及原本地使用手册保持不变。服务器维护、备份、重建网络、业务验收及备份unit更新见[部署说明](deployment.md#脚本升级)和[升级记录](changes/2026-10-06-compose-upgrade.md)。

2026-10-06后续统一入口：无参数 `bash scripts/install.sh`显示安装、卸载、运维、更新菜单，原直接安装改用 `--install`，直接升级保留 `--upgrade`；新增保留v6卷重装 `--restore`。卸载可保留数据或二次确认永久删除经核对的服务器项目卷、私有备份及.env；代码、Docker和外部备份不删除。这些菜单不用于本机18080/8000开发服务，本轮未执行真实卸载、升级或安装定时备份。见[菜单说明](deployment.md#统一管理菜单)。
