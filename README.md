# 抽奖模拟器

Python 3.11+ 的规则 1（版本 `2.0`）抽奖模拟器。命令行核心没有第三方依赖；网页仪表盘使用 Streamlit；公网部署接口使用 Docker/Caddy。

## 本地使用入口

本项目本地操作的唯一主目录是 `/home/qykj/202607/test/lottery_simulator`。请先进入该目录，再按[本地使用手册](docs/local-usage.md)创建或复用 `.venv`、启动网页、运行 CLI 和管理历史数据；已合并到 `master` 后不需要进入旧 worktree 路径。

界面各参数、三页面、四种结果视图、图表口径及历史操作，详见[网页页面详细说明](docs/dashboard-guide.md)。

## 默认奖池与保底

默认配置是 [configs/rule1_default.json](configs/rule1_default.json)：六星池有 9 名角色，其中 `UP-A` 是 1 名 UP，`限定-B`、`限定-C` 为其他限定；UP 合计占六星结果 50%，其余 8 名角色各占 6.25%。默认五星基础概率为 8%，五星保底开启且第 10 抽保证至少五星；六星仍使用原有动态保底，第 80 抽必出六星。

每次抽取只会落在四、五、六星之一：普通抽的五星概率保持配置值，四星吸收六星软保底带来的变化；到达五星保底位时先保留六星概率，剩余概率都归五星。五星重置五星保底但不重置六星保底，六星同时重置两者。

六星角色支持多个 UP 及各自权重；所有非 UP 角色平分余下的六星份额。每抽同时按星级结算全部奖励：默认奖励A为四/五/六星 `1/5/25`，奖励B为 `0/2/10`。角色、奖励和保底参数由同一个 JSON 配置校验。

## 命令行

精确查看当前配置和 80 行主池六星概率表：

```bash
.venv/bin/python -m lottery_simulator analyze --format json
```

用默认配置批量模拟：

```bash
.venv/bin/python -m lottery_simulator simulate --draws 100 --trials 100000 \
  --pool-config configs/rule1_default.json --seed 42
```

`--draws` 是每轮主池抽数。首次累计完成第 30 次主池抽取时，系统会以独立临时池赠送 10 抽；临时池沿用角色、UP、五星基础概率和奖励配置，但从独立双保底状态开始，固定六星概率 0.8%，五星保底强制为 10 抽。赠送不会推进或重置主池的任何保底，也不会递归触发赠送。

常用参数：

- `--pool-config PATH`：读取自定义 JSON；省略时加载默认配置。
- `--initial-pity N`：开始前主池连续未出六星次数，同时是已完成主池抽数；它决定首次 30 抽赠送是否已领取。
- `--initial-five-star-pity N`：开始前连续未出五星及以上次数；默认 0。五星保底关闭时只能为 0。
- `--trace`：按轮次输出每一抽的结构化记录；可与多轮 `--trials` 一起使用。
- `--format text|json`：JSON 包含 `pool_config`、`source_summaries`、`theoretical_source_summaries`、`source_distributions` 与 `at_least_one_rates`；Trace 时另有 `records`。

例如查看一次 30 主抽与赠送记录：

```bash
.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1 --seed 42 --trace
```

结果按 `main`（主池）、`bonus`（赠送）和 `total`（总计）分别给出四/五/六星、UP/其他限定/常驻、具体角色、奖励、五星/六星硬保底以及分布。`--format json --trace` 的每条记录使用嵌套的 `draw_result`（`outcome`、`probabilities`、`state_before`、`state_after`），另保留 `main_state_before`/`main_state_after`；每条记录还带 `trial_index`（轮次）和 `draw_index`（该轮总抽次），赠送抽也计入记录数。网页 Trace 将其展开为中文列。Trace 默认关闭；批量非 Trace 模式不保存逐抽记录。CLI Trace 会把记录保存在内存中，超大实验可能占用大量内存，完整多轮记录请优先使用网页落库或 `export-trace` 本地导出。

## 网页仪表盘与配置 JSON

本地开发（仅监听本机，并显式免登录；以下假设已有可用 `.venv`，首次安装请先按[本地使用手册](docs/local-usage.md)创建）：

```bash
cd /home/qykj/202607/test/lottery_simulator
.venv/bin/python -m pip install -r requirements.txt
APP_ENVIRONMENT=development APP_AUTH_MODE=disabled STREAMLIT_SERVER_ADDRESS=127.0.0.1 .venv/bin/python -m streamlit run dashboard/app.py --server.address=127.0.0.1
```

打开 `http://127.0.0.1:8501`。侧栏用于页面导航和任务状态；参数在“新建实验”主区域设置。“高级设置”可设初始五星保底；“奖池与奖励设置”可修改 UP 占比、五星保底、六星角色表与奖励表，恢复默认配置，导入 UTF-8 JSON，或下载当前已校验的 JSON。四、五星名单通过 JSON 编辑。开始摘要与“开始模拟”位于主区域；启动后自动进入“实验结果”，顶部“结果视图”切换四种视图。运行期间侧栏显示当前阶段和“停止模拟”。阶段进度只代表当前阶段的计数，主抽达到100%仍可能继续理论计算、Trace校验和保存。停止会取消尚未提交的任务且不能续算；若历史提交已经完成，停止操作会保留已完成历史。历史保存失败时，完整结果仍可在当前结果页查看，但不进入历史库。页面详情和操作流程见[网页页面详细说明](docs/dashboard-guide.md)；运行环境和数据目录见[本地使用手册](docs/local-usage.md)。后台任务和历史记录使用本次运行的配置快照，运行中继续编辑不会改变已启动任务；“复用参数”会把当次完整配置恢复到“新建实验”，不会自动运行。

网页固定为三个页面：“新建实验”“实验结果”“历史记录”。实验结果页有四种视图：“实验概览”“分类统计”“按抽次分析”“逐抽明细”；分类统计中可切换星级、六星构成、具体角色、奖励和保底，来源可选主池、赠送或总计。Trace 多轮记录在“按抽次分析”和“逐抽明细”中按轮次、轮内总抽次查看。开发默认历史库是 `data/history_v4.sqlite3`，任务状态在 `data/jobs_v4/`。默认逐抽上限为 1,000,000 条、单次网页明细下载上限为 10,000 条，分别可用 `LOTTERY_MAX_TRACE_RECORDS`、`LOTTERY_MAX_TRACE_DOWNLOAD_RECORDS` 覆盖；改动环境变量后必须重启网页进程才会读取。可用 `LOTTERY_DATA_DIR` 更改数据目录，或用 `LOTTERY_DB_PATH` 单独覆盖数据库路径。

旧 `data/history.sqlite3` 不读取、不迁移、不覆盖，也不自动删除；如需保留，请自行备份。显式把 `LOTTERY_DB_PATH` 指向旧 schema 时，程序会安全拒绝而不会改写旧库。固定种子、完整配置快照、相同参数、相同 `rule_version`（规则版本）、相同 `sampling_version` 和 Python 实现/版本才构成可复现实验条件。

## 公网部署

Linux 公网部署先按 [部署与运维手册](docs/deployment.md) 配置 DNS、`.env` 中的 `DOMAIN`/`ALLOWED_EMAILS` 和私密 `.streamlit/secrets.toml`，再运行：

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app caddy
```

Compose 固定 production/OIDC；仅 Caddy 发布 80/443，并声明 HSTS。页面、worker 和每日备份统一使用 `LOTTERY_DB_PATH=/app/data/lottery_v4.sqlite3`，任务目录为 `/app/data/jobs_v4/`，备份文件使用 `lottery-v4-` 前缀。备份只包含已提交的 v4 历史数据库，不包含 jobs_v4 暂存任务、secrets 或证书；保存失败时保留的完整暂存 Trace 也不在历史备份中。恢复只接受 v4 数据库，旧库不迁移、不删除。数据、备份和证书在命名卷中，secrets 只读挂载；不要执行 `docker compose down -v` 或宽泛删除 `data/`、`jobs/`。

✅ 多轮 Trace 与界面重组已本地合并到 `master`；合并后的主目录全套 385 项测试通过。⚠️ 尚未在线推送，也未执行真实浏览器视觉验收、服务器部署、百万记录容量验收或旧数据切换清理。完整操作与边界见[部署与运维手册](docs/deployment.md)、[多轮 Trace 实施记录](docs/changes/2026-09-20-multi-trial-trace-ui.md)及[最新本地合并记录](docs/changes/2026-09-22-multi-trial-trace-ui-local-merge.md)。

## 测试

```bash
python3 -m unittest discover -v
```
