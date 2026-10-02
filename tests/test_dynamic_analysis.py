from dataclasses import replace
import unittest
from unittest.mock import patch

from lottery_simulator.analysis import expected_simulation_results
from lottery_simulator.control import SimulationCancelled
from lottery_simulator.rules.definitions import BonusPolicy, GrantPolicy
from lottery_simulator.rules.runtime import compile_pool, initial_state, transition_branches
from tests.fixtures_rules import (
    default_parameters, default_pool, default_rule, deterministic_target_compiled,
)


def _no_pity_compiled(*, bonus=None, grant=None):
    rule, pool = default_rule(), default_pool()
    rarities = tuple(replace(r, soft_enabled=False, hard_enabled=False)
                     for r in rule.rarities)
    rule = replace(rule, rarities=rarities,
                   big_pity=replace(rule.big_pity, enabled=False),
                   bonus=bonus or BonusPolicy(False, rule.bonus.at_main_draw, rule.bonus.draws, ()),
                   grant=grant or GrantPolicy(False, rule.grant.period, rule.grant.quantity,
                                              rule.grant.target))
    return compile_pool(rule, pool)


class DynamicAnalysisTests(unittest.TestCase):
    def test_theory_reports_main_and_bonus_progress(self):
        compiled = _no_pity_compiled()
        params = default_parameters(draws=6, trials=1, seed=42, trace=False,
                                    initial_small_pity={})
        progress = []
        expected_simulation_results(compiled, params,
                                    progress_callback=lambda done, total: progress.append((done, total)))
        self.assertEqual(progress, [(done, 6) for done in range(7)])
        compiled = compile_pool(default_rule(), default_pool())
        params = default_parameters(draws=1, trials=1, seed=42, trace=False,
                                    initial_main_draws=29, initial_small_pity={})
        progress = []
        expected_simulation_results(compiled, params,
                                    progress_callback=lambda done, total: progress.append((done, total)))
        self.assertEqual(progress, [(done, 11) for done in range(12)])

    def test_default_rule_completes_240_main_draw_theory_exactly(self):
        compiled = default_rule()
        pool = default_pool()
        compiled = compile_pool(compiled, pool)
        result = expected_simulation_results(
            compiled, default_parameters(draws=240, trials=1, seed=42, trace=False,
                                         initial_small_pity={}))
        main = result["draws"]["main"]
        bonus = result["draws"]["bonus"]
        self.assertEqual(main["draw_count"], 240)
        self.assertAlmostEqual(sum(main["rarity_counts"].values()), 240)
        highest_id = max(compiled.rule.rarities, key=lambda rarity: rarity.rank).id
        self.assertAlmostEqual(sum(main["character_counts"].values()),
                               main["rarity_counts"][highest_id])
        self.assertEqual(bonus["draw_count"], compiled.rule.bonus.draws)
        self.assertEqual(result["grants"]["trigger_count"], 1)
        self.assertEqual(result["grants"]["character_count"],
                         compiled.rule.grant.quantity)
        self.assertTrue(all(0 <= value <= 1 for value in
                            main["at_least_one"]["characters"].values()))

    def test_first_and_reset_big_pity_modes_follow_joint_target_branches(self):
        for mode, expected_targets in (("disable_after_obtain", 1), ("reset_after_obtain", 2)):
            compiled = deterministic_target_compiled(3, mode)
            params = default_parameters(draws=6, trials=1, seed=42, trace=False,
                                        initial_small_pity={})
            result = expected_simulation_results(compiled, params)
            target = compiled.targets["big_pity"]
            self.assertEqual(result["draws"]["main"]["character_counts"][target], expected_targets)
            self.assertEqual(result["draws"]["main"]["at_least_one"]["characters"][target], 1)
            state = initial_state(compiled, params)
            branches = transition_branches(compiled, state)
            self.assertAlmostEqual(sum(branch[2] for branch in branches), 1)

    def test_fixed_probabilities_match_closed_form_survival_and_trials_do_not_scale_mean(self):
        compiled = _no_pity_compiled()
        one = default_parameters(draws=6, trials=1, seed=42, trace=False, initial_small_pity={})
        seven = replace(one, trials=7)
        first = expected_simulation_results(compiled, one)
        repeated = expected_simulation_results(compiled, seven)
        high = max(compiled.rule.rarities, key=lambda item: item.rank)
        up = next(character.id for item in compiled.pool.rarity_pools
                  for character in item.characters if character.rarity_id == high.id and character.is_up)
        probability = high.base_probability * next(
            item.up_share for item in compiled.pool.rarity_pools if item.rarity_id == high.id)
        self.assertAlmostEqual(first["draws"]["main"]["at_least_one"]["characters"][up],
                               1 - (1 - probability) ** 6)
        self.assertEqual(first, repeated)

    def test_three_rarity_two_draw_tree_matches_exact_path_enumeration(self):
        compiled = _no_pity_compiled()
        params = default_parameters(draws=2, trials=1, seed=42, trace=False,
                                    initial_small_pity={})
        target = next(c.id for pool in compiled.pool.rarity_pools for c in pool.characters
                      if c.is_up)
        paths = [(initial_state(compiled, params), 1.0, 0.0, False)]
        for _ in range(params.draws):
            next_paths = []
            for state, mass, count, hit in paths:
                for rarity_id, character_id, probability, after in transition_branches(compiled, state):
                    next_paths.append((after, mass * probability,
                                       count + (character_id == target),
                                       hit or character_id == target))
            paths = next_paths
        expected_count = sum(mass * count for _, mass, count, _ in paths)
        probability_at_least_once = sum(mass for _, mass, _, hit in paths if hit)
        result = expected_simulation_results(compiled, params)["draws"]["main"]
        self.assertAlmostEqual(result["character_counts"][target], expected_count)
        self.assertAlmostEqual(result["at_least_one"]["characters"][target],
                               probability_at_least_once)

    def test_bonus_is_independent_and_direct_grant_is_classified_in_acquisitions(self):
        rule = default_rule()
        bonus = rule.bonus
        grant = replace(rule.grant, enabled=True, period=1, quantity=2)
        compiled = _no_pity_compiled(bonus=bonus, grant=grant)
        params = default_parameters(draws=1, trials=3, seed=42, trace=False,
                                    initial_main_draws=bonus.at_main_draw - 1,
                                    initial_small_pity={})
        result = expected_simulation_results(compiled, params)
        main = result["draws"]["main"]["at_least_one"]["characters"]
        bonus_prob = result["draws"]["bonus"]["at_least_one"]["characters"]
        combined = result["draws"]["total"]["at_least_one"]["characters"]
        for character_id in main:
            self.assertAlmostEqual(combined[character_id],
                                   1 - (1 - main[character_id]) * (1 - bonus_prob[character_id]))
        for rarity_id, categories in result["draws"]["total"]["at_least_one"]["categories"].items():
            for category, probability in categories.items():
                expected = 1 - (
                    1 - result["draws"]["main"]["at_least_one"]["categories"][rarity_id][category]
                ) * (
                    1 - result["draws"]["bonus"]["at_least_one"]["categories"][rarity_id][category]
                )
                self.assertAlmostEqual(probability, expected)
        grants = result["grants"]
        acquisition = result["acquisitions"]
        target = compiled.targets["periodic_grant"]
        self.assertEqual(grants["trigger_count"], 1)
        self.assertEqual(grants["character_count"], 2)
        self.assertEqual(acquisition["character_counts"][target],
                         result["draws"]["total"]["character_counts"][target] + 2)
        self.assertEqual(acquisition["character_count"],
                         sum(acquisition["character_counts"].values()))
        self.assertEqual(acquisition["at_least_one"]["characters"][target], 1)
        self.assertEqual(result["draws"]["main"]["draw_count"], 1)
        self.assertEqual(result["draws"]["bonus"]["draw_count"], bonus.draws)

    def test_cancel_check_interrupts_finite_recurrence(self):
        compiled = deterministic_target_compiled()
        params = default_parameters(draws=6, trials=1, seed=42, trace=False,
                                    initial_small_pity={})
        with self.assertRaises(SimulationCancelled):
            expected_simulation_results(compiled, params, cancel_check=lambda: True)

    def test_resource_limits_report_failure_instead_of_partial_expectations(self):
        compiled = deterministic_target_compiled()
        params = default_parameters(draws=1, trials=1, initial_small_pity={})
        for limit in ("_MAX_STATES", "_MAX_BRANCHES"):
            with self.subTest(limit=limit), patch(f"lottery_simulator.analysis.{limit}", 0):
                with self.assertRaisesRegex(ValueError, "资源上限"):
                    expected_simulation_results(compiled, params)


if __name__ == "__main__":
    unittest.main()
