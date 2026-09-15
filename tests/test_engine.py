from dataclasses import astuple, replace
import unittest
from unittest.mock import patch

from lottery_simulator.engine import (
    DrawOutcome,
    DrawRecord,
    SimulationCancelled,
    SimulationResult,
    draw_once,
    simulate,
)
from lottery_simulator.rules.base import BonusEvent, DrawState, RarityProbabilities
from lottery_simulator.rules.pool_config import RewardRule
from lottery_simulator.rules.rule_1 import Rule1


class SequenceRandom:
    def __init__(self, values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class NoEarlySixRule(Rule1):
    def probability(self, state):
        super().probability(state)
        return 1.0 if state.misses_since_six_star == 79 else 0.0


class GuaranteedTwoDrawBonus:
    def events_after_main_draw(self, completed_main_draws):
        if completed_main_draws == 1:
            return (BonusEvent("guaranteed_test_bonus", 2, 1.0, 10),)
        return ()


class GuaranteedBonusRule(NoEarlySixRule):
    subrules = (GuaranteedTwoDrawBonus(),)


class AlwaysSixRule(Rule1):
    def probability(self, state):
        super().probability(state)
        return 1.0


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_fixed_seed_is_reproducible(self):
        first = simulate(self.rule, draws=100, trials=1, seed=42)
        second = simulate(self.rule, draws=100, trials=1, seed=42)
        self.assertEqual(first, second)

    def test_draw_once_returns_rarity_character_rewards_and_state(self):
        outcome, state_after, probabilities = draw_once(
            Rule1(), DrawState(9, 9), SequenceRandom((0.0, 0.0))
        )
        self.assertEqual(outcome.rarity, 6)
        self.assertEqual(outcome.six_star_character, "UP-A")
        self.assertTrue(outcome.is_up)
        self.assertTrue(outcome.is_limited)
        self.assertTrue(outcome.five_star_pity_triggered)
        self.assertEqual(outcome.rewards, {"奖励A": 25.0, "奖励B": 10.0})
        self.assertAlmostEqual(sum(astuple(probabilities)), 1.0)
        self.assertEqual(state_after, DrawState(0, 0))

    def test_draw_once_returns_four_and_five_star_outcomes(self):
        cases = (
            (
                0.5,
                DrawOutcome(4, None, False, False, {"奖励A": 1.0, "奖励B": 0.0}, False, False),
                DrawState(1, 1),
            ),
            (
                0.05,
                DrawOutcome(5, None, False, False, {"奖励A": 5.0, "奖励B": 2.0}, False, False),
                DrawState(1, 0),
            ),
        )
        for roll, expected_outcome, expected_state in cases:
            with self.subTest(rarity=expected_outcome.rarity):
                outcome, state_after, probabilities = draw_once(
                    Rule1(), DrawState(), SequenceRandom((roll,))
                )
                self.assertEqual(outcome, expected_outcome)
                self.assertEqual(state_after, expected_state)
                self.assertAlmostEqual(sum(astuple(probabilities)), 1.0)

    def test_draw_once_marks_six_star_hard_pity(self):
        outcome, state_after, _ = draw_once(
            Rule1(), DrawState(79, 0), SequenceRandom((0.99, 0.0))
        )

        self.assertEqual(outcome.rarity, 6)
        self.assertTrue(outcome.six_star_hard_pity_triggered)
        self.assertEqual(state_after, DrawState(0, 0))

    def test_single_trial_keeps_trace(self):
        result = simulate(self.rule, draws=3, trials=1, seed=42)
        self.assertEqual(len(result.records), 3)
        self.assertEqual(result.records[0].pity_position, 1)
        self.assertEqual(sum(result.count_distribution.values()), 1)

    def test_large_single_trial_can_explicitly_skip_record_collection(self):
        result = simulate(
            self.rule, draws=100_001, trials=1, seed=42, collect_records=False
        )

        self.assertEqual(result.records, ())
        self.assertEqual(result.total_draws, 100_011)
        self.assertEqual(result.source_summaries["total"]["draws"], 100_011)
        self.assertEqual(sum(result.count_distribution.values()), 1)

    def test_structured_aggregates_conserve_draws_characters_and_rewards(self):
        result = simulate(
            Rule1(), draws=30, trials=20, seed=42, collect_records=False
        )

        self.assertEqual(set(result.source_summaries), {"main", "bonus", "total"})
        for source in ("main", "bonus", "total"):
            summary = result.source_summaries[source]
            self.assertEqual(
                set(summary),
                {
                    "draws",
                    "mean_rarity_counts",
                    "mean_six_star_categories",
                    "mean_character_counts",
                    "mean_rewards",
                    "mean_pity_triggers",
                },
            )
            rarities = summary["mean_rarity_counts"]
            self.assertAlmostEqual(sum(rarities.values()), summary["draws"])
            self.assertAlmostEqual(
                sum(summary["mean_character_counts"].values()), rarities["6"]
            )
            self.assertAlmostEqual(
                summary["mean_rewards"]["奖励A"],
                rarities["4"] + 5 * rarities["5"] + 25 * rarities["6"],
            )
            self.assertAlmostEqual(
                summary["mean_rewards"]["奖励B"],
                2 * rarities["5"] + 10 * rarities["6"],
            )

        main = result.source_summaries["main"]
        bonus = result.source_summaries["bonus"]
        total = result.source_summaries["total"]
        self.assertEqual(total["draws"], main["draws"] + bonus["draws"])
        for field in (
            "mean_rarity_counts",
            "mean_six_star_categories",
            "mean_character_counts",
            "mean_rewards",
            "mean_pity_triggers",
        ):
            for name, value in total[field].items():
                self.assertAlmostEqual(value, main[field][name] + bonus[field][name])
        self.assertEqual(result.records, ())

    def test_theoretical_source_summaries_align_with_simulation_and_legacy_fields(self):
        result = simulate(
            Rule1(), draws=1, trials=2, seed=42,
            initial_pity=29, initial_five_star_pity=9,
        )
        theory = result.theoretical_source_summaries
        self.assertEqual(set(theory), {"main", "bonus", "total"})
        for source in theory:
            self.assertEqual(set(theory[source]), set(result.source_summaries[source]))
            self.assertEqual(theory[source]["draws"], result.source_summaries[source]["draws"])
            for field in theory[source]:
                if field != "draws":
                    self.assertEqual(set(theory[source][field]),
                                     set(result.source_summaries[source][field]))
        self.assertEqual(theory["main"]["mean_rarity_counts"],
                         {"4": 0.0, "5": 0.992, "6": 0.008})
        self.assertEqual(theory["main"]["mean_pity_triggers"],
                         {"five_star": 1.0, "six_star_hard": 0.0})
        self.assertAlmostEqual(theory["main"]["mean_character_counts"]["UP-A"], 0.004)
        self.assertAlmostEqual(theory["main"]["mean_six_star_categories"]["other_limited"], 0.001)
        self.assertAlmostEqual(theory["main"]["mean_rewards"]["奖励A"], 5.16)
        self.assertAlmostEqual(theory["bonus"]["mean_rarity_counts"]["5"], 0.8 + 0.912 ** 10)
        self.assertAlmostEqual(theory["bonus"]["mean_pity_triggers"]["five_star"], 0.912 ** 9)
        for field in theory["total"]:
            if field != "draws":
                for name, total in theory["total"][field].items():
                    self.assertAlmostEqual(total, theory["main"][field][name] + theory["bonus"][field][name])
        self.assertEqual(result.theoretical_expected_main_count, theory["main"]["mean_rarity_counts"]["6"])
        self.assertEqual(result.theoretical_expected_bonus_count, theory["bonus"]["mean_rarity_counts"]["6"])
        self.assertEqual(result.theoretical_expected_count, theory["total"]["mean_rarity_counts"]["6"])

    def test_bonus_ten_draws_have_at_least_one_five_or_six_per_trial(self):
        result = simulate(
            Rule1(), draws=30, trials=100, seed=7, collect_records=False
        )

        bonus = result.source_summaries["bonus"]["mean_rarity_counts"]
        self.assertGreaterEqual(round((bonus["5"] + bonus["6"]) * result.trials), 100)

    def test_fixed_seed_structured_result_has_complete_exact_shape(self):
        result = simulate(
            AlwaysSixRule(), draws=1, trials=1, seed=42, collect_records=False
        )
        empty_characters = {
            "UP-A": 0.0,
            "限定-B": 0.0,
            "限定-C": 0.0,
            "常驻-D": 0.0,
            "常驻-E": 0.0,
            "常驻-F": 0.0,
            "常驻-G": 0.0,
            "常驻-H": 0.0,
            "常驻-I": 0.0,
        }
        six_star_characters = dict(empty_characters, **{"UP-A": 1.0})

        self.assertEqual(
            result.source_summaries,
            {
                "main": {
                    "draws": 1,
                    "mean_rarity_counts": {"4": 0.0, "5": 0.0, "6": 1.0},
                    "mean_six_star_categories": {
                        "up": 1.0,
                        "other_limited": 0.0,
                        "standard": 0.0,
                    },
                    "mean_character_counts": six_star_characters,
                    "mean_rewards": {"奖励A": 25.0, "奖励B": 10.0},
                    "mean_pity_triggers": {"five_star": 0.0, "six_star_hard": 0.0},
                },
                "bonus": {
                    "draws": 0,
                    "mean_rarity_counts": {"4": 0.0, "5": 0.0, "6": 0.0},
                    "mean_six_star_categories": {
                        "up": 0.0,
                        "other_limited": 0.0,
                        "standard": 0.0,
                    },
                    "mean_character_counts": empty_characters,
                    "mean_rewards": {"奖励A": 0.0, "奖励B": 0.0},
                    "mean_pity_triggers": {"five_star": 0.0, "six_star_hard": 0.0},
                },
                "total": {
                    "draws": 1,
                    "mean_rarity_counts": {"4": 0.0, "5": 0.0, "6": 1.0},
                    "mean_six_star_categories": {
                        "up": 1.0,
                        "other_limited": 0.0,
                        "standard": 0.0,
                    },
                    "mean_character_counts": six_star_characters,
                    "mean_rewards": {"奖励A": 25.0, "奖励B": 10.0},
                    "mean_pity_triggers": {"five_star": 0.0, "six_star_hard": 0.0},
                },
            },
        )
        self.assertEqual(
            result.source_distributions,
            {
                "main": {
                    "rarity_counts": {
                        "4": {"0": 1},
                        "5": {"0": 1},
                        "6": {"1": 1},
                    },
                    "reward_totals": {
                        "奖励A": {"25.0": 1},
                        "奖励B": {"10.0": 1},
                    },
                },
                "bonus": {
                    "rarity_counts": {
                        "4": {"0": 1},
                        "5": {"0": 1},
                        "6": {"0": 1},
                    },
                    "reward_totals": {
                        "奖励A": {"0.0": 1},
                        "奖励B": {"0.0": 1},
                    },
                },
                "total": {
                    "rarity_counts": {
                        "4": {"0": 1},
                        "5": {"0": 1},
                        "6": {"1": 1},
                    },
                    "reward_totals": {
                        "奖励A": {"25.0": 1},
                        "奖励B": {"10.0": 1},
                    },
                },
            },
        )
        self.assertEqual(
            result.at_least_one_rates,
            {
                "main": {
                    "five_or_higher": 1.0,
                    "six_star": 1.0,
                    "up_six_star": 1.0,
                    "limited_six_star": 1.0,
                },
                "bonus": {
                    "five_or_higher": 0.0,
                    "six_star": 0.0,
                    "up_six_star": 0.0,
                    "limited_six_star": 0.0,
                },
                "total": {
                    "five_or_higher": 1.0,
                    "six_star": 1.0,
                    "up_six_star": 1.0,
                    "limited_six_star": 1.0,
                },
            },
        )
        self.assertEqual(result.initial_five_star_pity, 0)
        self.assertEqual(
            result.pool_config,
            {
                "up_share": 0.5,
                "five_star": {
                    "base_probability": 0.08,
                    "pity_enabled": True,
                    "hard_pity": 10,
                },
                "six_star_characters": [
                    {"name": "UP-A", "is_up": True, "is_limited": True, "up_weight": 1.0},
                    {"name": "限定-B", "is_up": False, "is_limited": True, "up_weight": None},
                    {"name": "限定-C", "is_up": False, "is_limited": True, "up_weight": None},
                    {"name": "常驻-D", "is_up": False, "is_limited": False, "up_weight": None},
                    {"name": "常驻-E", "is_up": False, "is_limited": False, "up_weight": None},
                    {"name": "常驻-F", "is_up": False, "is_limited": False, "up_weight": None},
                    {"name": "常驻-G", "is_up": False, "is_limited": False, "up_weight": None},
                    {"name": "常驻-H", "is_up": False, "is_limited": False, "up_weight": None},
                    {"name": "常驻-I", "is_up": False, "is_limited": False, "up_weight": None},
                ],
                "rewards": [
                    {"name": "奖励A", "four_star": 1.0, "five_star": 5.0, "six_star": 25.0},
                    {"name": "奖励B", "four_star": 0.0, "five_star": 2.0, "six_star": 10.0},
                ],
            },
        )

    def test_reward_distribution_groups_equal_totals_regardless_of_draw_order(self):
        config = replace(
            self.rule.config,
            rewards=(RewardRule("fractional", 0.1, 0.2, 0.3),),
        )

        rule = Rule1(config=config, subrules=())
        rolls = (0.5, 0.05, 0.0, 0.0, 0.0, 0.0, 0.05, 0.5)
        # Character selection consumes the roll immediately after each six-star.
        with patch("lottery_simulator.engine.random.Random", return_value=SequenceRandom(rolls)):
            result = simulate(rule, draws=3, trials=2, seed=42, collect_records=False)
        for trial_rolls, expected in ((rolls[:4], [4, 5, 6]), (rolls[4:], [6, 5, 4])):
            with patch("lottery_simulator.engine.random.Random", return_value=SequenceRandom(trial_rolls)):
                trace = simulate(rule, draws=3, trials=1, seed=42)
            self.assertEqual([record.rarity for record in trace.records], expected)

        for source in ("main", "total"):
            distribution = result.source_distributions[source]
            self.assertEqual(
                distribution["rarity_counts"],
                {"4": {"1": 2}, "5": {"1": 2}, "6": {"1": 2}},
            )
            reward_buckets = distribution["reward_totals"]["fractional"]
            self.assertEqual(len(reward_buckets), 1)
            self.assertEqual(sum(reward_buckets.values()), 2)
            self.assertAlmostEqual(float(next(iter(reward_buckets))), 0.6)

    def test_trace_inserts_structured_bonus_records_after_main_draw_thirty(self):
        result = simulate(Rule1(), draws=30, trials=1, seed=42)

        self.assertEqual(
            [record.source for record in result.records[29:]],
            ["main"] + ["bonus"] * 10,
        )
        main_state_at_thirty = result.records[29].state_after
        for record in result.records:
            self.assertIn(record.rarity, (4, 5, 6))
            self.assertEqual(record.is_six_star, record.rarity == 6)
            self.assertEqual(record.six_star_character is not None, record.rarity == 6)
            self.assertIsInstance(record.is_up, bool)
            self.assertIsInstance(record.is_limited, bool)
            self.assertEqual(set(record.rewards), {"奖励A", "奖励B"})
            self.assertAlmostEqual(sum(astuple(record.rarity_probabilities)), 1.0)
            self.assertIsInstance(record.five_star_pity_triggered, bool)
            self.assertIsInstance(record.six_star_hard_pity_triggered, bool)
        for record in result.records[30:]:
            self.assertEqual(record.state_after, main_state_at_thirty)
            self.assertIsNotNone(record.source_state_before)
            self.assertIsNotNone(record.source_state_after)

    def test_multiple_trials_only_keep_aggregates(self):
        result = simulate(self.rule, draws=100, trials=50, seed=42)
        self.assertEqual(result.records, ())
        self.assertEqual(sum(result.count_distribution.values()), 50)
        self.assertEqual(result.theoretical_expected_count > 0, True)

    def test_initial_pity_is_applied(self):
        result = simulate(self.rule, draws=1, trials=1, seed=1, initial_pity=79)
        self.assertTrue(result.records[0].is_six_star)
        self.assertEqual(result.records[0].rarity, 6)
        self.assertEqual(result.records[0].probability, 1.0)
        self.assertTrue(result.records[0].six_star_hard_pity_triggered)
        self.assertEqual(result.records[0].state_after.misses_since_six_star, 0)

    def test_bonus_records_are_inserted_without_changing_main_pity(self):
        result = simulate(NoEarlySixRule(), draws=31, trials=1, seed=42)

        bonus_records = [record for record in result.records if record.source == "bonus"]
        main_records = [record for record in result.records if record.source == "main"]
        self.assertEqual(result.draws, 31)
        self.assertEqual(result.bonus_draws, 10)
        self.assertEqual(result.total_draws, 41)
        self.assertEqual(len(main_records), 31)
        self.assertEqual([record.source_index for record in bonus_records], list(range(1, 11)))
        self.assertEqual(
            {record.bonus_event for record in bonus_records},
            {"first_thirty_bonus"},
        )
        self.assertEqual(
            {record.state_after.misses_since_six_star for record in bonus_records},
            {30},
        )
        self.assertEqual(main_records[-1].pity_position, 31)

    def test_initial_pity_thirty_means_bonus_was_already_claimed(self):
        result = simulate(self.rule, draws=1, trials=1, seed=42, initial_pity=30)

        self.assertEqual(result.bonus_draws, 0)
        self.assertEqual(result.total_draws, 1)
        self.assertEqual(len(result.records), 1)

    def test_early_main_six_stars_do_not_delay_the_draw_thirty_bonus(self):
        result = simulate(AlwaysSixRule(), draws=30, trials=1, seed=42)

        self.assertEqual(result.mean_main_six_stars, 30.0)
        self.assertEqual(result.bonus_draws, 10)

    def test_main_bonus_and_total_six_stars_are_aggregated_separately(self):
        result = simulate(GuaranteedBonusRule(), draws=1, trials=3, seed=42)

        self.assertEqual(result.mean_main_six_stars, 0.0)
        self.assertEqual(result.mean_bonus_six_stars, 2.0)
        self.assertEqual(result.mean_six_stars, 2.0)
        self.assertEqual(result.theoretical_expected_main_count, 0.0)
        self.assertEqual(result.theoretical_expected_bonus_count, 2.0)
        self.assertEqual(result.theoretical_expected_count, 2.0)
        self.assertEqual(result.count_distribution, {2: 3})

    def test_bonus_six_star_does_not_reset_main_pity(self):
        result = simulate(GuaranteedBonusRule(), draws=2, trials=1, seed=42)

        bonus_records = [record for record in result.records if record.source == "bonus"]
        main_records = [record for record in result.records if record.source == "main"]
        self.assertTrue(all(record.is_six_star for record in bonus_records))
        self.assertEqual(
            {record.state_after.misses_since_six_star for record in bonus_records},
            {1},
        )
        self.assertEqual(main_records[1].pity_position, 2)

    def test_bonus_records_do_not_change_main_double_pity(self):
        result = simulate(
            Rule1(), draws=2, trials=1, seed=42,
            initial_pity=29, initial_five_star_pity=8,
            collect_records=True,
        )
        bonus = [record for record in result.records if record.source == "bonus"]

        self.assertEqual(len(bonus), 10)
        self.assertEqual(result.initial_five_star_pity, 8)
        self.assertEqual(len({record.state_after for record in bonus}), 1)
        self.assertEqual(bonus[0].source_state_before, DrawState())
        self.assertTrue(any(
            record.source_state_after.misses_since_five_or_higher == 0
            for record in bonus
        ))

    def test_main_draw_counter_advances_only_for_main_draws(self):
        result = simulate(
            NoEarlySixRule(), draws=2, trials=1, seed=42, initial_pity=29
        )

        self.assertEqual(result.initial_main_draws, 29)
        self.assertEqual(result.final_main_draws, 31)
        self.assertEqual(
            [record.main_draws_completed for record in result.records],
            [30] + [30] * 10 + [31],
        )

    def test_omitted_seed_is_returned(self):
        result = simulate(self.rule, draws=1)
        self.assertIsInstance(result.seed, int)

    def test_invalid_inputs_are_rejected(self):
        for draws, trials in ((0, 1), (1, 0), (True, 1)):
            with self.subTest(draws=draws, trials=trials):
                with self.assertRaises(ValueError):
                    simulate(self.rule, draws=draws, trials=trials)

    def test_existing_positional_result_constructors_remain_compatible(self):
        record = DrawRecord(
            1, "main", 1, None, 1, 0.008, False, DrawState(1)
        )
        result = SimulationResult(
            "rule1", 3, 1, 42, 2, 0, 3, {0: 1}, 0.0, 0.0, 0.0,
            0.0, None, 0.024, 0.0, 0.024, (record,)
        )

        self.assertEqual(record.source, "main")
        self.assertEqual(record.source_index, 1)
        self.assertEqual(record.main_draws_completed, 1)
        self.assertEqual(record.pity_position, 1)
        self.assertEqual(record.probability, 0.008)
        self.assertEqual(record.state_after, DrawState(1))
        self.assertEqual(result.bonus_draws, 0)
        self.assertEqual(result.total_draws, 3)
        self.assertEqual(result.count_distribution, {0: 1})
        self.assertEqual(result.initial_main_draws, 2)
        self.assertEqual(result.final_main_draws, 5)
        self.assertEqual(result.mean_main_six_stars, 0.0)
        self.assertEqual(result.theoretical_expected_main_count, 0.024)
        self.assertEqual(result.theoretical_source_summaries, {})

    def test_progress_hooks_do_not_change_seeded_result(self):
        updates = []
        baseline = simulate(self.rule, 20, trials=3, seed=42)
        instrumented = simulate(
            self.rule, 20, trials=3, seed=42,
            progress_callback=lambda done, total: updates.append((done, total)),
            cancel_check=lambda: False,
            progress_interval=7,
        )
        self.assertEqual(instrumented, baseline)
        self.assertEqual(updates[0], (0, 60))
        self.assertEqual(updates[-1], (60, 60))

    def test_cancel_check_stops_without_returning_partial_result(self):
        checks = 0
        def cancelled():
            nonlocal checks
            checks += 1
            return checks >= 4
        with self.assertRaises(SimulationCancelled):
            simulate(self.rule, 100, trials=2, seed=42, cancel_check=cancelled)

    def test_cancel_is_checked_before_first_draw_probability(self):
        class CountingRule(Rule1):
            def __init__(self):
                self.probability_calls = 0
            def probability(self, state):
                self.probability_calls += 1
                return super().probability(state)
        rule = CountingRule()
        with self.assertRaises(SimulationCancelled):
            simulate(rule, 10, seed=42, cancel_check=lambda: True)
        self.assertEqual(rule.probability_calls, 1)

    def test_progress_interval_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "progress_interval"):
            simulate(self.rule, 1, progress_interval=0)


if __name__ == "__main__":
    unittest.main()
