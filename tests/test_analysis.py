import unittest

from lottery_simulator.analysis import (
    distribution_stats,
    expected_six_stars,
    waiting_time_distribution,
)
from lottery_simulator.rules.rule_1 import Rule1


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_distribution_is_complete(self):
        probabilities = waiting_time_distribution(self.rule)
        self.assertEqual(len(probabilities), 80)
        self.assertAlmostEqual(sum(probabilities), 1.0, places=12)
        self.assertAlmostEqual(probabilities[-1], 0.00007302369959649657)

    def test_rule_1_reference_statistics(self):
        stats = distribution_stats(self.rule)
        self.assertAlmostEqual(stats.mean, 53.32595362219928)
        self.assertAlmostEqual(stats.standard_deviation, 22.631871302420425)
        self.assertEqual(stats.median, 67)
        self.assertEqual(stats.mode, 68)
        self.assertEqual(stats.quantiles, {0.90: 72, 0.95: 73, 0.99: 75})
        self.assertAlmostEqual(stats.long_run_rate, 0.018752594788735404)

    def test_one_draw_expectation_is_its_probability(self):
        self.assertAlmostEqual(expected_six_stars(self.rule, 1), 0.008)
        self.assertAlmostEqual(
            expected_six_stars(self.rule, 1, initial_pity=64), 0.058
        )

    def test_eighty_draw_expectation_accounts_for_reset(self):
        value = expected_six_stars(self.rule, 80)
        self.assertAlmostEqual(value, 1.2628497757227852)

    def test_invalid_analysis_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            expected_six_stars(self.rule, 0)
        with self.assertRaises(ValueError):
            waiting_time_distribution(self.rule, initial_pity=80)


if __name__ == "__main__":
    unittest.main()
