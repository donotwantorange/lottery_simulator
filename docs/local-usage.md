# 本地使用手册

本文只覆盖本机开发和使用。服务器 Docker/Caddy/OIDC、域名、证书和公网验收请看[部署与运维手册](deployment.md)，两套流程不要混用。

想逐项了解三页面、四种结果视图、图表和历史记录，请看[网页页面详细说明](dashboard-guide.md)。本文负责安装、启动及数据管理；页面说明负责界面操作和统计口径。

## 1. 唯一主目录与虚拟环境

本项目本地使用的唯一入口是：

```bash
cd /home/qykj/202607/test/lottery_simulator
```

所有下面的相对路径都以这个目录为当前目录。这里已经合并到 `master`，不需要进入旧 worktree；旧 worktree 中的 `data/` 也不会自动搬过来。

先确认 Python 版本和环境：

```bash
python3 --version
.venv/bin/python --version
```

已有可用 `.venv` 时直接复用。首次安装或环境不完整时执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

如果 Debian/Ubuntu 报 `ensurepip` 缺失，先看 `python3 --version` 的实际版本，再安装匹配的 venv 包。例如实际是 3.12 才使用：

```bash
sudo apt install python3.12-venv
python3 -m venv .venv
```

实际版本不是 3.12 时，把包名中的版本替换为实际版本。不要盲目删除已有 `.venv`；先确认其中没有要保留的环境或依赖，确有损坏再由用户决定备份、移走或重建。本文命令只供用户执行，本次文档更新不安装软件、不重建环境。

## 2. 启动本地网页

在主目录执行以下命令。它显式使用开发环境和免登录模式，只监听回环地址：

```bash
APP_ENVIRONMENT=development APP_AUTH_MODE=disabled STREAMLIT_SERVER_ADDRESS=127.0.0.1 .venv/bin/python -m streamlit run dashboard/app.py --server.address=127.0.0.1
```

浏览器打开 `http://127.0.0.1:8501`。按 `Ctrl+C` 停止；再次执行启动命令即可重启，浏览器刷新后读取新页面。不要为了本地免登录把地址改成公网地址，也不要把 8501 对公网开放。

侧栏参数含义和网页校验如下：

- `规则`：当前可选 `rule1`。
- `主池抽数`：每轮主池抽多少次；必须为正整数，网页上限为 10,000,000。
- `实验轮数`：重复多少轮；网页上限为 1,000,000，且 `主池抽数 × 实验轮数` 不得超过 100,000,000。
- `假设主池已累计多少抽仍未出6星`：同时初始化六星连续未出状态和已完成的主池抽数，范围 0–79；它还决定首次 30 主抽赠送是否已领取。
- `随机种子（留空自动生成）`：留空自动生成；填写整数可复现同配置、同规则版本的结果。
- `Trace`：保存逐抽记录，支持多轮；每条记录包含轮次和轮内总抽次，赠送抽也计入总记录数。网页总实际记录上限默认 1,000,000，单次明细下载默认 10,000。
- `高级设置` 中的 `假设主池已连续多少抽未出5星及以上`：五星保底开启时范围为 0 到硬保底减 1；关闭时只能是 0。

运行中会显示进度和“停止模拟”。停止、服务重启或任务失败造成的不完整结果不会保存为历史；只有完成的运行才进入历史库。

建议先做小模拟，确认页面和数据目录正常，再扩大规模：

```bash
.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1000 --seed 42
```

网页中相同含义的是主池抽数 30、实验轮数 1000、随机种子 42。CLI 的参数校验和网页的 `RunParameters` 校验不是同一层；不要把 CLI 能接受的范围当成网页上限，也不要声称两者限制完全相同。

## 3. 奖池、奖励和 JSON

展开侧栏“奖池与奖励设置”可编辑并增删角色和奖励，也可“恢复默认配置”、导入 UTF-8 JSON 或“导出配置 JSON”。网页编辑器的真实列名是：

- 角色：`角色名称`、`是否UP`、`是否限定`、`UP权重`。
- 奖励：`奖励名称`、`四星`、`五星`、`六星`。

编辑表格单元格后按 `Enter` 确认；必要时刷新页面再观察当前值。无效配置会在网页显示中文提示，修正后才能开始模拟。

`up_share` 必须大于 0 且不超过 1，不是百分数：`0.5` 表示六星结果中 UP 合计 50%。至少要有一个 UP；UP 必须同时是限定角色，且 `is_up: true` 时 `up_weight` 必须是有限、严格为正的数，支持小数。非 UP 角色在剩余份额内等概率；网页中非 UP 的 `UP权重` 可留空，导出的 JSON 应为 `null`。`up_share < 1` 时必须存在非 UP 角色；全部角色均为 UP 时只能设为 1。角色名和奖励名必须非空且各自唯一，各星级奖励值必须有限且非负；可以删除全部奖励。

多个 UP 按权重归一化。例如权重 1 和 3、`up_share: 0.5` 时，两名 UP 在全部六星中的占比分别是 12.5% 和 37.5%；非 UP 角色平分剩余 50%。`up_share` 是概率值，不能填写 `50` 表示 50%。

下面是可直接复制的完整小配置（配置格式 `1`；四星名单权重 `1:3`，五星名单仅 1 人；六星含 1 个 UP 和 2 个非 UP）。它包含 `PoolConfig.from_dict` 所需的全部字段：

```json
{
  "format_version": 1,
  "up_share": 0.5,
  "five_star": {
    "base_probability": 0.08,
    "pity_enabled": true,
    "hard_pity": 10
  },
  "six_star_characters": [
    {"name": "UP角色", "is_up": true, "is_limited": true, "up_weight": 1},
    {"name": "限定角色", "is_up": false, "is_limited": true, "up_weight": null},
    {"name": "常驻角色", "is_up": false, "is_limited": false, "up_weight": null}
  ],
  "four_star_characters": [
    {"name": "四星角色A", "weight": 1},
    {"name": "四星角色B", "weight": 3}
  ],
  "five_star_characters": [
    {"name": "五星角色", "weight": 1}
  ],
  "rewards": [
    {"name": "奖励A", "four_star": 1, "five_star": 5, "six_star": 25},
    {"name": "奖励B", "four_star": 0, "five_star": 2, "six_star": 10}
  ]
}
```

用文本编辑器修改 JSON 后，先用下面的绝对解释器验证格式和名单，再运行模拟；不要把模拟 JSON 输出重定向回同一个配置文件。建议复制默认文件到新文件后修改，不要直接改默认配置。以下复制命令仅在 `configs/my-pool.json` 不存在时使用，已有文件应另选名字，避免覆盖：

```bash
cp configs/rule1_default.json configs/my-pool.json
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -c 'import json; from lottery_simulator.rules.pool_config import PoolConfig; PoolConfig.from_dict(json.load(open("configs/my-pool.json", encoding="utf-8")))'
.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1000 --seed 42 --pool-config configs/my-pool.json
```

主池和由它派生的赠送池都会做配置合法性校验。五星开关只控制主池；赠送池固定为六星概率 0.8%、五星硬保底 10 抽，并使用角色、奖励和五星基础概率。所有可达到的普通抽（未触发五星或六星硬保底）都必须满足五星基础概率与六星概率之和不超过 1；强制保底抽使用保底分配规则，由程序统一校验，不要手动截断概率。

## 4. 保底与首次赠送的边界

六星主池保底状态是 0–79 个连续未出六星，抽到第 80 抽必出六星。概率曲线的关键点是：第 65 抽仍为 0.8%，第 66 抽为 5.8%，第 79 抽为 70.8%，第 80 抽为 100%。五星初始进度同样从 0 开始，五星保底开启时必须小于配置的 `hard_pity`；关闭五星保底只能为 0。

`initial_pity` 同时代表“连续未出六星抽数”和“已经完成的主池抽数”：

- 初始值 0–79 均可用。
- 初始累计主抽数至少为 30 时，首次 30 抽赠送已领，不会再发。
- 初始为 29 时，再完成 1 次主池抽即可到 30，并触发 10 抽赠送。
- 每轮最多触发这一次首次赠送；赠送池从独立 `(0, 0)` 双保底状态开始，固定六星率 0.8%，不会推进或重置主池，也不会递归触发赠送。

## 5. CLI、输出格式与结果解读

命令行统一使用 `.venv/bin/python`：

```bash
# 分析 80 抽主池概率曲线
.venv/bin/python -m lottery_simulator analyze --format text

# JSON 分析结果（另选输出文件名）
.venv/bin/python -m lottery_simulator analyze --format json > analysis.json

# 批量模拟、固定种子、指定自定义奖池
.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1000 --seed 42 --pool-config configs/my-pool.json

# 多轮逐抽 Trace（赠送抽也计入每轮记录数）
.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 3 --seed 42 --trace

# 从历史主抽29/五星进度9开始，完成1主抽后触发送10抽
.venv/bin/python -m lottery_simulator simulate --draws 1 --trials 1 \
  --initial-pity 29 --initial-five-star-pity 9 --seed 42 --trace --format json

# 将批量结果保存为文件（同名文件会被覆盖）
.venv/bin/python -m lottery_simulator simulate --draws 30 --trials 1000 \
  --seed 42 --format json > simulation.json
```

`simulate` 的 `--draws` 必填；`--trials` 默认 1，`--seed` 省略时自动生成，两个初始保底参数默认 0。`--pool-config` 省略时加载默认文件，`--rule` 当前只能为 `rule1`。可用 `.venv/bin/python -m lottery_simulator simulate --help` 查看全部选项。

`--format text|json` 只改变输出形式，不改变概率或随机过程，默认 `text`。使用 `>` 重定向 JSON 前要确认目标文件名；Shell 会先覆盖目标，尤其不要把 `--pool-config my-pool.json > my-pool.json` 写成同名，否则配置会先被清空。

`--trace` 默认关闭且可用于多轮。CLI 不会自动写网页历史库；CLI Trace 将全部记录保存在内存中，大规模多轮实验可能占用大量内存。完整记录可将网页 Trace 保存后用 `export-trace` 本地导出；CLI 和网页分别遵守各自边界。CLI 的非 Trace JSON 不含 `records`。固定随机种子、相同规则/配置/参数、相同 `sampling_version`、Python 实现及版本才是可复现条件；改动任一项都不要把输出当作同一实验。

对已保存的网页历史 Trace 做本地完整导出（把 `<RUN_ID>` 替换为历史运行 UUID；目标文件不能已存在）：

```bash
.venv/bin/python -m lottery_simulator export-trace \
  --database data/history_v4.sqlite3 --run-id <RUN_ID> --output trace.jsonl
```

该命令按批次读取，不受网页单次 10,000 条下载上限影响；只读历史数据库，不导出 `jobs_v4/` 中未提交的暂存任务。

网页固定为三个页面：“新建实验”“实验结果”“历史记录”。实验结果页有四种结果视图：“实验概览”“分类统计”“按抽次分析”“逐抽明细”；“分类统计”中再选择星级、六星构成、具体角色、奖励或保底，并可在“主池”（`main`）、“赠送”（`bonus`）、“总计”（`total`）间切换。批量角色图和角色统计只包含六星；四星、五星名单只在单抽结果和 Trace 中显示。结果中：

Trace JSON 的唯一单抽结构是 `draw_result` 嵌套对象：`draw_result.outcome` 保存星级、角色、UP/限定、奖励和保底触发，`draw_result.probabilities` 保存四/五/六星概率，`draw_result.state_before`/`state_after` 保存来源池双保底状态；记录本身的 `main_state_before`/`main_state_after` 独立保存主池状态。多轮记录另有 `trial_index`（从1开始的轮次）和 `draw_index`（该轮内主池与赠送合并后的抽次，从1开始）；`source_index` 是各来源自己的序号。网页将其只读展开为中文列：

| 中文列 | JSON 路径 |
|---|---|
| 轮次、轮内总抽次、来源、来源内序号、主池累计抽数、赠送事件 | `trial_index`、`draw_index`、`source`、`source_index`、`main_draws_completed`、`bonus_event` |
| 星级、角色、是否UP、是否限定 | `draw_result.outcome.rarity`、`character_name`、`is_up`、`is_limited` |
| 四星概率、五星概率、六星概率 | `draw_result.probabilities.four_star/five_star/six_star` |
| 来源池抽前/后未出六星、未出五星及以上 | `draw_result.state_before/state_after.*` |
| 主池抽前/后未出六星、未出五星及以上 | `main_state_before/main_state_after.*` |
| 五星保底触发、六星硬保底触发、各奖励数量 | `draw_result.outcome.*` |

概率在原始 JSON 中保持 `0..1`，网页表格按百分比显示；没有角色名单时显示“未配置角色名单”，不会伪装成未出六星。Trace 默认 `False`；历史和下载保留上述嵌套 JSON，不用展开后的中文表格替代原始记录。Trace 记录数按每轮主抽加赠送抽计算，网页在启动前和 worker 冷启动时都会检查总量上限。

- “每轮均值”是每轮平均数量，不是 1000 轮的总数量；总计等于主池和赠送合并后的来源。
- 理论期望按有限保底状态动态规划计算；完整周期理论平均间隔是长期周期量，可能与有限模拟中已完成周期的平均间隔不同。
- “至少一个”是各轮中至少命中一次的比率，包含五星及以上、六星、UP 六星和限定六星口径；没有六星时，角色的六星内实际占比和占比误差不可用（显示为空），不能据此判断角色概率。
- 保底触发表示抽到了保底位置；该位置仍可能先命中六星，因此不保证“触发五星保底”就一定恰好得到五星。
- 角色结果区显示角色类型、模拟均值、理论期望、六星内实际/理论占比及占比误差；零六星时实际占比不可用。
- 奖励区的分布横轴是每轮奖励总量，频数是达到该总量的实验轮数，另有占比；不要把频数当成单抽概率。
- 概率曲线只展示主池的完整保底周期（最多 80 抽），不是按本次模拟长度截断或延长。

## 6. 历史记录

“历史记录”页面使用实际网页标签“历史规则”“历史 Trace”“历史开始日期（UTC）”“历史结束日期（UTC）”“历史页码”。日期按 UTC 过滤；每页最多 20 条，创建时间倒序，改变筛选后将页码设为 1。通过“选择历史运行”选择一条查看详情、最多两条并排比较；每份记录显示规则版本，展开“配置摘要”查看保存的奖池快照和初始五星进度。

“复用参数”只恢复当次的参数和配置快照，不会直接重新运行；需要重新模拟时再点击开始。删除流程分两次：第一次点击“删除历史 …”只进入确认，随后选择“确认删除”才执行；删除不可撤销，并会连同该运行的 `records` 一起删除。选择“取消删除”则保留记录。

## 7. 数据目录与本地备份

未设置环境变量时，数据位于主目录：

```text
data/history_v4.sqlite3
data/jobs_v4/
```

可用绝对路径自定义：`LOTTERY_DATA_DIR` 控制数据目录（数据库默认是其中的 `history_v4.sqlite3` 和 `jobs_v4/`），`LOTTERY_DB_PATH` 单独覆盖数据库路径。例如：

```bash
LOTTERY_DATA_DIR=/srv/lottery-data LOTTERY_DB_PATH=/srv/lottery-data/history_v4.sqlite3 \
APP_ENVIRONMENT=development APP_AUTH_MODE=disabled STREAMLIT_SERVER_ADDRESS=127.0.0.1 \
.venv/bin/python -m streamlit run dashboard/app.py --server.address=127.0.0.1
```

启动目录和数据目录都要确认清楚：旧 worktree 的 `data/` 不会自动迁移到主目录。历史库只接受数据库 schema v4；旧 v1/v2/v3 库不会迁移、覆盖或自动删除，程序会拒绝不兼容 schema。仅在开启 Trace 且历史保存失败时，`jobs_v4/<job_id>/` 会保留完整 `trace.sqlite3` 和 `result.json`，当前结果仍可分页查看并导出；未开启 Trace 时没有暂存明细，只保留 `result.json` 汇总。上述任务目录文件均不在历史备份中。

SQLite 在线备份使用项目已有脚本，源库必须存在：

```bash
mkdir -p backups
.venv/bin/python scripts/backup_db.py data/history_v4.sqlite3 backups/history-v4-$(date +%F-%H%M%S).sqlite3
```

看到 `Backup integrity_check: ok` 且命令退出码为 0 才算成功。脚本从只读源库执行 SQLite online backup，并检查目标完整性；不要在网页或 worker 运行时直接复制、删除或盲删数据库，也不要用备份脚本把源和目标写成同一路径。备份只包含 v4 SQLite 历史，不包含 `data/jobs_v4/` 暂存任务、保存失败的暂存 Trace、OIDC secrets 或证书；重要备份还应复制到受控的其他存储。

### 本地恢复历史

恢复会覆盖当前新版历史库，只用于已知成功的备份。先在网页停止模拟并等任务结束，再用 `Ctrl+C` 停止网页，确认没有其他实例/worker 使用同一个库。不要删除 WAL 或任务目录。

先保护当前库，再恢复选定备份（下面备份日期仅为示例，必须替换成实际文件名；每一步失败即停止）：

```bash
.venv/bin/python scripts/backup_db.py data/history_v4.sqlite3 backups/pre-restore-v4-$(date +%F-%H%M%S).sqlite3
.venv/bin/python scripts/backup_db.py backups/history-v4-2026-09-16-120000.sqlite3 data/history_v4.sqlite3
.venv/bin/python -c "import sqlite3; c=sqlite3.connect('file:data/history_v4.sqlite3?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchall()); c.close()"
```

备份/恢复须退出码 0、输出完整性检查成功；最后查询须为 `[('ok',)]`，才重新按第 2 节启动。检查历史并运行一次小模拟确认可写。当前库不存在时可以跳过第一步，不能跳过现有库的保护备份。恢复只接受并恢复 v4 数据库历史，不迁移旧库，不恢复未完成任务或 `jobs_v4/` 暂存；结果 JSON 不是 SQLite 备份，不能拿来替换数据库。

## 8. 常见问题

- **找不到 `.venv/bin/python`**：通常是当前目录不对；回到 `/home/qykj/202607/test/lottery_simulator`，或使用绝对解释器路径 `/home/qykj/202607/test/lottery_simulator/.venv/bin/python`。运行 `dashboard/app.py` 仍应在项目主目录。若环境不存在，按第 1 节创建。
- **`No module named streamlit`**：当前 `.venv` 未安装网页依赖；执行 `.venv/bin/python -m pip install -r requirements.txt`。
- **8501 端口占用**：先停止自己已启动的服务；确认无需旧服务后，也可用 `--server.port 8502` 启动并打开 `http://127.0.0.1:8502`。
- **编辑值没有生效**：编辑单元格后按 `Enter` 确认，必要时刷新；不要在未确认编辑时立即开始模拟。
- **配置无效**：查看网页中文错误，重点检查 `up_share` 是否大于 0 且不超过 1、UP 是否为限定且权重为正、非 UP 权重是否为 `null`、名称是否重复，以及普通抽的五星/六星概率之和是否合规。
- **历史不见了**：核对启动时的 `LOTTERY_DATA_DIR`、`LOTTERY_DB_PATH` 和主目录；CLI 本身不会写网页历史库。
- **看到 `Deploy`**：那是 Streamlit 云部署入口，本地使用无需点击；本地只执行第 2 节命令。
