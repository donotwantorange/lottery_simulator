import unittest

from lottery_simulator.engine import draw_once
from lottery_simulator.rules.base import BonusEvent, DrawState
from lottery_simulator.rules.first_thirty_bonus import FirstThirtyBonusRule
from lottery_simulator.rules.rule_1 import Rule1


class ConstantRandom:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


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
                    five_star_hard_pity=10,
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
                    BonusEvent("invalid", draws, 0.008, 10)
        for probability in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(probability=probability):
                with self.assertRaises(ValueError):
                    BonusEvent("invalid", 1, probability, 10)
        for hard_pity in (0, -1, True):
            with self.subTest(hard_pity=hard_pity):
                with self.assertRaises(ValueError):
                    BonusEvent("invalid", 1, 0.008, hard_pity)

    def test_bonus_event_builds_isolated_temporary_pool(self):
        main = Rule1()
        event = FirstThirtyBonusRule().events_after_main_draw(30)[0]
        temporary = main.for_bonus(event)

        self.assertIs(
            temporary.config.six_star_characters,
            main.config.six_star_characters,
        )
        self.assertIs(temporary.config.rewards, main.config.rewards)
        self.assertEqual(temporary.probability(DrawState(9, 9)), 0.008)
        self.assertTrue(temporary.config.five_star.pity_enabled)
        self.assertEqual(temporary.config.five_star.hard_pity, 10)
        self.assertEqual(temporary.subrules, ())

    def test_temporary_pool_guarantees_at_least_five_star_in_ten_draws(self):
        temporary = Rule1().for_bonus(
            FirstThirtyBonusRule().events_after_main_draw(30)[0]
        )
        state = DrawState()
        rarities = []
        rng = ConstantRandom(0.999)

        for _ in range(10):
            outcome, state, _ = draw_once(temporary, state, rng)
            rarities.append(outcome.rarity)

        self.assertEqual(rarities, [4] * 9 + [5])


if __name__ == "__main__":
    unittest.main()
