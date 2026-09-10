import unittest

from lottery_simulator.rules.base import BonusEvent
from lottery_simulator.rules.first_thirty_bonus import FirstThirtyBonusRule
from lottery_simulator.rules.rule_1 import Rule1


class FirstThirtyBonusRuleTest(unittest.TestCase):
    def test_only_main_draw_thirty_emits_the_bonus(self):
        subrule = FirstThirtyBonusRule()

        self.assertEqual(subrule.events_after_main_draw(29), ())
        self.assertEqual(subrule.events_after_main_draw(31), ())
        self.assertEqual(
            subrule.events_after_main_draw(30),
            (
                BonusEvent(
                    name="first_thirty_bonus",
                    draws=10,
                    six_star_probability=0.008,
                ),
            ),
        )

    def test_rule_one_composes_the_bonus_subrule(self):
        rule = Rule1()

        self.assertEqual(len(rule.subrules), 1)
        self.assertIsInstance(rule.subrules[0], FirstThirtyBonusRule)

    def test_bonus_event_rejects_invalid_draws_and_probabilities(self):
        for draws in (0, -1, True):
            with self.subTest(draws=draws):
                with self.assertRaises(ValueError):
                    BonusEvent("invalid", draws, 0.008)
        for probability in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(probability=probability):
                with self.assertRaises(ValueError):
                    BonusEvent("invalid", 1, probability)


if __name__ == "__main__":
    unittest.main()
