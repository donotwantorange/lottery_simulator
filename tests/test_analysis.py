from dataclasses import replace
from fractions import Fraction
from itertools import product
import unittest

from lottery_simulator.analysis import (
    PoolExpectations,
    distribution_stats,
    expected_bonus_six_stars,
    expected_six_stars,
    expected_pool_results,
    expected_simulation_results,
    waiting_time_distribution,
)
from lottery_simulator.control import SimulationCancelled
from lottery_simulator.rules.base import DrawState, RarityProbabilities
from lottery_simulator.rules.pool_config import FiveStarPolicy, RewardRule, SixStarCharacter
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


def enumerate_pool_expectations(draws, initial, config):
    """Exact path weights from the specification, independent of rule methods."""
    expected = {"4": Fraction(0), "5": Fraction(0), "6": Fraction(0)}
    base_five = Fraction(str(config.five_star.base_probability))
    for outcomes in product((4, 5, 6), repeat=draws):
        state = initial
        weight = Fraction(1)
        for rarity in outcomes:
            pull = state.misses_since_six_star + 1
            if pull == 80:
                six = Fraction(1)
            elif pull >= 66:
                six = Fraction(8, 1000) + (pull - 65) * Fraction(5, 100)
            else:
                six = Fraction(8, 1000)
            five_pity = (
                config.five_star.pity_enabled
                and state.misses_since_five_or_higher
                == config.five_star.hard_pity - 1
            )
            five = 0 if six == 1 else 1 - six if five_pity else base_five
            probabilities = {4: 1 - six - five, 5: five, 6: six}
            weight *= probabilities[rarity]
            if weight == 0:
                break
            state = (
                DrawState(0, 0) if rarity == 6 else
                DrawState(state.misses_since_six_star + 1,
                          0 if rarity == 5 or not config.five_star.pity_enabled else
                          state.misses_since_five_or_higher + 1)
            )
        for rarity in outcomes:
            expected[str(rarity)] += weight
    return {rarity: float(value) for rarity, value in expected.items()}


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_distribution_is_complete(self):
        probabilities = waiting_time_distribution(self.rule)
        self.assertEqual(len(probabilities), 80)
        self.assertAlmostEqual(sum(probabilities), 1.0, places=12)
        self.assertAlmostEqual(probabilities[-1], 0.00029933681818068074)

    def test_pool_expectation_can_be_cancelled_deterministically(self):
        with self.assertRaises(SimulationCancelled):
            expected_pool_results(self.rule, 100, cancel_check=lambda: True)

    def test_simulation_expectation_forwards_cancellation_to_main_pool(self):
        checks = 0

        def cancelled_after_the_simulation_entry():
            nonlocal checks
            checks += 1
            return checks == 2

        with self.assertRaises(SimulationCancelled):
            expected_simulation_results(
                self.rule, 100, cancel_check=cancelled_after_the_simulation_entry,
            )

    def test_waiting_distribution_does_not_advance_five_star_state(self):
        class NoAdvanceRule(Rule1):
            def advance(self, *args):
                raise AssertionError("waiting time must not use old advance")

            def advance_rarity(self, *args):
                raise AssertionError("waiting time must not invent a rarity")

        values = waiting_time_distribution(NoAdvanceRule(), initial_pity=64)
        self.assertEqual(len(values), 16)
        self.assertAlmostEqual(sum(values), 1.0, places=12)
        self.assertAlmostEqual(values[0], 0.008, places=12)
        self.assertAlmostEqual(values[1], 0.992 * 0.058, places=12)

    def test_waiting_distribution_matches_independent_direct_product(self):
        for initial_pity in (0, 64, 65, 78, 79):
            survival = Fraction(1)
            expected = []
            for misses in range(initial_pity, 80):
                probability = (
                    Fraction(1) if misses == 79 else
                    Fraction(8, 1000) + max(0, misses - 64) * Fraction(5, 100)
                )
                expected.append(float(survival * probability))
                survival *= 1 - probability
            with self.subTest(initial_pity=initial_pity):
                actual = waiting_time_distribution(self.rule, initial_pity)
                self.assertEqual(len(actual), 80 - initial_pity)
                for probability, reference in zip(actual, expected):
                    self.assertAlmostEqual(probability, reference, places=12)
                self.assertAlmostEqual(sum(actual), 1.0, places=12)

    def test_theory_uses_explicit_hard_pity_flag(self):
        class NoHardFlagRule(Rule1):
            def six_star_hard_pity_active(self, state):
                return False

        result = expected_pool_results(NoHardFlagRule(), 1, DrawState(79, 0))
        self.assertEqual(result.rarity_counts["6"], 1.0)
        self.assertEqual(result.pity_triggers["six_star_hard"], 0.0)

    def test_fixed_pool_has_no_complete_cycle_or_six_star_hard_pity(self):
        for probability in (0.008, 1.0):
            rule = Rule1(fixed_six_star_probability=probability, subrules=())
            with self.subTest(probability=probability):
                for analysis in (waiting_time_distribution, distribution_stats):
                    with self.assertRaisesRegex(ValueError, "fixed"):
                        analysis(rule)
                result = expected_pool_results(rule, 2, DrawState(79, 0))
                self.assertAlmostEqual(result.rarity_counts["6"], 2 * probability)
                self.assertEqual(result.pity_triggers["six_star_hard"], 0.0)

    def test_finite_six_star_expectation_uses_real_rarity_transitions(self):
        class NoAdvanceRule(Rule1):
            def advance(self, *args):
                raise AssertionError("finite expectation must not use old advance")

        self.assertAlmostEqual(expected_six_stars(NoAdvanceRule(), 2, 78),
                               enumerate_rule_1_expectation(2, 78), places=12)

    def test_old_advance_interface_is_removed(self):
        self.assertFalse(hasattr(self.rule, "advance"))

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

    def test_double_state_dp_matches_independent_exhaustive_outcomes(self):
        for initial in (
            DrawState(0, 0), DrawState(64, 8), DrawState(65, 9),
            DrawState(78, 8), DrawState(79, 9),
            *(DrawState(six, five) for six in (0, 64, 65, 78) for five in (0, 9)),
        ):
            for draws in range(1, 6):
                with self.subTest(initial=initial, draws=draws):
                    actual = expected_pool_results(self.rule, draws, initial)
                    expected = enumerate_pool_expectations(draws, initial, self.rule.config)
                    self.assertIsInstance(actual, PoolExpectations)
                    self.assertEqual(actual.rarity_counts.keys(), expected.keys())
                    for rarity in ("4", "5", "6"):
                        self.assertAlmostEqual(actual.rarity_counts[rarity],
                                               expected[rarity], places=12)

    def test_double_state_dp_handles_disabled_and_custom_five_star_pity(self):
        for policy, initial in (
            (FiveStarPolicy(0.03, False, 10), DrawState(65, 0)),
            (FiveStarPolicy(0.02, True, 2), DrawState(64, 1)),
            (FiveStarPolicy(0.08, True, 1), DrawState(79, 0)),
        ):
            rule = Rule1(config=replace(self.rule.config, five_star=policy))
            with self.subTest(policy=policy):
                actual = expected_pool_results(rule, 5, initial)
                expected = enumerate_pool_expectations(5, initial, rule.config)
                for rarity in ("4", "5", "6"):
                    self.assertAlmostEqual(actual.rarity_counts[rarity],
                                           expected[rarity], places=12)

    def test_pool_expectations_derive_default_characters_categories_and_rewards(self):
        actual = expected_pool_results(self.rule, 80)
        rarities = actual.rarity_counts
        self.assertAlmostEqual(sum(rarities.values()), 80, places=10)
        self.assertAlmostEqual(sum(actual.character_counts.values()), rarities["6"])
        self.assertAlmostEqual(sum(actual.six_star_categories.values()), rarities["6"])
        self.assertAlmostEqual(actual.six_star_categories["up"], rarities["6"] / 2)
        self.assertAlmostEqual(actual.six_star_categories["other_limited"], rarities["6"] / 8)
        self.assertAlmostEqual(actual.six_star_categories["standard"], rarities["6"] * 3 / 8)
        for name, count in actual.character_counts.items():
            self.assertAlmostEqual(count, rarities["6"] / (2 if name == "UP-A" else 16))
        self.assertAlmostEqual(actual.rewards["奖励A"],
                               rarities["4"] + 5 * rarities["5"] + 25 * rarities["6"])
        self.assertAlmostEqual(actual.rewards["奖励B"],
                               2 * rarities["5"] + 10 * rarities["6"])

    def test_pool_expectations_use_configured_character_weights_and_rewards(self):
        config = replace(
            self.rule.config,
            up_share=0.6,
            six_star_characters=(
                SixStarCharacter("up1", True, True, 1),
                SixStarCharacter("up2", True, True, 2),
                SixStarCharacter("limited", False, True),
                SixStarCharacter("standard", False, False),
            ),
            rewards=(RewardRule("custom", 0.5, 3, 7),),
        )
        actual = expected_pool_results(Rule1(config=config), 1)
        for name, expected in {"up1": 0.0016, "up2": 0.0032,
                               "limited": 0.0016, "standard": 0.0016}.items():
            self.assertAlmostEqual(actual.character_counts[name], expected)
        self.assertAlmostEqual(actual.six_star_categories["up"], 0.0048)
        self.assertAlmostEqual(actual.six_star_categories["other_limited"], 0.0016)
        self.assertAlmostEqual(actual.six_star_categories["standard"], 0.0016)
        self.assertAlmostEqual(actual.rewards["custom"], 0.752)

    def test_pity_trigger_expectations_count_pre_draw_state_including_six_stars(self):
        # From (78, 8), a first 4-star reaches both guarantees; a 5-star
        # reaches only the 6-star guarantee. Six-star probability is 0.708.
        cases = (
            (DrawState(65, 9), 1, 1.0, 0.0),
            (DrawState(79, 9), 1, 1.0, 1.0),
            (DrawState(78, 8), 2, float(Fraction(212, 1000)), float(Fraction(292, 1000))),
            (DrawState(), 10, float(Fraction(912, 1000) ** 9), 0.0),
        )
        for initial, draws, five, six in cases:
            with self.subTest(initial=initial, draws=draws):
                actual = expected_pool_results(self.rule, draws, initial)
                self.assertEqual(set(actual.pity_triggers), {"five_star", "six_star_hard"})
                self.assertAlmostEqual(actual.pity_triggers["five_star"], five, places=12)
                self.assertAlmostEqual(actual.pity_triggers["six_star_hard"], six, places=12)

    def test_five_star_pity_does_not_change_six_star_waiting_analysis(self):
        disabled = Rule1(config=replace(
            self.rule.config, five_star=replace(self.rule.config.five_star, pity_enabled=False)
        ))
        self.assertEqual(waiting_time_distribution(self.rule), waiting_time_distribution(disabled))
        for initial in (DrawState(), DrawState(65, 9)):
            with self.subTest(initial=initial):
                actual = expected_pool_results(self.rule, 80, initial)
                self.assertAlmostEqual(actual.rarity_counts["6"],
                                       expected_six_stars(self.rule, 80, initial.misses_since_six_star),
                                       places=12)
        self.assertEqual(expected_pool_results(disabled, 80).pity_triggers["five_star"], 0.0)

    def test_simulation_expectations_include_one_independent_bonus_only_when_crossing_thirty(self):
        bonus_five = Fraction(8, 10) + Fraction(912, 1000) ** 10
        expected_bonus = {"4": float(Fraction(10) - bonus_five - Fraction(8, 100)),
                          "5": float(bonus_five), "6": 0.08}
        for draws, initial, five_initial, receives_bonus in (
            (29, 0, 0, False), (30, 0, 0, True),
            (1, 29, 9, True), (1, 30, 9, False), (61, 29, 8, True),
        ):
            with self.subTest(draws=draws, initial=initial, five_initial=five_initial):
                actual = expected_simulation_results(self.rule, draws, initial, five_initial)
                self.assertEqual(set(actual), {"main", "bonus", "total"})
                main_expected = expected_pool_results(self.rule, draws, DrawState(initial, five_initial))
                self.assertEqual(actual["main"], main_expected)
                for rarity in ("4", "5", "6"):
                    self.assertAlmostEqual(actual["bonus"].rarity_counts[rarity],
                                           expected_bonus[rarity] if receives_bonus else 0.0,
                                           places=12)
                self.assertAlmostEqual(actual["bonus"].pity_triggers["five_star"],
                                       float(Fraction(912, 1000) ** 9) if receives_bonus else 0.0,
                                       places=12)
                self.assertEqual(actual["bonus"].pity_triggers["six_star_hard"], 0.0)
                for field in ("rarity_counts", "six_star_categories", "character_counts", "rewards", "pity_triggers"):
                    for name, total in getattr(actual["total"], field).items():
                        self.assertAlmostEqual(total, getattr(actual["main"], field)[name]
                                               + getattr(actual["bonus"], field)[name])

    def test_simulation_expectations_honor_absent_bonus_and_disabled_main_pity(self):
        rule = Rule1(subrules=())
        self.assertEqual(expected_simulation_results(rule, 30)["bonus"].rarity_counts,
                         {"4": 0.0, "5": 0.0, "6": 0.0})
        disabled = Rule1(config=replace(
            self.rule.config, five_star=replace(self.rule.config.five_star, pity_enabled=False)
        ))
        actual = expected_simulation_results(disabled, 30)
        self.assertEqual(actual["main"].pity_triggers["five_star"], 0.0)
        self.assertAlmostEqual(actual["bonus"].pity_triggers["five_star"],
                               float(Fraction(912, 1000) ** 9), places=12)

    def test_new_analysis_rejects_invalid_draws_and_initial_states(self):
        for draws in (0, -1, True, 1.5):
            with self.subTest(draws=draws):
                with self.assertRaises(ValueError):
                    expected_pool_results(self.rule, draws)
                with self.assertRaises(ValueError):
                    expected_simulation_results(self.rule, draws)
        for initial in (DrawState(-1, 0), DrawState(80, 0), DrawState(0, -1), DrawState(0, 10)):
            with self.subTest(initial=initial):
                with self.assertRaises(ValueError):
                    expected_pool_results(self.rule, 1, initial)
                with self.assertRaises(ValueError):
                    expected_simulation_results(self.rule, 1, initial.misses_since_six_star,
                                                initial.misses_since_five_or_higher)

    def test_pool_analysis_rejects_invalid_probabilities_in_reached_states(self):
        for probabilities in (
            RarityProbabilities(-0.1, 0.1, 1.0),
            RarityProbabilities(0.5, 0.8, 0.2),
            RarityProbabilities(0.9, float("nan"), 0.1),
            RarityProbabilities(0.9, 0.1, float("inf")),
        ):
            class InvalidRarityRule(Rule1):
                def rarity_probabilities(self, state):
                    if state.misses_since_six_star == 1:
                        return probabilities
                    return super().rarity_probabilities(state)

            with self.subTest(probabilities=probabilities):
                with self.assertRaisesRegex(ValueError, "probabilit"):
                    expected_pool_results(InvalidRarityRule(), 2)

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
