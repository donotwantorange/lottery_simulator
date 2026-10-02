"""Task-1 contracts; run with unittest during the task-16 acceptance phase."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import unittest
from uuid import uuid4

from lottery_simulator.rules.definitions import (
    ALGORITHM, MAX_COUNT, BigInitial, ExperimentDocument,
    ExperimentParameters, InitialContext, PoolDefinition, RarityDefinition, RuleDefinition,
)
from tests.fixtures_rules import default_parameters, default_pool, default_rule


class RuleDefinitionsTest(unittest.TestCase):
    def test_defaults_match_confirmed_mechanisms(self):
        rule = default_rule()
        self.assertEqual(rule.name, "zmd")
        self.assertEqual(rule.algorithm, ALGORITHM)
        self.assertEqual([r.name for r in sorted(rule.rarities, key=lambda r: r.rank)], ["四星", "五星", "六星"])
        self.assertAlmostEqual(sum(r.base_probability for r in rule.rarities), 1, places=12)
        top = max(rule.rarities, key=lambda r: r.rank)
        self.assertEqual((top.soft_start, top.soft_step, top.hard_pity), (66, .05, 80))
        self.assertEqual((rule.big_pity.hard_pity, rule.big_pity.target, rule.big_pity.after_obtain), (120, "first_up", "disable_after_obtain"))
        self.assertEqual((rule.bonus.at_main_draw, rule.bonus.draws), (30, 10))
        self.assertEqual((rule.grant.period, rule.grant.quantity), (240, 1))
        self.assertTrue(all(not r.soft_enabled for r in rule.bonus.rarities))
        self.assertEqual([r.rank for r in rule.bonus.rarities if r.hard_enabled], [1])

    def test_all_types_roundtrip_and_json_lists(self):
        rule, pool, parameters = default_rule(), default_pool(), default_parameters()
        context = InitialContext(rule.id, tuple(r.id for r in rule.rarities), rule.big_pity.after_obtain, pool.rarity_pools[-1].characters[0].id)
        document = ExperimentDocument("示例", {"id": pool.id, "name": pool.name}, parameters, context)
        objects = [rule, *rule.rarities, rule.big_pity, rule.bonus, rule.grant,
                   pool, *pool.rarity_pools, *pool.rarity_pools[-1].characters,
                   *pool.rewards, parameters, parameters.initial_big_pity, context, document]
        for value in objects:
            with self.subTest(type=type(value).__name__):
                self.assertEqual(type(value).from_dict(value.to_dict()), value)
                self.assertEqual(type(value).from_dict(json.loads(json.dumps(value.to_dict(), allow_nan=False))), value)
        self.assertIsInstance(rule.to_dict()["rarities"], list)
        with self.assertRaises(FrozenInstanceError):
            rule.name = "覆盖"
        output = pool.to_dict()
        output["rule_ref"]["name"] = "覆盖"
        self.assertEqual(pool.rule_ref["name"], "zmd")
        for mapping, key, value in ((pool.rule_ref, "name", "覆盖"),
                                    (parameters.initial_small_pity, rule.rarities[0].id, 3),
                                    (pool.rewards[0].amounts, rule.rarities[0].id, -1)):
            with self.assertRaises(TypeError):
                mapping[key] = value

    def test_unknown_missing_and_wrong_nested_shapes(self):
        for original, loader in ((default_rule().to_dict(), RuleDefinition.from_dict),
                                 (default_pool().to_dict(), PoolDefinition.from_dict),
                                 (default_parameters().to_dict(), ExperimentParameters.from_dict)):
            for changed in ({**original, "owner": "forged"}, {key: value for key, value in original.items() if key != next(iter(original))}):
                with self.subTest(loader=loader), self.assertRaises(ValueError):
                    loader(changed)
        for field, value in (("rarities", {}), ("rarities", "invalid"), ("big_pity", None), ("grant", [])):
            raw = default_rule().to_dict()
            raw[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                RuleDefinition.from_dict(raw)
        raw = default_rule().to_dict()
        raw["rarities"][0]["unknown"] = 1
        with self.assertRaises(ValueError):
            RuleDefinition.from_dict(raw)

    def test_rarity_identity_rank_names_and_sum(self):
        for field in ("id", "rank", "name"):
            raw = default_rule().to_dict()
            raw["rarities"][1][field] = raw["rarities"][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                RuleDefinition.from_dict(raw)
        for delta, accepted in ((5e-13, True), (2e-12, False), (.1, False)):
            raw = default_rule().to_dict()
            raw["rarities"][0]["base_probability"] += delta
            if accepted:
                self.assertEqual(RuleDefinition.from_dict(raw).rarities[0].base_probability, raw["rarities"][0]["base_probability"])
            else:
                with self.assertRaises(ValueError):
                    RuleDefinition.from_dict(raw)
        raw = default_rule().to_dict()
        raw["rarities"] = []
        with self.assertRaises(ValueError):
            RuleDefinition.from_dict(raw)

    def test_strict_numbers_booleans_and_modes(self):
        rarity = default_rule().rarities[-1].to_dict()
        for field, values in (("base_probability", [True, -1, 1.01, float("nan"), float("inf"), 10**400]),
                              ("soft_step", [False, 0, -1, float("nan")]),
                              ("rank", [True, -1, 1.5]), ("soft_start", [True, 0]),
                              ("hard_pity", [False, 0, MAX_COUNT + 1]),
                              ("soft_enabled", [1, None]), ("hard_enabled", [0, "true"])):
            for value in values:
                with self.subTest(field=field, value=str(value)[:30]), self.assertRaises(ValueError):
                    RarityDefinition.from_dict({**rarity, field: value})
        for field, value in (("algorithm", "zmd"), ("algorithm", "python")):
            with self.assertRaises(ValueError):
                RuleDefinition.from_dict({**default_rule().to_dict(), field: value})
        for section, field, value in (("big_pity", "target", "pool_selected"),
                                      ("big_pity", "after_obtain", "unknown"),
                                      ("grant", "target", "unknown"), ("grant", "quantity", False),
                                      ("bonus", "draws", 0)):
            raw = default_rule().to_dict()
            raw[section][field] = value
            with self.subTest(section=section), self.assertRaises(ValueError):
                RuleDefinition.from_dict(raw)

    def test_disabled_mechanisms_keep_drafts_and_enabled_bonus_matches(self):
        rule = default_rule()
        rarity = replace(rule.rarities[-1], soft_enabled=False, soft_step=0)
        self.assertEqual(rarity.soft_start, 66)
        disabled = replace(rule, bonus=replace(rule.bonus, enabled=False, rarities=()))
        self.assertEqual(RuleDefinition.from_dict(disabled.to_dict()), disabled)
        for field, value in (("id", str(uuid4())), ("rank", 3)):
            raw = rule.to_dict()
            raw["bonus"]["rarities"][-1][field] = value
            with self.assertRaises(ValueError):
                RuleDefinition.from_dict(raw)

    def test_weights_flags_and_group_endpoints(self):
        original = default_pool().rarity_pools[-1]
        character = original.characters[0]
        for weight in (True, 0, -1, float("nan"), float("inf"), 10**400):
            with self.subTest(weight=str(weight)[:30]), self.assertRaises(ValueError):
                replace(character, weight=weight)
        with self.assertRaises(ValueError):
            replace(character, is_limited=False)
        only_up = replace(original, characters=(character,), up_share=1)
        self.assertEqual(len(only_up.characters), 1)
        only_other = replace(original, characters=original.characters[1:], up_share=0)
        self.assertFalse(any(c.is_up for c in only_other.characters))
        for changed in ((character,), original.characters[1:], ()):
            with self.assertRaises(ValueError):
                replace(original, characters=changed)
        self.assertTrue(replace(original, up_enabled=False).characters[0].is_up)

    def test_pool_ids_names_and_reward_references(self):
        pool = default_pool()
        raw = pool.to_dict()
        raw["rarity_pools"][0]["characters"] = [dict(raw["rarity_pools"][-1]["characters"][0], id=str(uuid4()), rarity_id=raw["rarity_pools"][0]["rarity_id"])]
        self.assertEqual(PoolDefinition.from_dict(raw).rarity_pools[0].characters[0].name, "UP-A")
        for kind in ("duplicate_character_id", "duplicate_character_name", "wrong_rarity", "duplicate_rarity", "bad_reward", "duplicate_reward"):
            changed = pool.to_dict()
            group = changed["rarity_pools"][-1]
            if kind == "duplicate_character_id":
                group["characters"][1]["id"] = group["characters"][0]["id"]
            elif kind == "duplicate_character_name":
                group["characters"][1]["name"] = group["characters"][0]["name"]
            elif kind == "wrong_rarity":
                group["characters"][0]["rarity_id"] = changed["rarity_pools"][0]["rarity_id"]
            elif kind == "duplicate_rarity":
                changed["rarity_pools"].append(deepcopy(changed["rarity_pools"][0]))
            elif kind == "bad_reward":
                changed["rewards"][0]["amounts"][str(uuid4())] = 1
            else:
                changed["rewards"].append(deepcopy(changed["rewards"][0]))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                PoolDefinition.from_dict(changed)
        for amount in (True, -1, float("inf"), float("nan")):
            reward = pool.rewards[0]
            with self.assertRaises(ValueError):
                replace(reward, amounts={pool.rarity_pools[0].rarity_id: amount})

    def test_labels_bindings_and_mutable_inputs_are_copied(self):
        pool = default_pool()
        ids = [item.rarity_id for item in pool.rarity_pools]
        for labels in ({ids[0]: " "}, {ids[0]: "SSR", ids[1]: " SSR "}, {str(uuid4()): "UR"}):
            with self.assertRaises(ValueError):
                replace(pool, rarity_labels=labels)
        labels = {ids[0]: " R "}
        changed = replace(pool, rarity_labels=labels)
        labels[ids[0]] = "覆盖"
        self.assertEqual(changed.rarity_labels[ids[0]], "R")
        for targets in ({"unknown": str(uuid4())}, {"periodic_grant": "not-id"}):
            with self.assertRaises(ValueError):
                replace(pool, mechanism_targets=targets)
        # Enabled-target existence is checked by task-2 compile_pool, not this schema.
        self.assertEqual(len(replace(pool, mechanism_targets={"periodic_grant": str(uuid4())}).mechanism_targets), 1)

    def test_parameters_preserve_seed_and_reject_storage_overflow(self):
        parameters = default_parameters(seed=2**200 + 1)
        self.assertEqual(ExperimentParameters.from_dict(json.loads(json.dumps(parameters.to_dict()))).seed, 2**200 + 1)
        for field, value in (("draws", True), ("trials", 0), ("seed", False), ("seed", "42"),
                             ("trace", None), ("initial_main_draws", -1), ("draws", MAX_COUNT),
                             ("initial_small_pity", {default_rule().rarities[0].id: True})):
            raw = parameters.to_dict()
            raw[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                ExperimentParameters.from_dict(raw)
        with self.assertRaises(ValueError):
            BigInitial(False, True)
        with self.assertRaises(ValueError):
            default_parameters(draws=1, initial_main_draws=MAX_COUNT)

    def test_context_modes_ids_and_canonical_duplicates(self):
        rule = default_rule()
        ids = tuple(item.id for item in rule.rarities)
        context = InitialContext(rule.id, ids, None, None)
        self.assertEqual(InitialContext.from_dict(context.to_dict()), context)
        for changed in (dict(context.to_dict(), rarity_ids=[ids[0], ids[0]]),
                        dict(context.to_dict(), big_mode="unknown"),
                        dict(context.to_dict(), big_target_id=str(uuid4()))):
            with self.assertRaises(ValueError):
                InitialContext.from_dict(changed)
        with self.assertRaises(ValueError):
            default_parameters(initial_small_pity={"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": 0, "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA": 1})


if __name__ == "__main__":
    unittest.main()
