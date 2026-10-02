import json
import math
import unittest
from dataclasses import replace

from lottery_simulator.control import SimulationCancelled
from lottery_simulator.rules.definitions import BigPityPolicy, BonusPolicy, GrantPolicy
from lottery_simulator.rules.runtime import compile_pool
from lottery_simulator.waiting_analysis import waiting_time_stats
from tests.fixtures_rules import default_parameters, default_pool, default_rule


def _two_tier(*, high_probability=0.0, high_soft=False, high_start=1,
              high_step=0.0, low_soft=False, low_hard=False,
              big=True, threshold=3, after_obtain="disable_after_obtain"):
    rule, pool = default_rule(), default_pool()
    low, _, high = sorted(rule.rarities, key=lambda item: item.rank)
    low = replace(low, base_probability=1.0 - high_probability,
                  soft_enabled=low_soft, hard_enabled=low_hard)
    high = replace(high, base_probability=high_probability,
                   soft_enabled=high_soft, soft_start=high_start, soft_step=high_step,
                   hard_enabled=False)
    rule = replace(rule, rarities=(low, high),
                   big_pity=BigPityPolicy(big, threshold, "first_up", after_obtain),
                   bonus=BonusPolicy(False, 30, 10, ()),
                   grant=GrantPolicy(False, 240, 1, "first_up"))
    pool = replace(pool,
                   rarity_pools=tuple(p for p in pool.rarity_pools if p.rarity_id in {low.id, high.id}),
                   rarity_labels={key: value for key, value in pool.rarity_labels.items()
                                  if key in {low.id, high.id}},
                   rewards=tuple(replace(reward, amounts={key: value for key, value in reward.amounts.items()
                                                         if key in {low.id, high.id}})
                                 for reward in pool.rewards),
                   mechanism_targets={})
    return compile_pool(rule, pool), low.id, high.id


class WaitingAnalysisTests(unittest.TestCase):
    def params(self, **kwargs):
        defaults = {"draws": 1, "trials": 1, "initial_small_pity": {}, **kwargs}
        return default_parameters(**defaults)

    def test_big_pity_at_history_two_means_one_future_draw(self):
        compiled, _, high = _two_tier()
        result = waiting_time_stats(compiled, self.params(initial_main_draws=2), high)
        self.assertEqual(result["mean"], {"status": "finite", "value": 1.0})
        self.assertEqual(result["hit_probability"], {"status": "finite", "value": 1.0})
        self.assertEqual(result["distribution"]["support"]["maximum"], 1)
        self.assertEqual(result["initial_state"]["big_misses"], 2)

    def test_previously_obtained_one_shot_target_does_not_make_future_wait_zero(self):
        compiled, _, high = _two_tier()
        parameters = self.params(initial_main_draws=3,
                                 initial_big_pity=replace(self.params().initial_big_pity,
                                                          target_obtained=True))
        result = waiting_time_stats(compiled, parameters, high)
        self.assertEqual(result["status"], "unreachable")
        self.assertEqual(result["mean"], {"status": "infinite", "value": None})
        self.assertEqual(result["hit_probability"], {"status": "finite", "value": 0.0})
        self.assertTrue(all(value["status"] == "unreachable" for value in result["quantiles"].values()))

    def test_cycle_mode_uses_supplied_active_misses(self):
        compiled, _, high = _two_tier(after_obtain="reset_after_obtain")
        parameters = self.params(initial_main_draws=2,
                                 initial_big_pity=replace(self.params().initial_big_pity, misses=2))
        result = waiting_time_stats(compiled, parameters, high)
        self.assertEqual(result["initial_state"]["big_misses"], 2)
        self.assertEqual(result["mean"]["value"], 1.0)

    def test_constant_probability_uses_geometric_mean_and_quantiles(self):
        compiled, _, high = _two_tier(high_probability=0.25, big=False)
        result = waiting_time_stats(compiled, self.params(), high)
        self.assertEqual(result["distribution"]["kind"], "geometric")
        self.assertEqual(result["mean"]["value"], 4.0)
        self.assertEqual([result["quantiles"][str(q)]["value"] for q in (0.9, 0.95, 0.99)],
                         [9, 11, 17])
        self.assertEqual(result["distribution"]["tail_mass"]["status"], "remaining")
        self.assertGreater(result["distribution"]["tail_mass"]["value"], 0)

    def test_lower_tier_pity_does_not_change_query_hit_probability(self):
        rule, pool = default_rule(), default_pool()
        low, middle, high = sorted(rule.rarities, key=lambda item: item.rank)
        low = replace(low, base_probability=0.5, soft_enabled=False, hard_enabled=False)
        middle = replace(middle, base_probability=0.25, soft_enabled=True,
                         soft_start=1, soft_step=0.5, hard_enabled=True, hard_pity=2)
        high = replace(high, base_probability=0.25, soft_enabled=False, hard_enabled=False)
        rule = replace(rule, rarities=(low, middle, high),
                       big_pity=BigPityPolicy(False, 3, "first_up", "disable_after_obtain"),
                       bonus=BonusPolicy(False, 30, 10, ()),
                       grant=GrantPolicy(False, 240, 1, "first_up"))
        with_lower = compile_pool(rule, pool)
        params = self.params(initial_small_pity={middle.id: 0})
        result = waiting_time_stats(with_lower, params, high.id)
        self.assertEqual(result["distribution"]["kind"], "geometric")
        self.assertEqual(result["mean"]["value"], 4.0)

    def test_soft_saturation_has_exact_first_guaranteed_draw(self):
        compiled, _, high = _two_tier(high_soft=True, high_start=3, high_step=0.5, big=False)
        result = waiting_time_stats(compiled, self.params(), high)
        self.assertEqual(result["distribution"]["support"]["maximum"], 4)
        self.assertEqual(result["distribution"]["window"]["probabilities"][-1],
                         {"draws": 4, "probability": 0.5})
        self.assertEqual(result["mean"]["value"], 3.5)

    def test_geometric_tail_underflow_is_not_reported_as_zero(self):
        compiled, _, high = _two_tier(high_probability=1 - 1e-16, big=False)
        result = waiting_time_stats(compiled, self.params(), high)
        tail = result["distribution"]["tail_mass"]
        self.assertEqual(tail["status"], "underflow")
        self.assertIsNone(tail["value"])
        self.assertTrue(math.isfinite(tail["log_value"]))

    def test_tiny_soft_step_does_not_hide_active_big_pity_bound(self):
        compiled, _, high = _two_tier(high_soft=True, high_step=1e-320)
        result = waiting_time_stats(compiled, self.params(initial_main_draws=2), high)
        self.assertEqual(result["status"], "finite")
        self.assertEqual(result["distribution"]["support"]["maximum"], 1)

    def test_large_proven_bound_returns_explicit_incomplete(self):
        compiled, _, high = _two_tier(high_soft=True, high_start=1,
                                     high_step=1e-7, big=False)
        result = waiting_time_stats(compiled, self.params(), high)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("计算上限", result["message"])

    def test_certain_hit_before_conservative_bound_has_zero_tail(self):
        rule, pool = default_rule(), default_pool()
        low, middle, high = sorted(rule.rarities, key=lambda item: item.rank)
        low = replace(low, base_probability=0.5, soft_enabled=False, hard_enabled=False)
        middle = replace(middle, base_probability=0.25, soft_enabled=True,
                         soft_start=1, soft_step=0.25, hard_enabled=False)
        high = replace(high, base_probability=0.25, soft_enabled=True,
                       soft_start=1, soft_step=0.25, hard_enabled=False)
        rule = replace(rule, rarities=(low, middle, high),
                       big_pity=BigPityPolicy(False, 3, "first_up", "disable_after_obtain"),
                       bonus=BonusPolicy(False, 30, 10, ()),
                       grant=GrantPolicy(False, 240, 1, "first_up"))
        compiled = compile_pool(rule, pool)
        result = waiting_time_stats(compiled, self.params(), middle.id)
        self.assertEqual(result["distribution"]["support"]["maximum"], 1)
        self.assertEqual(result["distribution"]["tail_mass"], {"status": "zero", "value": 0.0})

    def test_querying_lowest_tier_is_certain_on_first_draw(self):
        compiled, low, _ = _two_tier()
        result = waiting_time_stats(compiled, self.params(), low)
        self.assertEqual(result["mean"]["value"], 1.0)
        self.assertEqual(result["distribution"]["support"]["maximum"], 1)

    def test_cancellation_and_json_finiteness(self):
        compiled, _, high = _two_tier(high_probability=0.25, big=False)
        with self.assertRaises(SimulationCancelled):
            waiting_time_stats(compiled, self.params(), high, cancel_check=lambda: True)
        result = waiting_time_stats(compiled, self.params(), high)
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
