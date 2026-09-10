# 主池累计抽数显示

## 状态

已完成，位于 `feature/bonus-subrule` 分支，尚未合并到 `master`。

## 目标

在文本汇总、JSON 和逐抽记录中统一显示主池累计抽数，明确赠送抽不会推进该计数。

## 确认规则

- 文本汇总显示初始与结束主池累计抽数。
- JSON 增加 `initial_main_draws` 与 `final_main_draws`。
- 每条逐抽记录增加主池累计抽数。
- 主池抽取后累计数加一。
- 赠送 10 抽期间，累计数固定为触发时的 30。
- `initial_pity` 同时作为模拟开始时的主池累计抽数。

## 示例

`--initial-pity 29 --draws 2` 的来源与累计数顺序为：主池 30、赠送 1–10 均为 30、下一次主池为 31。

## 涉及文件

- `lottery_simulator/engine.py`
- `lottery_simulator/cli.py`
- `tests/test_engine.py`
- `tests/test_cli.py`
- `README.md`

## 验证结果

- 自动化测试固定了 `29 → 主池30 → 10次赠送均保持30 → 主池31` 的完整序列。
- 文本汇总验证初始累计数 29、结束累计数 31。
- JSON 验证 `initial_main_draws`、`final_main_draws` 及每条记录的 `main_draws_completed`；批量实验中的起止值按每轮表示，不随 `trials` 累加。
- 真实文本与 JSON 入口验收通过。
- 独立审查发现公开结果 dataclass 的位置参数兼容风险；已恢复原字段顺序，并以回归测试验证旧构造方式。
- 完整测试：41 项通过。

## Git 提交

- `1ca3a90 feat: display cumulative main draw count`
- `577ae28 fix: preserve result constructor compatibility`
