# 主池累计抽数显示

## 状态

设计已确认，待实现。

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

## 预计涉及文件

- `lottery_simulator/engine.py`
- `lottery_simulator/cli.py`
- `tests/test_engine.py`
- `tests/test_cli.py`
- `README.md`

## 验证结果

实现后补充。

## Git 提交

实现后补充。
