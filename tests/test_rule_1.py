from dataclasses import replace
import unittest

from lottery_simulator.rules.base import DrawState, RarityProbabilities
from lottery_simulator.rules.pool_config import WeightedCharacter, load_pool_config
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
            self.rule.advance_rarity(DrawState(64, 8), 6), DrawState(0, 0)
        )

    def test_four_star_advances_both_counters(self):
        self.assertEqual(
            self.rule.advance_rarity(DrawState(63, 8), 4), DrawState(64, 9)
        )

    def test_invalid_states_are_rejected(self):
        for misses in (-1, 80):
            with self.subTest(misses=misses):
                with self.assertRaises(ValueError):
                    self.rule.probability(DrawState(misses))

    def test_missing_guaranteed_pull_is_rejected(self):
        with self.assertRaises(ValueError):
            self.rule.advance_rarity(DrawState(79), 4)

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

    def test_five_star_pity_cannot_return_four_star(self):
        with self.assertRaises(ValueError):
            self.rule.advance_rarity(DrawState(0, 9), 4)

    def test_six_star_hard_pity_cannot_return_lower_rarities(self):
        for rarity in (4, 5):
            with self.subTest(rarity=rarity):
                with self.assertRaises(ValueError):
                    self.rule.advance_rarity(DrawState(79, 0), rarity)
        self.assertEqual(self.rule.advance_rarity(DrawState(79, 9), 6), DrawState())

    def test_advance_rarity_rejects_invalid_rarities(self):
        for rarity in (True, False, 3, 7, 4.0, "6", None):
            with self.subTest(rarity=rarity):
                with self.assertRaises(ValueError):
                    self.rule.advance_rarity(DrawState(), rarity)

    def test_advance_rarity_rejects_zero_probability_outside_pity(self):
        config = self.rule.config
        no_fives = Rule1(replace(
            config, five_star=replace(config.five_star, base_probability=0.0),
        ), subrules=())
        no_sixes = Rule1(fixed_six_star_probability=0.0, subrules=())
        for rule, rarity in ((no_fives, 5), (no_sixes, 6)):
            with self.subTest(rarity=rarity):
                with self.assertRaises(ValueError):
                    rule.advance_rarity(DrawState(), rarity)

    def test_explicit_six_star_hard_pity_uses_pool_kind_not_probability(self):
        fixed = Rule1(fixed_six_star_probability=1.0, subrules=())
        for misses in (0, 78, 79):
            with self.subTest(misses=misses):
                self.assertEqual(
                    self.rule.six_star_hard_pity_active(DrawState(misses)),
                    misses == 79,
                )
                self.assertFalse(fixed.six_star_hard_pity_active(DrawState(misses)))

    def test_character_probabilities_preserve_config_order_and_weights(self):
        config = replace(
            self.rule.config,
            four_star_characters=(WeightedCharacter("B", 3), WeightedCharacter("A")),
            five_star_characters=(WeightedCharacter("A"),),
        )
        rule = Rule1(config)
        for state in (DrawState(), DrawState(79, 9)):
            with self.subTest(state=state):
                fours = rule.character_probabilities(4, state)
                self.assertEqual(list(fours.items()), [("B", 0.75), ("A", 0.25)])
                self.assertEqual(rule.character_probabilities(5, state), {"A": 1.0})
                self.assertAlmostEqual(rule.character_probabilities(6, state)["UP-A"], 0.5)
        for rarity in (4, 5):
            self.assertEqual(self.rule.character_probabilities(rarity, DrawState()), {})
        with self.assertRaises(ValueError):
            rule.character_probabilities(3, DrawState())

    def test_all_state_interfaces_reject_invalid_counts(self):
        calls = (
            self.rule.probability, self.rule.rarity_probabilities,
            self.rule.five_star_pity_active, self.rule.six_star_hard_pity_active,
            lambda state: self.rule.character_probabilities(4, state),
            lambda state: self.rule.advance_rarity(state, 6),
        )
        for state in (DrawState(True, 0), DrawState(0, False),
                      DrawState(0.5, 0), DrawState(0, 1.0)):
            for call in calls:
                with self.subTest(state=state, call=call):
                    with self.assertRaises(TypeError):
                        call(state)
        for state in (DrawState(-1, 0), DrawState(80, 0),
                      DrawState(0, -1), DrawState(0, 10)):
            for call in calls:
                with self.subTest(state=state, call=call):
                    with self.assertRaises(ValueError):
                        call(state)

    def test_four_star_remainder_only_clamps_rounding_error(self):
        class ControlledSixRate(Rule1):
            def probability(self, state):
                self._validate(state)
                return self.six_rate

        rule = ControlledSixRate(subrules=())
        rule.six_rate = 0.92 + 5e-13
        self.assertEqual(rule.rarity_probabilities(DrawState()).four_star, 0.0)
        rule.six_rate = 0.92 + 2e-12
        with self.assertRaises(ValueError):
            rule.rarity_probabilities(DrawState())

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
