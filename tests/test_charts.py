import unittest

from dashboard.charts import (
    count_distribution_rows,
    probability_rows,
    source_comparison_rows,
)
from lottery_simulator.rules.rule_1 import Rule1


class ChartDataTest(unittest.TestCase):
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
