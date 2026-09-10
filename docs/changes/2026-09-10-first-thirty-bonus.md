# 首次 30 抽赠送子规则

## 状态

已完成，位于 `feature/bonus-subrule` 分支，尚未合并到 `master`。

## 目标

规则 1 在累计完成第 30 次主池抽取后，通过独立子规则自动执行 10 次赠送抽。

## 确认规则

- 每轮只触发一次。
- 赠送抽每抽六星概率固定为 0.8%。
- 赠送抽不增加、不重置主池保底。
- 主池提前出现六星不会推迟累计第 30 次主抽后的赠送。
- `initial_pity >= 30` 时视为已经领取。
- `--draws` 只表示本轮主池抽数；赠送抽单独显示并计入总抽数。

## 设计与边界

`Rule1` 组合无状态 `FirstThirtyBonusRule`。子规则根据累计主池抽数返回 `BonusEvent`，引擎不硬编码 30、10 或 0.8%。精确主池分析保持不变，有限抽数总期望在触发赠送时增加 `10 × 0.8% = 0.08`。

## 涉及文件

- `lottery_simulator/rules/base.py`
- `lottery_simulator/rules/first_thirty_bonus.py`
- `lottery_simulator/rules/rule_1.py`
- `lottery_simulator/engine.py`
- `lottery_simulator/analysis.py`
- `lottery_simulator/cli.py`
- `tests/test_bonus_rule.py`
- `tests/test_engine.py`
- `tests/test_analysis.py`
- `tests/test_cli.py`
- `README.md`

## 验证结果

- 子规则只在累计主抽数 30 返回事件。
- 验证初始进度 29 触发、初始进度 30 跳过。
- 验证赠送六星不重置主池保底，并做错误突变与恢复因果检查。
- 验证提前出现主池六星仍按累计第 30 次主抽触发。
- 完整测试：37 项通过。
- 独立代码审查：通过，无阻塞问题。

## Git 提交

- `9a85e90 feat: add first-thirty bonus subrule`
- `b33ad3d docs: clarify bonus subrule state contract`
