from dataclasses import astuple, replace
import unittest
from unittest.mock import patch

from lottery_simulator.engine import (
    DrawOutcome,
    DrawRecord,
    DrawResult,
    SimulationCancelled,
    SimulationResult,
    draw_once,
    simulate,
)
from lottery_simulator.control import (
    SimulationCancelled as ControlSimulationCancelled,
    check_cancelled,
)
from lottery_simulator.formats import SAMPLING_VERSION
from lottery_simulator.rules.base import BonusEvent, DrawState, RarityProbabilities
from lottery_simulator.rules.pool_config import PoolConfig, RewardRule, WeightedCharacter
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

    def test_simulation_cancelled_is_shared_with_control_module(self):
        self.assertIs(SimulationCancelled, ControlSimulationCancelled)

    def test_check_cancelled_raises_shared_exception(self):
        with self.assertRaises(ControlSimulationCancelled):
            check_cancelled(lambda: True)
        check_cancelled(lambda: False)
        check_cancelled(None)

    def test_four_star_name_uses_common_result(self):
        raw = self.rule.config.to_dict()
        raw["four_star_characters"] = [
            {"name": "四星A", "weight": 1}, {"name": "四星B", "weight": 3}
        ]
        result = draw_once(Rule1(PoolConfig.from_dict(raw)), DrawState(),
                           SequenceRandom((0.9, 0.2)))
        self.assertIsInstance(result, DrawResult)
        self.assertEqual(result.outcome.rarity, 4)
        self.assertEqual(result.outcome.character_name, "四星A")
        self.assertEqual(result.state_before, DrawState())
        self.assertEqual(result.state_after, DrawState(1, 1))

    def test_five_star_named_weight_boundary_rewards_and_flags(self):
        config = replace(self.rule.config, five_star_characters=(
            WeightedCharacter("五星A", 1), WeightedCharacter("五星B", 3)))
        result = draw_once(Rule1(config), DrawState(2, 9), SequenceRandom((0.9, 0.25)))
        self.assertTrue(hasattr(result, "outcome"))
        self.assertEqual(result.outcome, DrawOutcome(
            5, "五星B", False, False, {"奖励A": 5.0, "奖励B": 2.0}, True, False))
        self.assertEqual(result.state_before, DrawState(2, 9))
        self.assertEqual(result.state_after, DrawState(3, 0))

    def test_role_roll_consumption_for_empty_singleton_and_weighted_lists(self):
        for rarity_roll, field, rarity in ((0.9, "four_star_characters", 4),
                                         (0.05, "five_star_characters", 5)):
            for characters in ((), (WeightedCharacter("A"),),
                               (WeightedCharacter("A"), WeightedCharacter("B"))):
                with self.subTest(rarity=rarity, characters=characters):
                    config = replace(self.rule.config, **{field: characters})
                    rng = SequenceRandom((rarity_roll, 0.2, 0.7))
                    result = draw_once(Rule1(config), DrawState(), rng)
                    self.assertEqual(rng.random(), 0.7 if characters else 0.2)
                    self.assertTrue(hasattr(result, "outcome"))
                    self.assertEqual(result.outcome.rarity, rarity)
                    self.assertEqual(result.outcome.character_name, "A" if characters else None)

    def test_six_star_empty_character_distribution_is_rejected(self):
        class EmptyCharactersRule(AlwaysSixRule):
            def character_probabilities(self, rarity, state):
                return {}
        with self.assertRaises(ValueError):
            draw_once(EmptyCharactersRule(), DrawState(), SequenceRandom((0.0, 0.0)))

    def test_six_star_hard_pity_uses_rule_interface_not_counter(self):
        class NoHardPityFlagRule(Rule1):
            def six_star_hard_pity_active(self, state):
                return False
        result = draw_once(NoHardPityFlagRule(), DrawState(79), SequenceRandom((0.9, 0.0)))
        self.assertTrue(hasattr(result, "outcome"))
        self.assertFalse(result.outcome.six_star_hard_pity_triggered)
        bonus = Rule1(fixed_six_star_probability=0.008, subrules=())
        result = draw_once(bonus, DrawState(79), SequenceRandom((0.9,)))
        self.assertFalse(result.outcome.six_star_hard_pity_triggered)
        self.assertEqual(result.state_after, DrawState(80, 1))

    def test_trace_defaults_off_and_rejects_invalid_flag_or_disabled_sink(self):
        result = simulate(self.rule, 1, seed=42)
        self.assertFalse(result.trace_enabled)
        self.assertEqual(result.record_count, 0)
        self.assertEqual(result.records, ())
        for value in (None, 0, "yes"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                simulate(self.rule, 1, seed=42, collect_records=value)
        with self.assertRaisesRegex(ValueError, "record_sink"):
            simulate(self.rule, 1, seed=42, record_sink=lambda record: None)

    def test_three_trial_trace_has_per_trial_indices_and_isolated_bonus_state(self):
        result = simulate(
            NoEarlySixRule(), draws=2, trials=3, seed=42,
            initial_pity=29, initial_five_star_pity=4,
            collect_records=True,
        )

        self.assertTrue(result.trace_enabled)
        self.assertEqual(result.record_count, 36)
        self.assertEqual(len(result.records), 36)
        for trial_index in (1, 2, 3):
            records = [
                record for record in result.records
                if record.trial_index == trial_index
            ]
            self.assertEqual(len(records), 12)
            self.assertEqual(
                [record.source for record in records],
                ["main"] + ["bonus"] * 10 + ["main"],
            )
            self.assertEqual(
                [record.draw_index for record in records], list(range(1, 13))
            )
            self.assertEqual(
                [record.main_draws_completed for record in records],
                [30] * 11 + [31],
            )
            main = [record for record in records if record.source == "main"]
            self.assertEqual(
                [record.source_index for record in main], [1, 2]
            )
            self.assertEqual(
                main[0].main_state_before, DrawState(29, 4)
            )
            bonus = [record for record in records if record.source == "bonus"]
            self.assertEqual(
                [record.source_index for record in bonus], list(range(1, 11))
            )
            self.assertTrue(all(
                record.main_state_before == record.main_state_after
                for record in bonus
            ))

    def test_sink_and_memory_modes_emit_identical_records(self):
        memory = simulate(
            NoEarlySixRule(), draws=2, trials=3, seed=42,
            initial_pity=29, collect_records=True,
        )
        streamed = []
        sink_result = simulate(
            NoEarlySixRule(), draws=2, trials=3, seed=42,
            initial_pity=29, collect_records=True, record_sink=streamed.append,
        )

        self.assertEqual(streamed, list(memory.records))
        self.assertEqual(sink_result.records, ())
        self.assertEqual(sink_result.record_count, len(streamed))
        self.assertEqual(sink_result, replace(memory, records=()))

    def test_trace_mode_does_not_change_aggregates(self):
        without = simulate(
            NoEarlySixRule(), draws=2, trials=3, seed=42, initial_pity=29,
        )
        with_trace = simulate(
            NoEarlySixRule(), draws=2, trials=3, seed=42,
            initial_pity=29, collect_records=True,
        )

        self.assertEqual(
            without,
            replace(
                with_trace, trace_enabled=False, record_count=0, records=()
            ),
        )

    def test_sink_error_aborts_simulation(self):
        def fail(_record):
            raise RuntimeError("sink failed")

        with self.assertRaisesRegex(RuntimeError, "sink failed"):
            simulate(
                self.rule, draws=2, trials=3, seed=42,
                collect_records=True, record_sink=fail,
            )

    def test_controlled_rng_advances_across_trial_boundary(self):
        rng = SequenceRandom((0.9, 0.0, 0.0))
        with patch(
            "lottery_simulator.engine.random.Random", return_value=rng
        ) as random_constructor:
            result = simulate(
                Rule1(subrules=()), draws=1, trials=2, seed=42,
                collect_records=True,
            )

        random_constructor.assert_called_once_with(42)
        self.assertEqual(
            [record.draw_result.outcome.rarity for record in result.records],
            [4, 6],
        )

    def test_sampling_version_one_seeded_sequence_is_unchanged(self):
        self.assertEqual(SAMPLING_VERSION, 1)
        result = simulate(
            Rule1(subrules=()), draws=8, seed=42, collect_records=True
        )

        self.assertEqual(
            [record.draw_result.outcome.rarity for record in result.records],
            [4, 5, 4, 4, 4, 4, 4, 5],
        )

    def test_trace_does_not_change_outcome(self):
        config = replace(self.rule.config,
                         four_star_characters=(WeightedCharacter("UP-A"),),
                         five_star_characters=(WeightedCharacter("五星A"),))
        rule = Rule1(config)
        without = simulate(rule, 30, trials=1, seed=42, collect_records=False)
        with_trace = simulate(rule, 30, trials=1, seed=42, collect_records=True)
        self.assertEqual(
            without,
            replace(with_trace, trace_enabled=False, record_count=0, records=()),
        )

    def test_disabled_trace_never_constructs_main_or_bonus_records(self):
        with patch("lottery_simulator.engine.DrawRecord", side_effect=AssertionError):
            result = simulate(self.rule, 1, initial_pity=29, seed=42, collect_records=False)
            self.assertEqual(result.bonus_draws, 10)
            self.assertEqual(result.records, ())
            with self.assertRaises(AssertionError):
                simulate(self.rule, 1, initial_pity=29, seed=42, collect_records=True)

    def test_named_lower_stars_do_not_pollute_six_star_statistics(self):
        config = replace(self.rule.config,
                         four_star_characters=(WeightedCharacter("UP-A"),),
                         five_star_characters=(WeightedCharacter("独立五星"),))
        with patch("lottery_simulator.engine.random.Random",
                   return_value=SequenceRandom((0.9, 0.0, 0.05, 0.0))):
            result = simulate(Rule1(config, subrules=()), 2, seed=42, collect_records=True)
        self.assertTrue(hasattr(result.records[0], "draw_result"))
        self.assertEqual([r.draw_result.outcome.character_name for r in result.records],
                         ["UP-A", "独立五星"])
        for source in ("main", "total"):
            summary = result.source_summaries[source]
            self.assertEqual(sum(summary["mean_character_counts"].values()), 0)
            self.assertEqual(sum(summary["mean_six_star_categories"].values()), 0)

    def test_fixed_seed_is_reproducible(self):
        first = simulate(self.rule, draws=100, trials=1, seed=42)
        second = simulate(self.rule, draws=100, trials=1, seed=42)
        self.assertEqual(first, second)

    def test_draw_once_returns_rarity_character_rewards_and_state(self):
        result = draw_once(
            Rule1(), DrawState(9, 9), SequenceRandom((0.0, 0.0))
        )
        outcome, state_after, probabilities = result.outcome, result.state_after, result.probabilities
        self.assertEqual(outcome.rarity, 6)
        self.assertEqual(outcome.character_name, "UP-A")
        self.assertTrue(outcome.is_up)
        self.assertTrue(outcome.is_limited)
        self.assertTrue(outcome.five_star_pity_triggered)
        self.assertEqual(outcome.rewards, {"奖励A": 25.0, "奖励B": 10.0})
        self.assertAlmostEqual(sum(astuple(probabilities)), 1.0)
        self.assertEqual(state_after, DrawState(0, 0))

    def test_six_star_metadata_boundaries_and_role_roll(self):
        for roll, name, up, limited in ((0.0, "UP-A", True, True),
                                         (0.5, "限定-B", False, True),
                                         (0.625, "常驻-D", False, False)):
            with self.subTest(name=name):
                rng = SequenceRandom((0.0, roll, 0.9))
                result = draw_once(self.rule, DrawState(), rng)
                self.assertEqual(result.outcome.character_name, name)
                self.assertEqual(result.outcome.is_up, up)
                self.assertEqual(result.outcome.is_limited, limited)
                self.assertEqual(rng.random(), 0.9)

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
                result = draw_once(
                    Rule1(), DrawState(), SequenceRandom((roll,))
                )
                outcome, state_after, probabilities = result.outcome, result.state_after, result.probabilities
                self.assertEqual(outcome, expected_outcome)
                self.assertEqual(state_after, expected_state)
                self.assertAlmostEqual(sum(astuple(probabilities)), 1.0)

    def test_draw_once_marks_six_star_hard_pity(self):
        result = draw_once(
            Rule1(), DrawState(79, 0), SequenceRandom((0.99, 0.0))
        )
        outcome, state_after = result.outcome, result.state_after
        self.assertEqual(outcome.rarity, 6)
        self.assertTrue(outcome.six_star_hard_pity_triggered)
        self.assertEqual(state_after, DrawState(0, 0))

    def test_single_trial_explicitly_keeps_trace(self):
        result = simulate(self.rule, draws=3, trials=1, seed=42, collect_records=True)
        self.assertEqual(len(result.records), 3)
        self.assertEqual(result.records[0].draw_result.state_before, DrawState())
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
                "format_version": 1,
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
                "four_star_characters": [],
                "five_star_characters": [],
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
                trace = simulate(rule, draws=3, trials=1, seed=42, collect_records=True)
            self.assertEqual([record.draw_result.outcome.rarity for record in trace.records], expected)

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
        result = simulate(Rule1(), draws=30, trials=1, seed=42, collect_records=True)

        self.assertEqual(
            [record.source for record in result.records[29:]],
            ["main"] + ["bonus"] * 10,
        )
        main_state_at_thirty = result.records[29].main_state_after
        for record in result.records:
            outcome = record.draw_result.outcome
            self.assertIn(outcome.rarity, (4, 5, 6))
            self.assertEqual(outcome.character_name is not None, outcome.rarity == 6)
            self.assertIsInstance(outcome.is_up, bool)
            self.assertIsInstance(outcome.is_limited, bool)
            self.assertEqual(set(outcome.rewards), {"奖励A", "奖励B"})
            self.assertAlmostEqual(sum(astuple(record.draw_result.probabilities)), 1.0)
            self.assertIsInstance(outcome.five_star_pity_triggered, bool)
            self.assertIsInstance(outcome.six_star_hard_pity_triggered, bool)
            self.assertEqual(record.record_format_version, 2)
            self.assertEqual(record.trial_index, 1)
            if record.source == "main":
                self.assertEqual(record.draw_result.state_before, record.main_state_before)
                self.assertEqual(record.draw_result.state_after, record.main_state_after)
        for record in result.records[30:]:
            self.assertEqual(record.main_state_before, main_state_at_thirty)
            self.assertEqual(record.main_state_after, main_state_at_thirty)
            self.assertIsNotNone(record.draw_result.state_before)
            self.assertIsNotNone(record.draw_result.state_after)

    def test_multiple_trials_only_keep_aggregates(self):
        result = simulate(self.rule, draws=100, trials=50, seed=42)
        self.assertEqual(result.records, ())
        self.assertEqual(sum(result.count_distribution.values()), 50)
        self.assertEqual(result.theoretical_expected_count > 0, True)

    def test_initial_pity_is_applied(self):
        result = simulate(self.rule, draws=1, trials=1, seed=1, initial_pity=79, collect_records=True)
        single = result.records[0].draw_result
        self.assertEqual(single.outcome.rarity, 6)
        self.assertEqual(single.probabilities.six_star, 1.0)
        self.assertTrue(single.outcome.six_star_hard_pity_triggered)
        self.assertEqual(single.state_after.misses_since_six_star, 0)

    def test_bonus_records_are_inserted_without_changing_main_pity(self):
        result = simulate(NoEarlySixRule(), draws=31, trials=1, seed=42, collect_records=True)

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
            {record.main_state_after.misses_since_six_star for record in bonus_records},
            {30},
        )
        self.assertEqual(main_records[-1].draw_result.state_before.misses_since_six_star + 1, 31)

    def test_bonus_source_index_is_cumulative_across_events_in_a_trial(self):
        class MultipleBonusEvents:
            def events_after_main_draw(self, completed_main_draws):
                if completed_main_draws == 1:
                    return (
                        BonusEvent("first", 2, 0.008, 10),
                        BonusEvent("second", 3, 0.008, 10),
                    )
                return ()

            def expected_draws(self, initial_main_draws, draws):
                return 5 if initial_main_draws == 0 and draws >= 1 else 0

        result = simulate(
            Rule1(subrules=(MultipleBonusEvents(),)), draws=1, seed=42,
            collect_records=True,
        )
        bonus = [record for record in result.records if record.source == "bonus"]

        self.assertEqual([record.source_index for record in bonus], [1, 2, 3, 4, 5])

    def test_initial_pity_thirty_means_bonus_was_already_claimed(self):
        result = simulate(self.rule, draws=1, trials=1, seed=42, initial_pity=30, collect_records=True)

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
        result = simulate(GuaranteedBonusRule(), draws=2, trials=1, seed=42, collect_records=True)

        bonus_records = [record for record in result.records if record.source == "bonus"]
        main_records = [record for record in result.records if record.source == "main"]
        self.assertTrue(all(record.draw_result.outcome.rarity == 6 for record in bonus_records))
        self.assertEqual(
            {record.main_state_after.misses_since_six_star for record in bonus_records},
            {1},
        )
        self.assertEqual(main_records[1].draw_result.state_before.misses_since_six_star + 1, 2)

    def test_bonus_records_do_not_change_main_double_pity(self):
        result = simulate(
            Rule1(), draws=2, trials=1, seed=42,
            initial_pity=29, initial_five_star_pity=8,
            collect_records=True,
        )
        bonus = [record for record in result.records if record.source == "bonus"]

        self.assertEqual(len(bonus), 10)
        self.assertEqual(result.initial_five_star_pity, 8)
        self.assertEqual(len({record.main_state_after for record in bonus}), 1)
        self.assertEqual(bonus[0].draw_result.state_before, DrawState())
        self.assertTrue(any(
            record.draw_result.state_after.misses_since_five_or_higher == 0
            for record in bonus
        ))

    def test_main_draw_counter_advances_only_for_main_draws(self):
        result = simulate(
            NoEarlySixRule(), draws=2, trials=1, seed=42, initial_pity=29, collect_records=True
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

    def test_new_record_constructor_nests_draw_and_main_state(self):
        single = draw_once(self.rule, DrawState(), SequenceRandom((0.9,)))
        record = DrawRecord(
            2, 1, 1, "main", 1, None, 1, single, DrawState(), DrawState(1, 1)
        )
        result = SimulationResult(
            "rule1", 3, 1, 42, 2, 0, 3, {0: 1}, 0.0, 0.0, 0.0,
            0.0, None, 0.024, 0.0, 0.024, True, 1, (record,)
        )

        self.assertEqual(record.trial_index, 1)
        self.assertEqual(record.source, "main")
        self.assertEqual(record.source_index, 1)
        self.assertEqual(record.main_draws_completed, 1)
        self.assertIs(record.draw_result, single)
        self.assertEqual(record.draw_result.probabilities.six_star, 0.008)
        self.assertEqual(record.draw_result.state_after, DrawState(1, 1))
        self.assertEqual(record.main_state_before, DrawState())
        self.assertEqual(record.main_state_after, DrawState(1, 1))
        self.assertEqual(result.bonus_draws, 0)
        self.assertEqual(result.total_draws, 3)
        self.assertEqual(result.count_distribution, {0: 1})
        self.assertEqual(result.initial_main_draws, 2)
        self.assertEqual(result.final_main_draws, 5)
        self.assertEqual(result.mean_main_six_stars, 0.0)
        self.assertEqual(result.theoretical_expected_main_count, 0.024)
        self.assertTrue(result.trace_enabled)
        self.assertEqual(result.record_count, 1)
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

    def test_phase_callback_can_cancel_when_theory_starts(self):
        cancelled = False
        phases = []

        def phase_callback(name, completed, total):
            nonlocal cancelled
            phases.append((name, completed, total))
            if name == "theory":
                cancelled = True

        with self.assertRaises(SimulationCancelled):
            simulate(
                self.rule, 2, seed=42, phase_callback=phase_callback,
                cancel_check=lambda: cancelled,
            )
        self.assertEqual(phases, [("simulating", None, None), ("theory", None, None)])

    def test_cancel_check_stops_during_bonus_draws(self):
        checks = 0

        def cancelled_on_second_bonus_draw():
            nonlocal checks
            checks += 1
            return checks == 3

        with self.assertRaises(SimulationCancelled):
            simulate(
                GuaranteedBonusRule(), 1, seed=42,
                cancel_check=cancelled_on_second_bonus_draw,
            )

    def test_phase_callbacks_preserve_seeded_results_and_trace_records(self):
        phases = []
        progress_updates = []
        phase_callback = lambda name, completed, total: phases.append((name, completed, total))
        progress_callback = lambda completed, total: progress_updates.append((completed, total))
        baseline = simulate(self.rule, 30, trials=2, seed=42, collect_records=True)
        instrumented = simulate(
            self.rule, 30, trials=2, seed=42,
            phase_callback=phase_callback, progress_callback=progress_callback,
            cancel_check=lambda: False,
        )
        memory = simulate(
            self.rule, 30, trials=2, seed=42, collect_records=True,
            phase_callback=phase_callback, progress_callback=progress_callback,
            cancel_check=lambda: False,
        )
        streamed = []
        sink = simulate(
            self.rule, 30, trials=2, seed=42, collect_records=True,
            record_sink=streamed.append, phase_callback=phase_callback,
            progress_callback=progress_callback,
            cancel_check=lambda: False,
        )

        def aggregate_summary(result):
            # SimulationResult has no wall-clock field; omit Trace storage shape.
            return replace(result, trace_enabled=False, record_count=0, records=())

        self.assertEqual(aggregate_summary(instrumented), aggregate_summary(baseline))
        self.assertEqual(aggregate_summary(memory), aggregate_summary(baseline))
        self.assertEqual(baseline.records, memory.records)
        self.assertEqual(len(memory.records), 80)
        self.assertEqual(streamed, list(memory.records))
        self.assertEqual(sink, replace(memory, records=()))
        self.assertEqual(phases, [("simulating", None, None), ("theory", None, None)] * 3)
        self.assertEqual(progress_updates, [(0, 60), (60, 60)] * 3)

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
