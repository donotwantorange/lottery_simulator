from dataclasses import astuple
import unittest

from lottery_simulator.engine import (
    DrawOutcome,
    DrawRecord,
    SimulationCancelled,
    SimulationResult,
    draw_once,
    simulate,
)
from lottery_simulator.rules.base import BonusEvent, DrawState
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
            return (BonusEvent("guaranteed_test_bonus", 2, 1.0),)
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
