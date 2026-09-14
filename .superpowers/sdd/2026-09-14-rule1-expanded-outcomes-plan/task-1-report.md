# Task 1 报告：不可变奖池配置与默认 JSON

## 实现内容

- 新增 `FiveStarPolicy`、`SixStarCharacter`、`RewardRule` 和不可变 `PoolConfig` 数据模型，均使用 `@dataclass(frozen=True, slots=True)`。
- `PoolConfig.from_dict()` 统一完成配置边界校验并把角色、奖励列表转换为元组；`to_dict()` 输出稳定的 JSON 可序列化字段。
- 实现 UP 按权重分配、非 UP 等概率分配，以及按稀有度查询奖励。
- 新增默认规则配置：五星基础概率 0.08、五星保底开启且阈值 10；六星池 9 名、1 名 UP、3 名限定、UP 占比 0.5；奖励 A 为 1/5/25，奖励 B 为 0/2/10。
- `load_pool_config()` 支持显式路径；无路径时加载 `configs/rule1_default.json`。
- 从 `lottery_simulator.rules` 和 `lottery_simulator` 导出全部配置接口。

## 变更文件

- `configs/rule1_default.json`
- `lottery_simulator/rules/pool_config.py`
- `lottery_simulator/rules/__init__.py`
- `lottery_simulator/__init__.py`
- `tests/test_pool_config.py`

## RED

命令：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_pool_config -v
```

关键失败输出：

```text
ModuleNotFoundError: No module named 'lottery_simulator.rules.pool_config'
```

失败原因：测试先引用任务要求的新配置模块，而生产模块尚未创建，验证了测试能捕获缺失功能。

## GREEN

命令：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_pool_config -v
```

结果：`Ran 4 tests ... OK`。

全量回归命令：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest discover -v
```

结果：`Ran 146 tests ... OK`。

## 突变/恢复因果检查

临时删除 `SixStarCharacter.__post_init__()` 中“UP 必须限定”校验后运行：

```text
/home/qykj/202607/test/lottery_simulator/.venv/bin/python -m unittest tests.test_pool_config.PoolConfigTest.test_invalid_character_combinations_are_rejected -v
```

结果：失败，子测试 `description='up must be limited'` 报 `AssertionError: ValueError not raised`。

恢复校验后运行同一命令，结果：`Ran 1 test ... OK`。

## 自审发现

- 配置模型的列表在解析边界转换为元组，字段和嵌套对象不可变。
- 数值校验拒绝布尔值、NaN、无穷、越界概率、非正权重和负奖励。
- 重名、空名、无 UP、UP 非限定以及 `up_share < 1` 无非 UP 均被拒绝。
- 未实现依赖六星曲线的 `p6 + base_p5` 联合校验，符合 Task 1 边界。
- `git diff --check` 未发现空白错误；旧测试未受影响。

## 问题/担忧

无。任务要求的配置级行为已验证；五星/六星联合概率校验留给 Task 2。
