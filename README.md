# 抽奖模拟器

Python 3.11+ 的规则 1（版本 `2.0`）抽奖模拟器。命令行核心没有第三方依赖；网页仪表盘使用 Streamlit；公网部署接口使用 Docker/Caddy。

## 本地使用入口

本项目本地操作的唯一主目录是 `/home/qykj/202607/test/lottery_simulator`。请先进入该目录，再按[本地使用手册](docs/local-usage.md)创建或复用 `.venv`、启动网页、运行 CLI 和管理历史数据；已合并到 `master` 后不需要进入旧 worktree 路径。

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
- `--trace`：仅限 `--trials 1`，输出每一抽的结构化记录。
- `--format text|json`：JSON 包含 `pool_config`、`source_summaries`、`theoretical_source_summaries`、`source_distributions` 与 `at_least_one_rates`；Trace 时另有 `records`。

例如查看一次 30 主抽与赠送记录：

```bash
.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1 --seed 42 --trace
```

结果按 `main`（主池）、`bonus`（赠送）和 `total`（总计）分别给出四/五/六星、UP/其他限定/常驻、具体角色、奖励、五星/六星硬保底以及分布。`--format json --trace` 的每条记录包含来源、主池累计抽数、星级、具体角色、UP/限定标记、奖励、概率和抽取前后的双保底状态；网页 Trace 直接展示该结构化记录。终端文字 Trace 保留原来源、序号、累计、保底位置、六星概率、是否六星和主池六星状态，并追加星级、角色、按星级奖励、4/5/6 星概率、主池抽后双保底、来源池抽前/后双保底及两个保底触发标记。批量非 Trace 模式不保存逐抽记录。

## 网页仪表盘与配置 JSON

本地开发（仅监听本机，并显式免登录；以下假设已有可用 `.venv`，首次安装请先按[本地使用手册](docs/local-usage.md)创建）：

```bash
cd /home/qykj/202607/test/lottery_simulator
.venv/bin/python -m pip install -r requirements.txt
APP_ENVIRONMENT=development APP_AUTH_MODE=disabled STREAMLIT_SERVER_ADDRESS=127.0.0.1 .venv/bin/python -m streamlit run dashboard/app.py --server.address=127.0.0.1
```

打开 `http://127.0.0.1:8501`。侧栏的“高级设置”可设初始五星保底；“奖池与奖励设置”可修改 UP 占比、五星保底、角色表与奖励表，恢复默认配置，导入 UTF-8 JSON，或下载当前已校验的 JSON。后台任务和历史记录保存的是不可变配置快照，运行中继续编辑不会改变已启动任务；历史“复用参数”会恢复当次完整配置。

结果页提供“总览、六星构成、具体角色、附赠奖励、保底统计、Trace”六个区域，并可在主池、赠送、总计之间切换；每个图表都有可展开的数值表和 JSON 结果下载。开发默认历史库是 `data/history_v2.sqlite3`，任务状态在 `data/jobs/`。可用 `LOTTERY_DATA_DIR` 更改数据目录，或用 `LOTTERY_DB_PATH` 单独覆盖数据库路径。

旧 `data/history.sqlite3` 不读取、不迁移、不覆盖，也不自动删除；如需保留，请自行备份。显式把 `LOTTERY_DB_PATH` 指向旧 schema 时，程序会安全拒绝而不会改写旧库。

## 公网部署

Linux 公网部署先按 [部署与运维手册](docs/deployment.md) 配置 DNS、`.env` 中的 `DOMAIN`/`ALLOWED_EMAILS` 和私密 `.streamlit/secrets.toml`，再运行：

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app caddy
```

Compose 固定 production/OIDC；仅 Caddy 发布 80/443，并声明 HSTS。页面、worker 和每日备份统一使用 `LOTTERY_DB_PATH=/app/data/lottery_v2.sqlite3`。旧 `/app/data/lottery.sqlite3` 不迁移、不删除。数据、备份和证书在命名卷中，secrets 只读挂载；不要执行 `docker compose down -v`。

✅ 本地功能和部署静态合同已验证。⚠️ Docker/Caddy 实际运行、卷权限、自动证书、真实公网 HTTPS/HSTS 与 OIDC 仍是服务器现场未验，不能由本地测试替代。完整操作与边界见[部署与运维手册](docs/deployment.md)及[本次变更记录](docs/changes/2026-09-14-rule1-expanded-outcomes.md)。

## 测试

```bash
python3 -m unittest discover -v
```
