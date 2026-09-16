import unittest

from dashboard.charts import (
    character_rows,
    count_distribution_rows,
    pity_rows,
    probability_rows,
    rarity_comparison_rows,
    reward_distribution_rows,
    reward_rows,
    six_star_category_rows,
    source_comparison_rows,
)
from lottery_simulator.rules.rule_1 import Rule1


class ChartDataTest(unittest.TestCase):
    def setUp(self):
        characters = [
            {"name": "UP-A", "is_up": True, "is_limited": True, "up_weight": 1.0},
            {"name": "限定-B", "is_up": False, "is_limited": True, "up_weight": None},
            {"name": "限定-C", "is_up": False, "is_limited": True, "up_weight": None},
            {"name": "常驻-D", "is_up": False, "is_limited": False, "up_weight": None},
            {"name": "常驻-E", "is_up": False, "is_limited": False, "up_weight": None},
            {"name": "常驻-F", "is_up": False, "is_limited": False, "up_weight": None},
            {"name": "常驻-G", "is_up": False, "is_limited": False, "up_weight": None},
            {"name": "常驻-H", "is_up": False, "is_limited": False, "up_weight": None},
            {"name": "常驻-I", "is_up": False, "is_limited": False, "up_weight": None},
        ]
        simulated_characters = {
            "常驻-I": 0.05,
            "常驻-H": 0.05,
            "常驻-G": 0.1,
            "常驻-F": 0.1,
            "常驻-E": 0.1,
            "常驻-D": 0.1,
            "限定-C": 0.2,
            "限定-B": 0.3,
            "UP-A": 2.0,
        }
        theoretical_characters = {
            "常驻-I": 0.1875,
            "常驻-H": 0.1875,
            "常驻-G": 0.1875,
            "常驻-F": 0.1875,
            "常驻-E": 0.1875,
            "常驻-D": 0.1875,
            "限定-C": 0.1875,
            "限定-B": 0.1875,
            "UP-A": 1.5,
        }
        self.payload = {
            "trials": 10,
            "pool_config": {
                "up_share": 0.5,
                "five_star": {
                    "base_probability": 0.08,
                    "pity_enabled": True,
                    "hard_pity": 10,
                },
                "six_star_characters": characters,
                "rewards": [
                    {"name": "奖励A", "four_star": 1.0, "five_star": 5.0,
                     "six_star": 25.0},
                    {"name": "奖励B", "four_star": 0.0, "five_star": 2.0,
                     "six_star": 10.0},
                ],
            },
            "source_summaries": {
                "total": {
                    "mean_rarity_counts": {"4": 7.0, "5": 1.0, "6": 3.0},
                    "mean_six_star_categories": {
                        "up": 2.0, "other_limited": 0.5, "standard": 0.5,
                    },
                    "mean_character_counts": simulated_characters,
                    "mean_rewards": {"奖励B": 4.0, "奖励A": 12.0},
                    "mean_pity_triggers": {"five_star": 0.4, "six_star_hard": 0.2},
                }
            },
            "theoretical_source_summaries": {
                "total": {
                    "rarity_counts": {"4": 7.5, "5": 1.5, "6": 3.0},
                    "six_star_categories": {
                        "up": 1.5, "other_limited": 0.375, "standard": 1.125,
                    },
                    "character_counts": theoretical_characters,
                    "rewards": {"奖励B": 3.5, "奖励A": 11.5},
                    "pity_triggers": {"five_star": 0.3, "six_star_hard": 0.1},
                }
            },
            "source_distributions": {
                "total": {
                    "reward_totals": {
                        "奖励A": {"10.0": 1, "2.0": 6, "0.0": 3},
                        "奖励B": {"4.0": 4, "0.0": 6},
                    }
                }
            },
        }

    def test_rarity_comparison_rows_map_simulation_and_theory(self):
        self.assertEqual(
            rarity_comparison_rows(self.payload, "total"),
            [
                {"星级": "四星", "模拟均值": 7.0, "理论期望": 7.5},
                {"星级": "五星", "模拟均值": 1.0, "理论期望": 1.5},
                {"星级": "六星", "模拟均值": 3.0, "理论期望": 3.0},
            ],
        )

    def test_six_star_category_rows_map_all_categories(self):
        self.assertEqual(
            six_star_category_rows(self.payload, "total"),
            [
                {"类型": "UP限定", "模拟均值": 2.0, "理论期望": 1.5},
                {"类型": "其他限定", "模拟均值": 0.5, "理论期望": 0.375},
                {"类型": "常驻", "模拟均值": 0.5, "理论期望": 1.125},
            ],
        )

    def test_character_rows_compare_simulation_and_theory(self):
        rows = character_rows(self.payload, "total")
        self.assertEqual([row["角色"] for row in rows], [
            "UP-A", "限定-B", "限定-C", "常驻-D", "常驻-E",
            "常驻-F", "常驻-G", "常驻-H", "常驻-I",
        ])
        self.assertEqual(rows[0]["类型"], "UP限定")
        self.assertAlmostEqual(rows[0]["六星内理论占比"], 0.5)
        self.assertAlmostEqual(rows[0]["六星内实际占比"], 2.0 / 3.0)
        self.assertAlmostEqual(rows[0]["占比误差"], 0.16666666666666663)
        self.assertAlmostEqual(
            sum(row["理论期望"] for row in rows),
            self.payload["theoretical_source_summaries"]["total"]
            ["rarity_counts"]["6"],
        )

    def test_character_rows_use_none_for_actual_share_when_no_six_stars(self):
        self.payload["source_summaries"]["total"]["mean_rarity_counts"]["6"] = 0.0

        rows = character_rows(self.payload, "total")

        self.assertTrue(all(row["六星内实际占比"] is None for row in rows))
        self.assertTrue(all(row["占比误差"] is None for row in rows))

    def test_reward_rows_follow_pool_configuration_order(self):
        self.assertEqual(
            reward_rows(self.payload, "total"),
            [
                {"奖励": "奖励A", "模拟均值": 12.0, "理论期望": 11.5},
                {"奖励": "奖励B", "模拟均值": 4.0, "理论期望": 3.5},
            ],
        )

    def test_reward_distribution_rows_sort_numeric_string_keys_as_numbers(self):
        self.assertEqual(
            reward_distribution_rows(self.payload, "total", "奖励A"),
            [
                {"奖励总量": 0.0, "实验次数": 3, "占比": 0.3},
                {"奖励总量": 2.0, "实验次数": 6, "占比": 0.6},
                {"奖励总量": 10.0, "实验次数": 1, "占比": 0.1},
            ],
        )

    def test_pity_rows_map_five_and_six_star_triggers(self):
        self.assertEqual(
            pity_rows(self.payload, "total"),
            [
                {"保底类型": "五星保底", "模拟均值": 0.4, "理论期望": 0.3},
                {"保底类型": "六星硬保底", "模拟均值": 0.2, "理论期望": 0.1},
            ],
        )

    def test_probability_rows_follow_rule_and_analyzer_output(self):
        rows = probability_rows(Rule1())

        self.assertEqual(len(rows), 80)
        self.assertEqual(rows[64]["抽次"], 65)
        self.assertAlmostEqual(rows[64]["条件六星概率"], 0.008)
        self.assertEqual(rows[65]["抽次"], 66)
        self.assertAlmostEqual(rows[65]["条件六星概率"], 0.058)
        self.assertEqual(rows[79]["抽次"], 80)
        self.assertEqual(rows[79]["条件六星概率"], 1.0)
        self.assertGreater(rows[79]["首次六星累计概率"], 0.999999999999)

    def test_count_distribution_rows_sort_numeric_string_keys_as_integers(self):
        rows = count_distribution_rows(
            {"count_distribution": {"10": 1, "2": 3, "0": 6}, "trials": 10}
        )

        self.assertEqual(
            rows,
            [
                {"六星数量": 0, "实验次数": 6, "占比": 0.6},
                {"六星数量": 2, "实验次数": 3, "占比": 0.3},
                {"六星数量": 10, "实验次数": 1, "占比": 0.1},
            ],
        )

    def test_source_comparison_rows_map_exact_simulated_and_theoretical_values(self):
        payload = {
            "mean_main_six_stars": 1.25,
            "mean_bonus_six_stars": 0.5,
            "mean_six_stars": 1.75,
            "theoretical_expected_main_count": 1.2,
            "theoretical_expected_bonus_count": 0.4,
            "theoretical_expected_count": 1.6,
        }

        self.assertEqual(
            source_comparison_rows(payload),
            [
                {"来源": "主池", "模拟均值": 1.25, "理论期望": 1.2},
                {"来源": "赠送", "模拟均值": 0.5, "理论期望": 0.4},
                {"来源": "总计", "模拟均值": 1.75, "理论期望": 1.6},
            ],
        )


if __name__ == "__main__":
    unittest.main()
