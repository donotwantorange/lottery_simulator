import unittest

from lottery_simulator.engine import simulate
from lottery_simulator.rules.base import BonusEvent
from lottery_simulator.rules.rule_1 import Rule1


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
