from fractions import Fraction
from itertools import product
import unittest

from lottery_simulator.analysis import (
    distribution_stats,
    expected_bonus_six_stars,
    expected_six_stars,
    waiting_time_distribution,
)
from lottery_simulator.rules.rule_1 import Rule1


class InvalidProbabilityRule(Rule1):
    def __init__(self, invalid_state, probability):
        self.invalid_state = invalid_state
        self.invalid_probability = probability

    def probability(self, state):
        if state.misses_since_six_star == self.invalid_state:
            return self.invalid_probability
        return super().probability(state)


def enumerate_rule_1_expectation(draws, initial_pity):
    """Enumerate event sequences using exact, spec-derived probabilities."""
    expected = Fraction(0)
    for outcomes in product((False, True), repeat=draws):
        misses = initial_pity
        weight = Fraction(1)
        for success in outcomes:
            if misses == 79:
                probability = Fraction(1)
            else:
                probability = Fraction(8, 1000) + max(0, misses - 64) * Fraction(5, 100)
            weight *= probability if success else 1 - probability
            if not weight:
                break
            misses = 0 if success else misses + 1
        expected += weight * sum(outcomes)
    return float(expected)


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_distribution_is_complete(self):
        probabilities = waiting_time_distribution(self.rule)
        self.assertEqual(len(probabilities), 80)
        self.assertAlmostEqual(sum(probabilities), 1.0, places=12)
        self.assertAlmostEqual(probabilities[-1], 0.00029933681818068074)

    def test_rule_1_reference_statistics(self):
        stats = distribution_stats(self.rule)
        self.assertAlmostEqual(stats.mean, 53.89927355371174)
        self.assertAlmostEqual(stats.standard_deviation, 23.036219232912913)
        self.assertEqual(stats.median, 67)
        self.assertEqual(stats.mode, 69)
        self.assertEqual(stats.quantiles, {0.90: 73, 0.95: 74, 0.99: 76})
        self.assertAlmostEqual(stats.long_run_rate, 0.01855312574859621)

    def test_one_draw_expectation_is_its_probability(self):
        self.assertAlmostEqual(expected_six_stars(self.rule, 1), 0.008)
        self.assertAlmostEqual(
            expected_six_stars(self.rule, 1, initial_pity=64), 0.008
        )
        self.assertAlmostEqual(
            expected_six_stars(self.rule, 1, initial_pity=65), 0.058
        )

    def test_eighty_draw_expectation_accounts_for_reset(self):
        value = expected_six_stars(self.rule, 80)
        self.assertAlmostEqual(value, 1.2533176900565965)

    def test_bonus_expectation_only_applies_when_crossing_main_draw_thirty(self):
        cases = (
            (29, 0, 0.0),
            (30, 0, 0.08),
            (1, 29, 0.08),
            (1, 30, 0.0),
        )
        for draws, initial_pity, expected in cases:
            with self.subTest(draws=draws, initial_pity=initial_pity):
                self.assertAlmostEqual(
                    expected_bonus_six_stars(self.rule, draws, initial_pity),
                    expected,
                )

    def test_dp_matches_independent_exhaustive_outcomes(self):
        for initial_pity in (0, 63, 64, 78, 79):
            for draws in range(1, 6):
                with self.subTest(initial_pity=initial_pity, draws=draws):
                    self.assertAlmostEqual(
                        expected_six_stars(self.rule, draws, initial_pity),
                        enumerate_rule_1_expectation(draws, initial_pity),
                        places=12,
                    )

    def test_invalid_analysis_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            expected_six_stars(self.rule, 0)
        with self.assertRaises(ValueError):
            waiting_time_distribution(self.rule, initial_pity=80)

    def test_invalid_probabilities_are_rejected_at_each_reached_dp_state(self):
        for value in (-0.1, 1.1, float("nan"), float("inf"), -float("inf")):
            for initial_pity, invalid_state, draws in ((0, 0, 1), (0, 1, 2), (79, 0, 2)):
                with self.subTest(value=value, initial_pity=initial_pity, invalid_state=invalid_state):
                    rule = InvalidProbabilityRule(invalid_state, value)
                    with self.assertRaisesRegex(ValueError, r"probability outside \[0, 1\]"):
                        expected_six_stars(rule, draws, initial_pity)

    def test_waiting_distribution_rejects_invalid_probabilities(self):
        for value in (-0.1, 1.1, float("nan"), float("inf"), -float("inf")):
            for invalid_state in (0, 1):
                with self.subTest(value=value, invalid_state=invalid_state):
                    with self.assertRaisesRegex(ValueError, r"probability outside \[0, 1\]"):
                        waiting_time_distribution(InvalidProbabilityRule(invalid_state, value))


if __name__ == "__main__":
    unittest.main()
