from dataclasses import replace
import unittest
from unittest.mock import patch

from lottery_simulator.engine import draw_once, simulate
from lottery_simulator.rules.base import (
    BonusEvent,
    DrawState,
    expected_bonus_draws,
)
from lottery_simulator.rules.first_thirty_bonus import FirstThirtyBonusRule
from lottery_simulator.rules.pool_config import WeightedCharacter, load_pool_config
from lottery_simulator.rules.rule_1 import Rule1


class ConstantRandom:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


class FirstThirtyBonusRuleTest(unittest.TestCase):
    def test_expected_draws_counts_a_trigger_crossed_by_future_main_draws(self):
        subrule = FirstThirtyBonusRule()

        self.assertEqual(subrule.expected_draws(29, 1), 10)
        self.assertEqual(subrule.expected_draws(30, 1), 0)
        self.assertEqual(subrule.expected_draws(0, 29), 0)
        self.assertEqual(subrule.expected_draws(0, 30), 10)

    def test_expected_draws_rejects_invalid_initial_position_or_draw_count(self):
        subrule = FirstThirtyBonusRule()

        for initial_main_draws in (-1, True, 1.5, "0"):
            with self.subTest(initial_main_draws=initial_main_draws):
                with self.assertRaises(ValueError):
                    subrule.expected_draws(initial_main_draws, 1)
        for draws in (0, -1, True, 1.5, "1"):
            with self.subTest(draws=draws):
                with self.assertRaises(ValueError):
                    subrule.expected_draws(0, draws)

    def test_expected_bonus_draws_sums_subrules_and_allows_no_subrules(self):
        self.assertEqual(expected_bonus_draws(Rule1(), 29, 1), 10)
        self.assertEqual(expected_bonus_draws(Rule1(subrules=()), 29, 1), 0)

    def test_expected_bonus_draws_rejects_unknown_subrule_capability(self):
        class EventsOnlySubRule:
            def events_after_main_draw(self, completed_main_draws):
                return ()

        rule = Rule1(subrules=(EventsOnlySubRule(),))
        with self.assertRaisesRegex(ValueError, "expected_draws"):
            expected_bonus_draws(rule, 0, 1)

    def test_expected_draws_uses_event_draw_count_from_trigger_logic(self):
        subrule = FirstThirtyBonusRule()
        original = subrule.events_after_main_draw

        def custom_events(completed_main_draws):
            if completed_main_draws == 30:
                return (BonusEvent("custom", 7, 0.2, 4),)
            return original(completed_main_draws)

        subrule.events_after_main_draw = custom_events
        self.assertEqual(subrule.expected_draws(29, 1), 7)

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

    def test_bonus_has_no_six_star_hard_pity(self):
        rule = Rule1(fixed_six_star_probability=0.008, subrules=())
        self.assertFalse(rule.six_star_hard_pity_active(DrawState(79, 0)))
        self.assertTrue(Rule1().six_star_hard_pity_active(DrawState(79, 0)))

    def test_fixed_pool_allows_six_star_misses_past_main_pool_limit(self):
        rule = Rule1(fixed_six_star_probability=0.008, subrules=())
        for misses in (79, 80, 1000):
            with self.subTest(misses=misses):
                state = DrawState(misses, 0)
                self.assertEqual(rule.probability(state), 0.008)
                self.assertFalse(rule.six_star_hard_pity_active(state))
                self.assertEqual(rule.advance_rarity(state, 4), DrawState(misses + 1, 1))
                self.assertEqual(rule.advance_rarity(state, 5), DrawState(misses + 1, 0))
                self.assertEqual(rule.advance_rarity(state, 6), DrawState())
                self.assertEqual(rule.character_probabilities(4, state), {})
        for state in (DrawState(-1, 0), DrawState(80, 10)):
            with self.assertRaises(ValueError):
                rule.rarity_probabilities(state)
        disabled_config = replace(
            rule.config, five_star=replace(rule.config.five_star, pity_enabled=False),
        )
        disabled = Rule1(disabled_config, fixed_six_star_probability=0.008, subrules=())
        self.assertEqual(disabled.advance_rarity(DrawState(80, 0), 4), DrawState(81, 0))
        with self.assertRaises(ValueError):
            disabled.rarity_probabilities(DrawState(80, 1))

    def test_bonus_inherits_all_lists_rewards_and_up(self):
        config = load_pool_config()
        config = replace(
            config, up_share=0.7,
            five_star=replace(config.five_star, pity_enabled=False, hard_pity=3),
            four_star_characters=(WeightedCharacter("四星A"),),
            five_star_characters=(WeightedCharacter("五星A"),),
        )
        main = Rule1(config)
        event = FirstThirtyBonusRule().events_after_main_draw(30)[0]
        temporary = main.for_bonus(event)
        for field in ("four_star_characters", "five_star_characters",
                      "six_star_characters", "rewards"):
            self.assertIs(getattr(temporary.config, field), getattr(config, field))
        self.assertEqual(temporary.config.up_share, 0.7)
        self.assertTrue(temporary.config.five_star.pity_enabled)
        self.assertEqual(temporary.config.five_star.hard_pity, 10)
        self.assertEqual(temporary.subrules, ())
        temporary.advance_rarity(DrawState(80, 9), 5)
        self.assertEqual(main.probability(DrawState(79, 0)), 1.0)
        self.assertFalse(main.config.five_star.pity_enabled)
        self.assertEqual(main.config.five_star.hard_pity, 3)

    def test_real_bonus_draw_chain_keeps_main_state_and_inherits_names(self):
        config = replace(load_pool_config(),
                         four_star_characters=(WeightedCharacter("四星A"),),
                         five_star_characters=(WeightedCharacter("五星A"),))
        # A high roll produces main 4/5, bonus nine fours then pity five.
        with patch("lottery_simulator.engine.random.Random", return_value=ConstantRandom(0.999)):
            result = simulate(Rule1(config), 2, seed=42, initial_pity=29,
                              initial_five_star_pity=8, collect_records=True)
        first_main, *middle, last_main = result.records
        self.assertTrue(hasattr(first_main, "draw_result"), "Trace must nest source draw state")
        self.assertEqual(first_main.main_state_before, DrawState(29, 8))
        self.assertEqual(first_main.main_state_after, DrawState(30, 9))
        self.assertEqual(first_main.draw_result.state_before, first_main.main_state_before)
        self.assertEqual(first_main.draw_result.state_after, first_main.main_state_after)
        self.assertEqual(len(middle), 10)
        for index, record in enumerate(middle):
            self.assertEqual(record.source, "bonus")
            self.assertEqual(record.main_draws_completed, 30)
            self.assertEqual(record.main_state_before, DrawState(30, 9))
            self.assertEqual(record.main_state_after, DrawState(30, 9))
            self.assertEqual(record.draw_result.state_before, DrawState(index, index))
            self.assertEqual(record.draw_result.state_after,
                             DrawState(index + 1, index + 1 if index < 9 else 0))
            self.assertEqual(record.draw_result.outcome.character_name,
                             "四星A" if index < 9 else "五星A")
        self.assertEqual(last_main.main_state_before, DrawState(30, 9))
        self.assertEqual(last_main.main_state_after, DrawState(31, 0))
        self.assertEqual(last_main.draw_result.outcome.rarity, 5)
        self.assertEqual(last_main.main_draws_completed, 31)

    def test_temporary_pool_guarantees_at_least_five_star_in_ten_draws(self):
        temporary = Rule1().for_bonus(
            FirstThirtyBonusRule().events_after_main_draw(30)[0]
        )
        state = DrawState()
        rarities = []
        rng = ConstantRandom(0.999)

        for _ in range(10):
            result = draw_once(temporary, state, rng)
            state = result.state_after
            rarities.append(result.outcome.rarity)

        self.assertEqual(rarities, [4] * 9 + [5])


if __name__ == "__main__":
    unittest.main()
