import unittest

from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_fixed_seed_is_reproducible(self):
        first = simulate(self.rule, draws=100, trials=1, seed=42)
        second = simulate(self.rule, draws=100, trials=1, seed=42)
        self.assertEqual(first, second)

    def test_single_trial_keeps_trace(self):
        result = simulate(self.rule, draws=3, trials=1, seed=42)
        self.assertEqual(len(result.records), 3)
        self.assertEqual(result.records[0].pity_position, 1)
        self.assertEqual(sum(result.count_distribution.values()), 1)

    def test_multiple_trials_only_keep_aggregates(self):
        result = simulate(self.rule, draws=100, trials=50, seed=42)
        self.assertEqual(result.records, ())
        self.assertEqual(sum(result.count_distribution.values()), 50)
        self.assertEqual(result.theoretical_expected_count > 0, True)

    def test_initial_pity_is_applied(self):
        result = simulate(self.rule, draws=1, trials=1, seed=1, initial_pity=79)
        self.assertTrue(result.records[0].is_six_star)
        self.assertEqual(result.records[0].probability, 1.0)
        self.assertEqual(result.records[0].state_after.misses_since_six_star, 0)

    def test_omitted_seed_is_returned(self):
        result = simulate(self.rule, draws=1)
        self.assertIsInstance(result.seed, int)

    def test_invalid_inputs_are_rejected(self):
        for draws, trials in ((0, 1), (1, 0), (True, 1)):
            with self.subTest(draws=draws, trials=trials):
                with self.assertRaises(ValueError):
                    simulate(self.rule, draws=draws, trials=trials)


if __name__ == "__main__":
    unittest.main()
