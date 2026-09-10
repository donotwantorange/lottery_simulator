import unittest

from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.rule_1 import Rule1


class Rule1Test(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_probability_boundaries(self):
        expected = {0: 0.008, 63: 0.008, 64: 0.058, 78: 0.758, 79: 1.0}
        for misses, probability in expected.items():
            with self.subTest(misses=misses):
                self.assertAlmostEqual(
                    self.rule.probability(DrawState(misses)), probability
                )

    def test_six_star_resets_state(self):
        self.assertEqual(
            self.rule.advance(DrawState(64), True), DrawState(0)
        )

    def test_miss_advances_state(self):
        self.assertEqual(
            self.rule.advance(DrawState(63), False), DrawState(64)
        )

    def test_invalid_states_are_rejected(self):
        for misses in (-1, 80):
            with self.subTest(misses=misses):
                with self.assertRaises(ValueError):
                    self.rule.probability(DrawState(misses))

    def test_missing_guaranteed_pull_is_rejected(self):
        with self.assertRaises(ValueError):
            self.rule.advance(DrawState(79), False)

    def test_rule_version_identifies_bonus_rule_behavior(self):
        self.assertEqual(self.rule.version, "1.1")


if __name__ == "__main__":
    unittest.main()
