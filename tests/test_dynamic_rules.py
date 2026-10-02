"""Task-2 regression checks; collective execution is scheduled for task 16."""

from dataclasses import FrozenInstanceError, replace
import json
import math
import unittest
from uuid import UUID

from lottery_simulator.rules.definitions import (
    BigInitial, CharacterDefinition, RarityDefinition, RarityPool,
)
from lottery_simulator.rules.runtime import (
    DrawState, advance_state, character_probabilities, compile_pool, initial_context,
    initial_state, normalize_parameters, pity_status, rarity_probabilities,
    transition_branches,
)
from tests.fixtures_rules import (
    character_id, default_parameters, make_default_compiled,
)


def uid(number):
    return str(UUID(int=number))


class DynamicRulesTests(unittest.TestCase):
    def setUp(self):
        self.c = make_default_compiled()
        self.r4, self.r5, self.r6 = sorted(self.c.rule.rarities, key=lambda r: r.rank)
        self.up = character_id(self.c, "UP-A")

    def compile(self, *, rarities=None, big=None, pool=None, grant=None):
        rule = self.c.rule
        rule = replace(rule, rarities=rarities or rule.rarities,
                       big_pity=big or rule.big_pity, grant=grant or rule.grant,
                       bonus=replace(rule.bonus, enabled=False))
        return compile_pool(rule, pool or self.c.pool)

    def test_default_boundaries_and_simultaneous_pity(self):
        for misses, expected in [(64, .008), (65, .058), (78, .708), (79, 1.0)]:
            with self.subTest(misses=misses):
                s = DrawState({self.r6.id: misses})
                self.assertAlmostEqual(rarity_probabilities(self.c, s)[self.r6.id], expected)
                self.assertEqual(self.r6.id in pity_status(self.c, s)["soft_active"], misses >= 65)
                self.assertEqual(self.r6.id in pity_status(self.c, s)["hard_active"], misses == 79)
        s = DrawState({self.r6.id: 65, self.r5.id: 9})
        p = rarity_probabilities(self.c, s)
        self.assertEqual(p[self.r4.id], 0)
        self.assertAlmostEqual(p[self.r5.id], .942)
        self.assertAlmostEqual(p[self.r6.id], .058)
        s = DrawState({self.r6.id: 79, self.r5.id: 9})
        self.assertEqual(pity_status(self.c, s)["hard_active"], [self.r5.id, self.r6.id])
        self.assertEqual(rarity_probabilities(self.c, s)[self.r6.id], 1)

    def test_big_forces_target_and_modes(self):
        s = DrawState({self.r6.id: 0}, 119, True)
        self.assertTrue(pity_status(self.c, s)["big_forced"])
        self.assertEqual(character_probabilities(self.c, self.r6.id, s), {self.up: 1})
        branches = transition_branches(self.c, s)
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0][:3], (self.r6.id, self.up, 1))
        self.assertFalse(branches[0][3].big_active)
        self.assertEqual(branches[0][3].big_misses, 0)
        cyclic = self.compile(big=replace(self.c.rule.big_pity, after_obtain="reset_after_obtain"))
        after = advance_state(cyclic, s, self.r6.id, self.up)
        self.assertTrue(after.big_active)
        self.assertEqual(after.big_misses, 0)
        other = character_id(self.c, "限定-B")
        after = advance_state(self.c, DrawState({}, 12, True), self.r6.id, other)
        self.assertEqual(after.big_misses, 13)
        normal_hit = advance_state(self.c, DrawState({}, 12, True), self.r6.id, self.up)
        self.assertFalse(normal_hit.big_active)

    def test_soft_priority_lowest_and_four_tiers(self):
        rarities = tuple(replace(r, base_probability=p, soft_enabled=True,
                                 soft_start=1, soft_step=step, hard_enabled=False)
                         for r, p, step in zip((self.r4, self.r5, self.r6), (.6, .3, .1), (1, .8, .4)))
        c = self.compile(rarities=rarities)
        p = rarity_probabilities(c, DrawState())
        self.assertEqual(p[self.r4.id], 0)
        self.assertAlmostEqual(p[self.r5.id], .5)
        self.assertAlmostEqual(p[self.r6.id], .5)
        lowest_only = self.compile(rarities=tuple(replace(r, soft_enabled=r.id == self.r4.id,
                                                         soft_start=1, soft_step=1)
                                                  for r in (self.r4, self.r5, self.r6)))
        self.assertEqual(rarity_probabilities(lowest_only, DrawState())[self.r4.id], .912)
        r7 = RarityDefinition(uid(100), "新档", 10, .1, False, 1, 0, True, 2)
        rule = replace(self.c.rule, rarities=(replace(self.r4, base_probability=.812), self.r5, self.r6, r7),
                       bonus=replace(self.c.rule.bonus, enabled=False),
                       big_pity=replace(self.c.rule.big_pity, enabled=False))
        pool = replace(self.c.pool, rarity_pools=(*self.c.pool.rarity_pools, RarityPool(r7.id, (), False, 0)))
        c = compile_pool(rule, pool)
        branches = transition_branches(c, DrawState({r7.id: 1}))
        self.assertEqual(branches[0][:3], (r7.id, None, 1))

    def test_weights_up_groups_same_name_and_overflow(self):
        for r in (self.r4, self.r5, self.r6):
            a = CharacterDefinition(uid(200 + r.rank), r.id, "同名", 1e308, True, True)
            b = CharacterDefinition(uid(300 + r.rank), r.id, "普通", 1e308, False, False)
            d = CharacterDefinition(uid(400 + r.rank), r.id, "另一位", 5e307, False, True)
            rosters = tuple(RarityPool(x.id, (a, b, d), True, .25) if x.id == r.id
                            else p for x, p in zip((self.r4, self.r5, self.r6), self.c.pool.rarity_pools))
            c = self.compile(pool=replace(self.c.pool, rarity_pools=rosters))
            self.assertEqual(character_probabilities(c, r.id, DrawState()), {a.id: .25, b.id: .5, d.id: .25})
            off = replace(rosters[r.rank - self.r4.rank], up_enabled=False)
            c = self.compile(pool=replace(self.c.pool, rarity_pools=tuple(off if p.rarity_id == r.id else p for p in rosters)))
            self.assertEqual(character_probabilities(c, r.id, DrawState()), {a.id: .4, b.id: .4, d.id: .2})
            for share in (0, 1):
                pool = replace(self.c.pool, rarity_pools=tuple(replace(p, up_share=share) if p.rarity_id == self.r6.id else p for p in self.c.pool.rarity_pools))
                p = character_probabilities(self.compile(pool=pool), self.r6.id, DrawState())
                self.assertAlmostEqual(p[self.up], share)
        a = CharacterDefinition(uid(900), self.r4.id, "UP-A", 1, False, False)
        pool = replace(self.c.pool, rarity_pools=(RarityPool(self.r4.id, (a,), False, 0), *self.c.pool.rarity_pools[1:]))
        c = self.compile(pool=pool)
        self.assertEqual(character_probabilities(c, self.r4.id, DrawState()), {a.id: 1})

    def test_compile_references_labels_and_targets(self):
        with self.assertRaises(ValueError):
            compile_pool(self.c.rule, replace(self.c.pool, rule_ref={"id": uid(99), "name": "其他"}))
        with self.assertRaises(ValueError):
            compile_pool(self.c.rule, replace(self.c.pool, rarity_pools=self.c.pool.rarity_pools[1:]))
        with self.assertRaises(ValueError):
            compile_pool(self.c.rule, replace(self.c.pool, rarity_labels={self.r4.id: self.r6.name}))
        roster = self.c.pool.rarity_pools[-1]
        another_up = replace(roster.characters[1], is_up=True)
        reordered = replace(roster, characters=(another_up, roster.characters[0], *roster.characters[2:]))
        c = compile_pool(self.c.rule, replace(self.c.pool, rarity_pools=(*self.c.pool.rarity_pools[:-1], reordered)))
        self.assertEqual(c.targets["big_pity"], another_up.id)
        s = DrawState({}, 10, True)
        after = advance_state(c, s, self.r6.id, self.up)
        self.assertTrue(after.big_active)
        self.assertEqual(after.big_misses, 11)
        grant = replace(self.c.rule.grant, target="pool_selected")
        with self.assertRaises(ValueError):
            self.compile(grant=grant)
        pool = replace(self.c.pool, mechanism_targets={"periodic_grant": character_id(self.c, "限定-B")})
        self.assertEqual(self.compile(grant=grant, pool=pool).targets["periodic_grant"], character_id(self.c, "限定-B"))
        self.assertIsNone(self.compile(grant=replace(grant, enabled=False)).targets["periodic_grant"])
        top = replace(self.c.pool.rarity_pools[-1], up_enabled=False,
                      characters=tuple(replace(c, is_up=False) for c in self.c.pool.rarity_pools[-1].characters))
        lower = RarityPool(self.r5.id, (CharacterDefinition(uid(700), self.r5.id, "低档UP", 1, True, True),), True, 1)
        pool = replace(self.c.pool, rarity_pools=(self.c.pool.rarity_pools[0], lower, top))
        with self.assertRaisesRegex(ValueError, "最高"):
            compile_pool(self.c.rule, pool)
        c = self.compile(pool=pool, big=replace(self.c.rule.big_pity, enabled=False))
        self.assertEqual(c.targets["periodic_grant"], uid(700))
        with self.assertRaises(TypeError):
            c.targets["big_pity"] = self.up

    def test_initial_semantics_and_context(self):
        parameters = normalize_parameters(self.c, default_parameters(initial_small_pity={}).to_dict())
        self.assertEqual(dict(parameters.initial_small_pity), {r.id: 0 for r in self.c.rule.rarities})
        self.assertEqual(initial_state(self.c, parameters), DrawState({self.r5.id: 0, self.r6.id: 0}, 0, True))
        p = default_parameters(initial_main_draws=20, initial_small_pity={self.r6.id: 15})
        self.assertEqual(initial_state(self.c, p).big_misses, 20)
        obtained = replace(p, initial_big_pity=BigInitial(True, 0))
        self.assertFalse(initial_state(self.c, obtained).big_active)
        context = initial_context(self.c)
        self.assertEqual(context.rarity_ids, (self.r4.id, self.r5.id, self.r6.id))
        self.assertEqual(context.big_target_id, self.up)
        cyclic = self.compile(big=replace(self.c.rule.big_pity, after_obtain="reset_after_obtain"))
        self.assertEqual(initial_state(cyclic, replace(p, initial_big_pity=BigInitial(False, 16))).big_misses, 16)
        disabled = self.compile(big=replace(self.c.rule.big_pity, enabled=False))
        self.assertIsNone(initial_context(disabled).big_target_id)
        self.assertIsNone(initial_context(disabled).big_mode)
        # Disabled top-tier counter must not act as a placeholder zero in history comparisons.
        untracked = self.compile(rarities=(self.r4, self.r5, replace(self.r6, soft_enabled=False, hard_enabled=False)))
        normalize_parameters(untracked, default_parameters(initial_main_draws=20, initial_small_pity={self.r5.id: 8}))

    def test_impossible_initial_histories(self):
        invalid = [dict(initial_small_pity={uid(99): 0}),
                   dict(initial_main_draws=1, initial_small_pity={self.r4.id: 1}),
                   dict(initial_small_pity={self.r6.id: 1}),
                   dict(initial_main_draws=80, initial_small_pity={self.r6.id: 80}),
                   dict(initial_main_draws=20, initial_small_pity={self.r5.id: 9, self.r6.id: 8}),
                   dict(initial_main_draws=120),
                   dict(initial_big_pity=BigInitial(True, 0)),
                   dict(initial_main_draws=20, initial_small_pity={self.r6.id: 20}, initial_big_pity=BigInitial(True, 0)),
                   dict(initial_main_draws=20, initial_big_pity=BigInitial(False, 1))]
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                normalize_parameters(self.c, default_parameters(**overrides))
        cyclic = self.compile(big=replace(self.c.rule.big_pity, after_obtain="reset_after_obtain"))
        for big in (BigInitial(True, 0), BigInitial(False, 21), BigInitial(False, 10)):
            with self.subTest(big=big), self.assertRaises(ValueError):
                normalize_parameters(cyclic, default_parameters(initial_main_draws=20,
                                     initial_small_pity={self.r6.id: 15}, initial_big_pity=big))
        with self.assertRaises(ValueError):
            normalize_parameters(cyclic, default_parameters(initial_main_draws=200, initial_big_pity=BigInitial(False, 120)))
        disabled = self.compile(big=replace(self.c.rule.big_pity, enabled=False))
        for big in (BigInitial(True, 0), BigInitial(False, 1)):
            with self.assertRaises(ValueError):
                normalize_parameters(disabled, default_parameters(initial_main_draws=1, initial_big_pity=big))

    def test_state_hash_roundtrip_validation_and_real_counts(self):
        raw = {self.r6.id: 65, self.r5.id: 8}
        state = DrawState(raw)
        raw[self.r6.id] = 0
        self.assertEqual(state, DrawState(tuple(reversed(state.small_pity))))
        self.assertEqual(DrawState.from_dict(json.loads(json.dumps(state.to_dict()))), state)
        self.assertEqual(len({state, DrawState(dict(state.small_pity))}), 1)
        with self.assertRaises(FrozenInstanceError):
            state.big_misses = 0
        for raw in ([(self.r6.id, 1), (self.r6.id, 2)], {self.r6.id: True}):
            with self.assertRaises(ValueError):
                DrawState(raw)
        for state in (DrawState({uid(99): 0}), DrawState({self.r4.id: 1}),
                      DrawState({self.r6.id: 80}), DrawState({}, 120, True)):
            with self.assertRaises(ValueError):
                rarity_probabilities(self.c, state)
        # A saturated candidate may have no lower mass available. Equal vectors
        # do not rewrite the supplied real state; a higher hit still resets it.
        c = self.compile(rarities=(replace(self.r4, base_probability=0),
                         replace(self.r5, base_probability=0, soft_enabled=True, soft_start=1,
                         soft_step=1, hard_enabled=False), replace(self.r6, base_probability=1,
                         soft_enabled=False, hard_enabled=False)))
        real = DrawState({self.r5.id: 100})
        equivalent = DrawState({self.r5.id: 0})
        self.assertEqual(rarity_probabilities(c, real), rarity_probabilities(c, equivalent))
        after = advance_state(c, real, self.r6.id, self.up)
        self.assertEqual(dict(after.small_pity), {self.r5.id: 0})
        # Before the first soft increment, many counts have equal probabilities;
        # runtime must retain the true count even when theory can share a key.
        c = self.compile(rarities=(replace(self.r4, base_probability=0),
                         replace(self.r5, base_probability=1, soft_enabled=False),
                         replace(self.r6, base_probability=0, soft_enabled=True,
                                 soft_start=1000, hard_enabled=False)))
        real = DrawState({self.r6.id: 100, self.r5.id: 0})
        equivalent = DrawState({self.r6.id: 0, self.r5.id: 0})
        self.assertEqual(rarity_probabilities(c, real), rarity_probabilities(c, equivalent))
        after = advance_state(c, real, self.r5.id, None)
        self.assertEqual(dict(after.small_pity)[self.r6.id], 101)
        self.assertEqual(dict(real.small_pity)[self.r6.id], 100)

    def test_transitions_joint_mass_and_reject_impossible_results(self):
        state = DrawState({self.r5.id: 3, self.r6.id: 5}, 7, True)
        branches = transition_branches(self.c, state)
        self.assertAlmostEqual(math.fsum(b[2] for b in branches), 1)
        low = next(b for b in branches if b[0] == self.r4.id)
        self.assertIsNone(low[1])
        self.assertEqual(dict(low[3].small_pity), {self.r5.id: 4, self.r6.id: 6})
        self.assertEqual(low[3].big_misses, 8)
        middle = next(b for b in branches if b[0] == self.r5.id)
        self.assertEqual(dict(middle[3].small_pity), {self.r5.id: 0, self.r6.id: 6})
        high = next(b for b in branches if b[0] == self.r6.id)
        self.assertEqual(dict(high[3].small_pity), {self.r5.id: 0, self.r6.id: 0})
        self.assertEqual(dict(state.small_pity), {self.r5.id: 3, self.r6.id: 5})
        for rarity, character in ((self.r4.id, self.up), (self.r6.id, None), (uid(99), None)):
            with self.assertRaises(ValueError):
                advance_state(self.c, state, rarity, character)
        with self.assertRaises(ValueError):
            advance_state(self.c, DrawState({self.r5.id: 9}), self.r4.id, None)
        with self.assertRaises(ValueError):
            advance_state(self.c, DrawState({}, 119, True), self.r6.id, character_id(self.c, "限定-B"))


if __name__ == "__main__":
    unittest.main()
