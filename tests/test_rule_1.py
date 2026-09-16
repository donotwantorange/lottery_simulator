from dataclasses import replace
import unittest

from lottery_simulator.rules.base import DrawState, RarityProbabilities
from lottery_simulator.rules.pool_config import load_pool_config
from lottery_simulator.rules.rule_1 import Rule1


class Rule1Test(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_probability_boundaries(self):
        expected = {
            0: 0.008,
            63: 0.008,
            64: 0.008,
            65: 0.058,
            78: 0.708,
            79: 1.0,
        }
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

    def test_rule_version_identifies_current_behavior(self):
        self.assertEqual(self.rule.version, "2.0")

    def test_rarity_probabilities_and_five_star_pity_boundaries(self):
        rule = Rule1()
        self.assertEqual(rule.version, "2.0")
        normal = rule.rarity_probabilities(DrawState(64, 0))
        self.assertEqual(normal, RarityProbabilities(0.912, 0.08, 0.008))
        soft = rule.rarity_probabilities(DrawState(65, 0))
        self.assertAlmostEqual(soft.six_star, 0.058)
        self.assertAlmostEqual(soft.five_star, 0.08)
        self.assertAlmostEqual(soft.four_star, 0.862)
        five_pity = rule.rarity_probabilities(DrawState(65, 9))
        self.assertEqual(five_pity.four_star, 0.0)
        self.assertAlmostEqual(five_pity.five_star, 0.942)
        self.assertAlmostEqual(five_pity.six_star, 0.058)
        self.assertEqual(rule.rarity_probabilities(DrawState(79, 9)).six_star, 1.0)

    def test_each_rarity_advances_both_pity_states(self):
        rule = Rule1()
        self.assertEqual(rule.advance_rarity(DrawState(4, 3), 4), DrawState(5, 4))
        self.assertEqual(rule.advance_rarity(DrawState(4, 3), 5), DrawState(5, 0))
        self.assertEqual(rule.advance_rarity(DrawState(4, 3), 6), DrawState(0, 0))

    def test_disabled_five_star_pity_requires_zero_state_and_keeps_base_rate(self):
        config = load_pool_config()
        disabled = replace(
            config,
            five_star=replace(config.five_star, pity_enabled=False),
        )
        rule = Rule1(disabled)

        with self.assertRaises(ValueError):
            rule.rarity_probabilities(DrawState(0, 9))
        for six_star_misses in range(rule.max_pity - 1):
            with self.subTest(six_star_misses=six_star_misses):
                self.assertEqual(
                    rule.rarity_probabilities(DrawState(six_star_misses, 0)).five_star,
                    0.08,
                )

    def test_rule_rejects_base_five_probability_that_overflows_reachable_six_rates(self):
        config = load_pool_config()
        overflowing = replace(
            config,
            five_star=replace(config.five_star, base_probability=0.30),
        )

        with self.assertRaises(ValueError):
            Rule1(overflowing)

    def test_bonus_admission_preserves_unreachable_main_base_probability(self):
        config = load_pool_config()
        always_pity = replace(config, five_star=replace(
            config.five_star, base_probability=1.0, hard_pity=1,
        ))
        main_only = Rule1(always_pity, subrules=())
        self.assertEqual(main_only.rarity_probabilities(DrawState()),
                         RarityProbabilities(0.0, 0.992, 0.008))
        with self.assertRaisesRegex(ValueError, "赠送池.*五星.*六星.*不能超过 1"):
            Rule1(always_pity)

    def test_six_star_hard_pity_zeroes_five_star_probability(self):
        config = load_pool_config()
        disabled = replace(
            config,
            five_star=replace(config.five_star, pity_enabled=False),
        )

        for candidate in (config, disabled):
            with self.subTest(pity_enabled=candidate.five_star.pity_enabled):
                self.assertEqual(
                    Rule1(candidate).rarity_probabilities(DrawState(79, 0)),
                    RarityProbabilities(0.0, 0.0, 1.0),
                )

    def test_rule_allows_overlapping_base_rate_when_every_draw_has_five_star_pity(self):
        config = load_pool_config()
        always_pity = replace(
            config,
            five_star=replace(
                config.five_star,
                base_probability=0.30,
                hard_pity=1,
            ),
        )

        try:
            probabilities = Rule1(always_pity).rarity_probabilities(DrawState(78, 0))
        except ValueError as error:
            self.fail(f"unused base five-star probability was rejected: {error}")
        self.assertEqual(probabilities.four_star, 0.0)
        self.assertAlmostEqual(probabilities.five_star, 0.292)
        self.assertAlmostEqual(probabilities.six_star, 0.708)


if __name__ == "__main__":
    unittest.main()
