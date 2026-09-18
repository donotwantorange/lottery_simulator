import unittest
from copy import deepcopy

from dashboard.trace import trace_rows


class TraceRowsTest(unittest.TestCase):
    def setUp(self):
        self.record = {
            "record_format_version": 1,
            "draw_index": 1,
            "source": "main",
            "source_index": 1,
            "bonus_event": None,
            "main_draws_completed": 1,
            "draw_result": {
                "outcome": {
                    "rarity": 4,
                    "character_name": None,
                    "is_up": False,
                    "is_limited": False,
                    "rewards": {"奖励A": 1.0, "奖励B": 0.0},
                    "five_star_pity_triggered": False,
                    "six_star_hard_pity_triggered": False,
                },
                "probabilities": {"four_star": 0.912, "five_star": 0.08, "six_star": 0.008},
                "state_before": {"misses_since_six_star": 0, "misses_since_five_or_higher": 0},
                "state_after": {"misses_since_six_star": 1, "misses_since_five_or_higher": 1},
            },
            "main_state_before": {"misses_since_six_star": 0, "misses_since_five_or_higher": 0},
            "main_state_after": {"misses_since_six_star": 1, "misses_since_five_or_higher": 1},
        }

    def test_trace_rows_keep_original_record(self):
        before = deepcopy(self.record)

        rows = trace_rows([self.record], ("奖励A", "奖励B"))

        self.assertEqual(rows[0]["星级"], 4)
        self.assertEqual(rows[0]["来源"], "主池")
        self.assertEqual(rows[0]["角色"], "未配置角色名单")
        self.assertEqual(rows[0]["六星概率"], 0.008)
        self.assertEqual(rows[0]["奖励：奖励A"], 1.0)
        self.assertEqual(self.record, before)

    def test_trace_rows_map_bonus_and_all_nested_fields(self):
        record = deepcopy(self.record)
        record.update(
            draw_index=31,
            source="bonus",
            source_index=2,
            bonus_event="首30抽赠送",
            main_draws_completed=30,
            main_state_before={"misses_since_six_star": 29, "misses_since_five_or_higher": 4},
            main_state_after={"misses_since_six_star": 29, "misses_since_five_or_higher": 4},
        )
        record["draw_result"] = {
            "outcome": {
                "rarity": 6,
                "character_name": "限定A",
                "is_up": True,
                "is_limited": True,
                "rewards": {"奖励A": 0.0, "奖励B": 2.5},
                "five_star_pity_triggered": True,
                "six_star_hard_pity_triggered": False,
            },
            "probabilities": {"four_star": 0.9, "five_star": 0.09, "six_star": 0.01},
            "state_before": {"misses_since_six_star": 1, "misses_since_five_or_higher": 2},
            "state_after": {"misses_since_six_star": 0, "misses_since_five_or_higher": 0},
        }

        row = trace_rows([record], ("奖励A", "奖励B"))[0]

        self.assertEqual(
            list(row),
            [
                "总体抽取序号", "来源", "来源内序号", "主池累计抽数", "星级", "角色",
                "是否UP", "是否限定", "四星概率", "五星概率", "六星概率",
                "来源池抽前未出六星", "来源池抽前未出五星及以上",
                "来源池抽后未出六星", "来源池抽后未出五星及以上",
                "主池抽前未出六星", "主池抽前未出五星及以上",
                "主池抽后未出六星", "主池抽后未出五星及以上",
                "五星保底触发", "六星硬保底触发", "赠送事件", "奖励：奖励A", "奖励：奖励B",
            ],
        )
        self.assertEqual(row, {
            "总体抽取序号": 31, "来源": "赠送", "来源内序号": 2,
            "主池累计抽数": 30, "星级": 6, "角色": "限定A",
            "是否UP": True, "是否限定": True,
            "四星概率": 0.9, "五星概率": 0.09, "六星概率": 0.01,
            "来源池抽前未出六星": 1, "来源池抽前未出五星及以上": 2,
            "来源池抽后未出六星": 0, "来源池抽后未出五星及以上": 0,
            "主池抽前未出六星": 29, "主池抽前未出五星及以上": 4,
            "主池抽后未出六星": 29, "主池抽后未出五星及以上": 4,
            "五星保底触发": True, "六星硬保底触发": False,
            "赠送事件": "首30抽赠送", "奖励：奖励A": 0.0, "奖励：奖励B": 2.5,
        })

    def test_trace_rows_show_named_four_and_five_star_characters(self):
        for rarity, name in ((4, "四星角色"), (5, "五星角色")):
            with self.subTest(rarity=rarity):
                record = deepcopy(self.record)
                record["draw_result"]["outcome"].update(rarity=rarity, character_name=name)
                row = trace_rows([record], ())[0]
                self.assertEqual((row["星级"], row["角色"]), (rarity, name))

    def test_trace_rows_use_configured_reward_order_and_allow_no_rewards(self):
        row = trace_rows([self.record], ("奖励B", "奖励A"))[0]
        self.assertEqual(list(row)[-2:], ["奖励：奖励B", "奖励：奖励A"])
        self.assertEqual((row["奖励：奖励B"], row["奖励：奖励A"]), (0.0, 1.0))
        row = trace_rows([self.record], ())[0]
        self.assertFalse(any(name.startswith("奖励：") for name in row))
        self.assertEqual(trace_rows([], ("奖励A",)), [])


if __name__ == "__main__":
    unittest.main()
