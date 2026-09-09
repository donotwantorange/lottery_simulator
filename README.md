# 抽奖模拟器

一个无第三方依赖的 Python 3.11+ 六星动态保底模拟器。

## 精确分析

`python3 -m lottery_simulator analyze`

## 批量模拟

`python3 -m lottery_simulator simulate --draws 100 --trials 100000 --seed 42`

## 单轮跟踪

`python3 -m lottery_simulator simulate --draws 30 --trials 1 --initial-pity 60 --seed 123 --trace`

## 参数

- `--rule`：规则模块，默认 `rule1`。
- `--draws`：每轮抽数，必填正整数。
- `--trials`：实验轮数，默认 1。
- `--seed`：整数随机种子；省略时程序生成并显示实际种子。
- `--initial-pity`：开始前连续未出六星次数，规则 1 接受 0–79。
- `--trace`：显示逐抽详情，仅可用于一轮实验。
- `--format`：`text` 或 `json`。

## 结果含义

`analyze` 是由概率公式计算的精确理论结果。`simulate` 是伪随机实验；指定相同参数和种子可复现。长期综合六星率为平均完整保底周期的倒数；有限抽数内的理论六星数量由状态动态规划计算。

批量模拟中的“期望误差”比较模拟平均六星数和相同有限抽数下的精确期望，可以用于检查抽样收敛，但单次小样本偏差不能证明实现错误。相同地，期望误差很小或与理论一致也不能证明实现正确。“已完成周期平均间隔”忽略模拟结束时尚未完成的周期，短模拟会有截尾偏差，不能单独用于验证规则。

## 测试

`python3 -m unittest discover -v`
