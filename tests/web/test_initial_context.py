from copy import deepcopy
import unittest

from dashboard.services.initial_conditions import build_initial_context, require_initial_context
from lottery_simulator.config_documents import (
    DEFAULT_POOL_PATH, DEFAULT_RULE_PATH, load_pool_document, load_rule_document, read_config_json,
)
from lottery_simulator.rules.runtime import compile_pool


class InitialContextTests(unittest.TestCase):
    def setUp(self):
        self.rule_raw = read_config_json(DEFAULT_RULE_PATH)
        self.pool_raw = read_config_json(DEFAULT_POOL_PATH)
        self.rule = load_rule_document(self.rule_raw)
        self.pool = load_pool_document(self.pool_raw)
        self.compiled = compile_pool(self.rule, self.pool)

    def test_zero_values_accept_missing_context_but_reject_stale_context(self):
        raw = {"draws": 10, "trials": 1, "seed": None, "trace": False,
               "initial_main_draws": 0, "initial_small_pity": {},
               "initial_big_pity": {"target_obtained": False, "misses": 0}}
        old = build_initial_context(self.compiled)
        normalized = require_initial_context(self.compiled, raw, None)
        self.assertEqual(normalized.initial_main_draws, 0)
        stale = {**old, "rule_id": "00000000-0000-0000-0000-000000000001"}
        with self.assertRaisesRegex(ValueError, "重新确认"):
            require_initial_context(self.compiled, raw, stale)

    def test_changed_target_requires_confirmation_and_cannot_reuse_old_context(self):
        old = build_initial_context(self.compiled)
        changed = deepcopy(self.pool_raw)
        roster = next(item for item in changed["rarity_pools"]
                      if item["rarity_id"] == old["rarity_ids"][-1])
        roster["characters"][1]["is_up"] = True
        roster["characters"] = [roster["characters"][1], roster["characters"][0],
                                 *roster["characters"][2:]]
        compiled = compile_pool(self.rule, load_pool_document(changed))
        params = {"draws": 10, "trials": 1, "seed": None, "trace": False,
                  "initial_main_draws": 20, "initial_small_pity": {},
                  "initial_big_pity": {"target_obtained": True, "misses": 0}}
        with self.assertRaises(ValueError):
            require_initial_context(compiled, params, old)

    def test_switching_big_pity_mode_requires_new_context(self):
        old = build_initial_context(self.compiled)
        changed_rule = deepcopy(self.rule_raw)
        changed_rule["big_pity"]["after_obtain"] = "reset_after_obtain"
        compiled = compile_pool(load_rule_document(changed_rule), self.pool)
        params = {"draws": 10, "trials": 1, "seed": None, "trace": False,
                  "initial_main_draws": 20, "initial_small_pity": {},
                  "initial_big_pity": {"target_obtained": False, "misses": 4}}
        with self.assertRaises(ValueError):
            require_initial_context(compiled, params, old)

    def test_threshold_change_still_runs_mathematical_validation_after_confirmation(self):
        changed_rule = deepcopy(self.rule_raw)
        highest = max(changed_rule["rarities"], key=lambda item: item["rank"])
        highest["hard_pity"] = 10
        compiled = compile_pool(load_rule_document(changed_rule), self.pool)
        params = {"draws": 10, "trials": 1, "seed": None, "trace": False,
                  "initial_main_draws": 20, "initial_small_pity": {highest["id"]: 10},
                  "initial_big_pity": {"target_obtained": False, "misses": 0}}
        context = build_initial_context(compiled)
        with self.assertRaises(ValueError):
            require_initial_context(compiled, params, context)
