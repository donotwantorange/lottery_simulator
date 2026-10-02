"""Task-3 dynamic simulation contract; collective execution is scheduled for task 16."""

from dataclasses import replace
import unittest
from unittest.mock import patch

from lottery_simulator.engine import draw_once, simulate_draws
from lottery_simulator.events import event_counts
from lottery_simulator.formats import SAMPLING_VERSION
from lottery_simulator.results import simulation_payload
from lottery_simulator.rules.runtime import DrawState, compile_pool
from lottery_simulator.rules.definitions import BonusPolicy, MAX_COUNT
from lottery_simulator.control import SimulationCancelled
from tests.fixtures_rules import (
    default_parameters, deterministic_target_compiled, make_default_compiled,
)


class SequenceRandom:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def random(self):
        self.calls += 1
        return next(self.values)


class DynamicEngineTests(unittest.TestCase):
    def test_deterministic_big_pity_target_and_both_modes(self):
        for mode, expected_active in (("disable_after_obtain", False),
                                      ("reset_after_obtain", True)):
            with self.subTest(mode=mode):
                compiled = deterministic_target_compiled(3, mode)
                result = simulate_draws(compiled, default_parameters(draws=3, trials=1, seed=1, trace=True,
                                                                      initial_small_pity={}))
                main = [event for event in result.records
                        if event.event_type == "draw" and event.source == "main"]
                self.assertEqual(len(main), 3)
                self.assertEqual(main[-1].draw_result.outcome.character_id,
                                 compiled.targets["big_pity"])
                self.assertEqual(main[-1].draw_result.state_after.big_active, expected_active)
                if mode == "disable_after_obtain":
                    simulation = result.simulation["draws"]["main"]
                    distributions = simulation["distributions"]
                    high_id = max(compiled.rule.rarities, key=lambda item: item.rank).id
                    self.assertEqual(distributions["pity_triggers"]["big"]["1"], 1)
                    self.assertEqual(distributions["category_counts"][high_id]["up"]["1"], 1)

    def test_draw_once_consumes_one_rarity_roll_and_role_roll_only_when_configured(self):
        compiled = deterministic_target_compiled()
        rarity = compiled.rule.rarities[0]
        rng = SequenceRandom((0.4, 0.7))
        result = draw_once(compiled, DrawState({}, 0, True), rng)
        self.assertEqual(result.outcome.rarity_id, rarity.id)
        self.assertEqual(rng.calls, 1)  # Low tier has no roster.
        self.assertTrue(0 <= result.probabilities[rarity.id] <= 1)
        forced_rng = SequenceRandom((0.2, 0.2))
        forced = draw_once(compiled, DrawState({}, 2, True), forced_rng)
        self.assertEqual(forced.outcome.character_id, compiled.targets["big_pity"])
        self.assertEqual(forced_rng.calls, 2)

    def test_default_480_plus_bonus_and_quantity_two_counts_events(self):
        compiled = make_default_compiled()
        compiled = compile_pool(replace(compiled.rule, grant=replace(compiled.rule.grant, quantity=2)), compiled.pool)
        parameters = default_parameters(draws=480, trials=1, seed=42, trace=True,
                                        initial_small_pity={})
        result = simulate_draws(compiled, parameters)
        self.assertEqual(result.counts.main_draws, 480)
        self.assertEqual(result.counts.bonus_draws, 10)
        self.assertEqual(result.counts.total_draws, 490)
        self.assertEqual(result.counts.grant_triggers, 2)
        self.assertEqual(result.counts.granted_characters, 4)
        self.assertEqual(result.event_count, 492)
        self.assertEqual(result.counts.trace_events, 492)
        self.assertIn("category_counts", result.simulation["draws"]["main"])
        self.assertIn("reward_totals", result.simulation["draws"]["main"])
        grants = [event for event in result.records if event.event_type == "character_grant"]
        self.assertEqual(len(grants), 2)
        self.assertTrue(all(event.grant["quantity"] == 2 for event in grants))
        progress = []
        simulate_draws(compiled, replace(parameters, trace=False),
                       progress_callback=lambda done, total: progress.append((done, total)))
        self.assertEqual(progress[-1], (492, 492))

    def test_event_counts_crossing_history_thresholds(self):
        compiled = make_default_compiled()
        rule = replace(compiled.rule, grant=replace(compiled.rule.grant, period=30, quantity=2))
        counts = event_counts(rule, default_parameters(draws=5, trials=3, initial_main_draws=28))
        self.assertEqual(counts.main_draws, 15)
        self.assertEqual(counts.bonus_draws, 30)
        self.assertEqual(counts.grant_triggers, 3)
        self.assertEqual(counts.granted_characters, 6)
        already_crossed = event_counts(rule, default_parameters(draws=5, trials=1, initial_main_draws=30))
        self.assertEqual(already_crossed.bonus_draws, 0)
        self.assertEqual(already_crossed.grant_triggers, 0)
        base = deterministic_target_compiled(3)
        huge_rule = replace(base.rule, grant=replace(base.rule.grant, enabled=True,
                                                      period=2, quantity=MAX_COUNT))
        with self.assertRaises(ValueError):
            event_counts(huge_rule, default_parameters(draws=2, trials=1, initial_small_pity={}))

    def test_main_bonus_grant_order_when_all_trigger_at_same_position(self):
        compiled = deterministic_target_compiled(120)
        bonus = BonusPolicy(True, 30, 10, compiled.rule.rarities)
        rule = replace(compiled.rule, bonus=bonus,
                       grant=replace(compiled.rule.grant, enabled=True, period=30, quantity=2))
        compiled = compile_pool(rule, compiled.pool)
        parameters = default_parameters(draws=1, trials=1, seed=8, trace=True, initial_main_draws=29,
                                        initial_small_pity={})
        result = simulate_draws(compiled, parameters)
        events = result.records
        self.assertEqual(events[0].source, "main")
        self.assertEqual([event.source for event in events[1:11]], ["bonus"] * 10)
        self.assertEqual(events[-1].event_type, "character_grant")
        self.assertEqual(events[-1].mechanism_id, "periodic_grant")
        self.assertEqual(events[0].draw_result.state_after.big_misses, 30)
        self.assertTrue(all(event.main_state_before == event.main_state_after for event in events[1:11]))

    def test_120th_pity_is_one_main_draw_event(self):
        compiled = deterministic_target_compiled(120)
        result = simulate_draws(compiled, default_parameters(draws=120, trials=1, seed=3, trace=True,
                                                              initial_small_pity={}))
        mains = [event for event in result.records
                 if event.event_type == "draw" and event.source == "main"]
        self.assertEqual(len(mains), 120)
        self.assertEqual([event.event_index for event in mains], list(range(1, 121)))
        self.assertEqual(mains[-1].main_draws_completed, 120)
        self.assertEqual(mains[-1].draw_result.outcome.character_id, compiled.targets["big_pity"])

    def test_grant_quantity_two_is_one_event_without_rng_or_draw_indexes(self):
        base = deterministic_target_compiled(99)
        rule = replace(base.rule, grant=replace(base.rule.grant, enabled=True, period=2,
                                                quantity=2, target="first_up"))
        compiled = compile_pool(rule, base.pool)
        result = simulate_draws(compiled, default_parameters(draws=4, trials=1, seed=31, trace=True,
                                                              initial_small_pity={}))
        draws = [event for event in result.records if event.event_type == "draw"]
        grants = [event for event in result.records if event.event_type == "character_grant"]
        self.assertEqual(len(draws), 4)
        self.assertEqual(len(grants), 2)
        self.assertEqual(result.counts.granted_characters, 4)
        for grant in grants:
            raw = grant.to_dict()
            self.assertIsNone(grant.source)
            self.assertIsNone(grant.draw_index)
            self.assertIsNone(grant.source_index)
            self.assertNotIn("draw_result", raw)
            self.assertIsNone(raw["source"])
            self.assertEqual(grant.grant["quantity"], 2)

    def test_grant_does_not_change_draw_results_or_consume_randomness(self):
        base = deterministic_target_compiled(3)
        p = default_parameters(draws=12, trials=1, seed=991, trace=True, initial_small_pity={})
        plain = simulate_draws(base, p)
        enabled = replace(base.rule.grant, enabled=True, period=1, quantity=1)
        with_grants = simulate_draws(compile_pool(replace(base.rule, grant=enabled), base.pool), p)
        take_draws = lambda result: [event.draw_result for event in result.records
                                     if event.event_type == "draw"]
        self.assertEqual(take_draws(plain), take_draws(with_grants))

    def test_trace_changes_storage_only_and_sink_is_streaming(self):
        compiled = deterministic_target_compiled(5)
        params = default_parameters(draws=8, trials=1, seed=43, initial_small_pity={})
        off = simulate_draws(compiled, replace(params, trace=False))
        on = simulate_draws(compiled, replace(params, trace=True))
        self.assertEqual(off.simulation, on.simulation)
        self.assertEqual(off.counts, replace(on.counts, trace_events=0))
        self.assertEqual(off.event_count, 0)
        self.assertEqual(off.records, ())
        streamed = []
        streamed_result = simulate_draws(compiled, replace(params, trace=True),
                                         record_sink=streamed.append)
        self.assertEqual(tuple(streamed), on.records)
        self.assertEqual(streamed_result.records, ())
        self.assertEqual(streamed_result.event_count, on.event_count)

    def test_progress_uses_real_events_even_without_trace_and_cancellation_aborts(self):
        compiled = deterministic_target_compiled(100)
        progress = []
        phases = []
        params = default_parameters(draws=4, trials=2, seed=5, trace=False,
                                    initial_small_pity={})
        result = simulate_draws(compiled, params, progress_callback=lambda done, total: progress.append((done, total)),
                                phase_callback=lambda *phase: phases.append(phase))
        self.assertEqual(progress[-1][1], 8)
        self.assertEqual(progress[-1][0], 8)
        self.assertEqual(phases[0][0], "simulating")
        self.assertEqual(result.counts.trace_events, 0)
        checks = iter([False, False, True])
        with self.assertRaises(SimulationCancelled):
            simulate_draws(compiled, params, cancel_check=lambda: next(checks))

    def test_randomness_seed_none_and_trial_event_indexes(self):
        compiled = deterministic_target_compiled(3)
        result = simulate_draws(compiled, default_parameters(draws=3, trials=2, seed=None,
                                                              trace=True, initial_small_pity={}))
        self.assertIsInstance(result.seed, int)
        self.assertEqual(result.parameters.seed, result.seed)
        large_seed = 1 << 200
        large = simulate_draws(compiled, default_parameters(draws=1, trials=1, seed=large_seed,
                                                              trace=False, initial_small_pity={}))
        self.assertEqual(large.seed, large_seed)
        self.assertEqual(SAMPLING_VERSION, 2)
        for trial in (1, 2):
            events = [event for event in result.records if event.trial_index == trial]
            self.assertEqual([event.event_index for event in events], list(range(1, len(events) + 1)))
            main = [event for event in events if event.event_type == "draw" and event.source == "main"]
            self.assertEqual([event.draw_index for event in main], [1, 2, 3])

    def test_trace_off_never_constructs_events(self):
        compiled = deterministic_target_compiled(10)
        with patch("lottery_simulator.engine.ProcessEvent", side_effect=AssertionError):
            result = simulate_draws(compiled, default_parameters(draws=3, trials=1, seed=2, trace=False,
                                                                  initial_small_pity={}))
        self.assertEqual(result.records, ())
        self.assertEqual(result.event_count, 0)

    def test_unfinished_theory_and_overflowing_rewards_cannot_serialize(self):
        compiled = deterministic_target_compiled(1, "reset_after_obtain")
        result = simulate_draws(compiled, default_parameters(draws=1, trials=1, seed=2, trace=True,
                                                              initial_small_pity={}))
        with self.assertRaises(ValueError):
            simulation_payload(result, compiled, duration_seconds=0.1)
        complete = replace(result, theoretical={"fixture": {"mean": 1.0}})
        payload = simulation_payload(complete, compiled, duration_seconds=0.1, include_events=True)
        self.assertEqual(payload["rule_snapshot"], compiled.rule.to_dict())
        self.assertEqual(payload["pool_snapshot"], compiled.pool.to_dict())
        self.assertEqual(set(payload["simulation"]), {"draws", "grants", "acquisitions"})
        self.assertIn("reward_totals", payload["simulation"]["draws"]["main"])
        self.assertEqual(len(payload["events"]), complete.event_count)
        with self.assertRaises(ValueError):
            simulation_payload(replace(complete, theoretical={"bad": float("inf")}),
                               compiled, duration_seconds=0.1)
        no_trace = simulate_draws(compiled, default_parameters(draws=1, trials=1, seed=2, trace=False,
                                                               initial_small_pity={}))
        with self.assertRaises(ValueError):
            simulation_payload(replace(no_trace, theoretical={"fixture": True}), compiled,
                               duration_seconds=0.1, include_events=True)
        reward = compiled.pool.rewards[0]
        reward = replace(reward, amounts={rarity_id: 1e308 for rarity_id in reward.amounts})
        pool = replace(compiled.pool, rewards=(reward, *compiled.pool.rewards[1:]))
        overflow_compiled = compile_pool(compiled.rule, pool)
        with self.assertRaises((ValueError, OverflowError)):
            simulate_draws(overflow_compiled, default_parameters(draws=2, trials=1, seed=2, trace=False,
                                                                  initial_small_pity={}))


if __name__ == "__main__":
    unittest.main()
