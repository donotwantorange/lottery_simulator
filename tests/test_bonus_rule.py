"""Task-3 bonus isolation regressions; collective execution is task 16."""

from dataclasses import replace
import unittest

from lottery_simulator.rules.definitions import BonusPolicy
from lottery_simulator.rules.runtime import compile_pool
from lottery_simulator.engine import simulate_draws
from tests.fixtures_rules import default_parameters, make_default_compiled


class BonusRuleTests(unittest.TestCase):
    def test_bonus_draws_use_a_separate_pity_state(self):
        base = make_default_compiled()
        ordered = sorted(base.rule.rarities, key=lambda rarity: rarity.rank)
        low, high = ordered[0], ordered[-1]
        main_rarities = (replace(low, base_probability=1.0, soft_enabled=False, hard_enabled=False),
                         replace(high, base_probability=0.0, soft_enabled=False, hard_enabled=False))
        bonus_rarities = (replace(low, base_probability=0.0, soft_enabled=False, hard_enabled=False),
                          replace(high, base_probability=1.0, soft_enabled=False, hard_enabled=False))
        # Keep the default low/high IDs so the matching pool stays valid.
        pool = replace(base.pool, rarity_pools=tuple(
                           replace(item, up_share=1.0) if item.rarity_id == high.id else item
                           for item in base.pool.rarity_pools if item.rarity_id in {r.id for r in main_rarities}),
                       rewards=tuple(replace(reward, amounts={key: value for key, value in reward.amounts.items()
                                                            if key in {r.id for r in main_rarities}})
                                     for reward in base.pool.rewards),
                       rarity_labels={key: value for key, value in base.pool.rarity_labels.items()
                                      if key in {r.id for r in main_rarities}})
        bonus = BonusPolicy(True, 1, 2, bonus_rarities)
        rule = replace(base.rule, rarities=main_rarities,
                       big_pity=replace(base.rule.big_pity, hard_pity=3), bonus=bonus)
        compiled = compile_pool(rule, pool)
        result = simulate_draws(compiled, default_parameters(draws=3, trials=1, seed=17, trace=True,
                                                              initial_small_pity={}))
        main = [event for event in result.records if event.event_type == "draw" and event.source == "main"]
        bonus_events = [event for event in result.records if event.event_type == "draw" and event.source == "bonus"]
        self.assertEqual(len(bonus_events), 2)
        self.assertTrue(all(event.main_state_before == event.main_state_after for event in bonus_events))
        self.assertTrue(all(event.draw_result.outcome.character_id == compiled.targets["big_pity"]
                            for event in bonus_events))
        self.assertEqual(main[-1].draw_result.state_before.big_misses, 2)
        self.assertEqual(main[-1].draw_result.outcome.character_id, compiled.targets["big_pity"])


if __name__ == "__main__":
    unittest.main()
