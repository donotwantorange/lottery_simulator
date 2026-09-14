# 抽奖模拟器

一个 Python 3.11+ 六星动态保底模拟器。命令行核心无第三方依赖；可选网页仪表盘使用 Streamlit，公网部署使用 Docker/Caddy。

## 网页仪表盘

本地开发（仅监听本机，显式免登录）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
APP_ENVIRONMENT=development APP_AUTH_MODE=disabled STREAMLIT_SERVER_ADDRESS=127.0.0.1 .venv/bin/python -m streamlit run dashboard/app.py --server.headless=true --server.address=127.0.0.1
```

打开 `http://127.0.0.1:8501`。支持后台进度/停止、指标与图表数值表、单轮 Trace、JSON 下载、历史筛选、双运行对比、参数复用和二次确认删除。开发历史默认保存到 `data/history.sqlite3`，任务状态位于 `data/jobs/`；可用 `LOTTERY_DATA_DIR` 改数据目录，`LOTTERY_DB_PATH` 单独覆盖数据库路径。

Linux 公网部署须先按 [部署与运维手册](docs/deployment.md) 配好 DNS、`.env` 的 `DOMAIN`/`ALLOWED_EMAILS` 和私密 `.streamlit/secrets.toml`，再运行：

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app caddy
```

Compose 固定 production/OIDC，仅 Caddy 发布 80/443；页面及 worker 使用 `LOTTERY_DB_PATH=/app/data/lottery.sqlite3`，与每日备份路径一致。数据、备份和证书保存在命名卷，secrets 只读挂载。手册包含定时备份安装、停机恢复、升级与命名 Git 提交回滚命令；不要执行 `docker compose down -v`。

✅ 本地功能及服务器部署接口已实现，部署静态合同已验证。⚠️ 按当前范围，真正服务器部署和测试暂缓；镜像、Compose 运行和公网 HTTPS/OIDC 均为服务器现场未验，不能用本地测试替代。详细证据和验收边界见 [变更记录](docs/changes/2026-09-10-web-dashboard.md)。

## 精确分析

`python3 -m lottery_simulator analyze`

## 批量模拟

`python3 -m lottery_simulator simulate --draws 100 --trials 100000 --seed 42`

`--draws` 表示每轮的主池抽数。若本轮经过累计第 30 次主池抽取，程序会自动追加 10 次赠送抽，并将主池、赠送和总结果分开统计。

## 单轮跟踪

`python3 -m lottery_simulator simulate --draws 30 --trials 1 --initial-pity 60 --seed 123 --trace`

## 参数

- `--rule`：规则模块，默认 `rule1`。
- `--draws`：每轮抽数，必填正整数。
- `--trials`：实验轮数，默认 1。
- `--seed`：整数随机种子；省略时程序生成并显示实际种子。
- `--initial-pity`：开始前连续未出六星次数，规则 1 接受 0–79。它同时作为模拟开始时的累计主抽数：例如 `--draws 1 --initial-pity 29` 会在这次主抽后触发 10 次赠送；初始值大于或等于 30 时视为赠送已经领取，不再触发。
- `--trace`：显示逐抽详情，仅可用于一轮实验。
- `--format`：`text` 或 `json`。

## 结果含义

`analyze` 是主池保底规则由概率公式计算的精确理论结果。`simulate` 是伪随机实验；指定相同参数和种子可复现。长期综合六星率为平均完整保底周期的倒数；有限抽数内的主池理论六星数量由状态动态规划计算。

## 首次 30 抽赠送子规则

规则 1 组合了 `FirstThirtyBonusRule`：

- 累计完成第 30 次主池抽取后，立即赠送 10 抽；
- 每次赠送抽的六星概率固定为 0.8%；
- 赠送抽不增加也不重置主池保底；
- 主池提前抽到六星不会推迟第 30 次主池抽取后的赠送；
- 每轮最多触发一次，赠送记录从 1 到 10 单独编号。

例如 `--draws 30 --initial-pity 0` 会执行 30 次主池抽取和 10 次赠送抽，总抽数为 40；`--draws 1 --initial-pity 30` 视为赠送已经领取，只执行 1 次主池抽取。

触发赠送时，赠送六星期望固定为 `10 × 0.8% = 0.08`。模拟输出分别给出主池、赠送及总抽数，以及对应的模拟六星均值和理论期望。

模拟汇总同时显示初始和结束主池累计抽数；JSON 对应字段为 `initial_main_draws` 和 `final_main_draws`。使用 `--trace` 时，每条主池或赠送记录都包含 `main_draws_completed`：主池抽取后加一，赠送抽期间保持不变。

批量模拟中的“期望误差”比较模拟平均六星数和相同有限抽数下的精确期望，可以用于检查抽样收敛，但单次小样本偏差不能证明实现错误。相同地，期望误差很小或与理论一致也不能证明实现正确。“已完成周期平均间隔”忽略模拟结束时尚未完成的周期，短模拟会有截尾偏差，不能单独用于验证规则。

## 测试

`python3 -m unittest discover -v`
