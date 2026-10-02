"""Task 9 Trace store contracts; feature execution is scheduled for task 16."""

from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from dashboard.limits import TraceLimits
from dashboard.trace_store import TraceWriter, validate_event
from lottery_simulator.control import SimulationCancelled
from lottery_simulator.engine import simulate_draws as simulate
from lottery_simulator.rules.runtime import compile_pool
from tests.fixtures_rules import default_parameters, make_default_compiled


class TraceStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "trace.sqlite3"
        base = make_default_compiled()
        self.compiled = compile_pool(replace(base.rule,
            grant=replace(base.rule.grant, quantity=2)), base.pool)
        self.parameters = default_parameters(draws=40, trials=2, seed=42, trace=True)

    def simulate_to(self, writer, parameters=None):
        return simulate(self.compiled, parameters or self.parameters, record_sink=writer.append)

    def metadata(self):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return dict(db.execute("SELECT * FROM metadata WHERE id=1").fetchone())

    def test_batch_flush_finish_freezes_event_metadata(self):
        writer = TraceWriter(self.path, limits=TraceLimits(batch_size=7, max_records=None))
        self.addCleanup(writer.close)
        result = self.simulate_to(writer)
        self.assertFalse(self.metadata()["complete"])
        writer.finish(self.compiled, result.parameters, result.counts)
        self.assertEqual((self.metadata()["format_version"], self.metadata()["complete"],
                          self.metadata()["event_count"]), (2, 1, result.counts.trace_events))

    def test_writer_rejects_existing_path_and_event_limit(self):
        self.path.touch()
        with self.assertRaises(ValueError):
            TraceWriter(self.path, limits=TraceLimits())
        self.path.unlink()
        writer = TraceWriter(self.path, limits=TraceLimits(batch_size=100, max_records=1))
        self.addCleanup(writer.close)
        result = simulate(self.compiled, default_parameters(draws=2, trials=1, seed=2, trace=True))
        self.assertEqual(result.counts.trace_events, 2)
        writer.append(result.records[0])
        with self.assertRaises(ValueError):
            writer.append(result.records[1])

    def test_finish_rejects_gap_wrong_count_and_semantically_corrupt_grant(self):
        params = default_parameters(draws=241, trials=1, seed=4, trace=True)
        result = simulate(self.compiled, params)
        self.assertTrue(any(event.event_type == "character_grant" for event in result.records))
        gap_path = Path(self.temp.name) / "gap.sqlite3"
        gap_writer = TraceWriter(gap_path, limits=TraceLimits(max_records=None))
        self.addCleanup(gap_writer.close)
        for event in result.records[:-1]:
            gap_writer.append(event)
        with self.assertRaises(ValueError):
            gap_writer.finish(self.compiled, result.parameters, result.counts)
        with sqlite3.connect(gap_path) as db:
            self.assertEqual(db.execute("SELECT complete FROM metadata").fetchone()[0], 0)

        grant = next(event for event in result.records if event.event_type == "character_grant")
        bad_grant = replace(grant, grant={**grant.grant, "quantity": grant.grant["quantity"] + 1})
        writer = TraceWriter(self.path, limits=TraceLimits(batch_size=11, max_records=None))
        self.addCleanup(writer.close)
        for event in (*result.records[:result.records.index(grant)], bad_grant, *result.records[result.records.index(grant)+1:]):
            writer.append(event)
        with self.assertRaises(ValueError):
            writer.finish(self.compiled, result.parameters, result.counts)

        index_path = Path(self.temp.name) / "index.sqlite3"
        index_writer = TraceWriter(index_path, limits=TraceLimits(batch_size=1, max_records=None))
        self.addCleanup(index_writer.close)
        for event in result.records:
            index_writer.append(event)
        with sqlite3.connect(index_path) as db, self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE events SET event_index=event_index+1 WHERE event_index=1")
        self.assertFalse(self.metadata()["complete"])

    def test_cancel_and_progress_failure_never_publish_complete(self):
        writer = TraceWriter(self.path, limits=TraceLimits(batch_size=3, max_records=None))
        self.addCleanup(writer.close)
        result = self.simulate_to(writer)
        with self.assertRaises(SimulationCancelled):
            writer.finish(self.compiled, result.parameters, result.counts, cancel_check=lambda: True)
        self.assertFalse(self.metadata()["complete"])
        fresh_path = Path(self.temp.name) / "callback.sqlite3"
        callback_writer = TraceWriter(fresh_path, limits=TraceLimits(batch_size=3, max_records=None))
        self.addCleanup(callback_writer.close)
        callback_result = simulate(self.compiled, self.parameters, record_sink=callback_writer.append)
        def fail(_done, _total):
            raise RuntimeError("progress callback failed")
        with self.assertRaisesRegex(RuntimeError, "progress callback failed"):
            callback_writer.finish(self.compiled, callback_result.parameters,
                                   callback_result.counts, progress_callback=fail)
        with sqlite3.connect(fresh_path) as db:
            self.assertEqual(db.execute("SELECT complete FROM metadata").fetchone()[0], 0)

    def test_duplicate_batch_rolls_back_and_writer_lifecycle_is_closed(self):
        writer = TraceWriter(self.path, limits=TraceLimits(batch_size=2, max_records=None))
        self.addCleanup(writer.close)
        result = simulate(self.compiled, default_parameters(draws=2, trials=1, seed=3, trace=True))
        event = result.records[0]
        writer.append(event)
        with self.assertRaises(sqlite3.IntegrityError):
            writer.append(event)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 0)
        self.assertFalse(self.metadata()["complete"])

        self.path = Path(self.temp.name) / "complete.sqlite3"
        writer = TraceWriter(self.path, limits=TraceLimits(max_records=None))
        self.addCleanup(writer.close)
        for saved in result.records:
            writer.append(saved)
        writer.finish(self.compiled, result.parameters, result.counts)
        with self.assertRaises(RuntimeError):
            writer.append(event)
        with self.assertRaises(RuntimeError):
            writer.finish(self.compiled, result.parameters, result.counts)

    def test_finish_rejects_disk_corrupted_probability_and_index_mismatch(self):
        writer = TraceWriter(self.path, limits=TraceLimits(batch_size=1, max_records=None))
        self.addCleanup(writer.close)
        result = simulate(self.compiled, default_parameters(draws=2, trials=1, seed=7, trace=True))
        for event in result.records:
            writer.append(event)
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT event_json FROM events ORDER BY event_index LIMIT 1").fetchone()
            value = json.loads(row[0])
            value["draw_result"]["probabilities"][next(iter(value["draw_result"]["probabilities"]))] = 0.5
            db.execute("UPDATE events SET event_json=? WHERE event_index=1", (json.dumps(value),))
        with self.assertRaises(ValueError):
            writer.finish(self.compiled, result.parameters, result.counts)

    def test_bonus_grant_order_and_wrong_grant_quantities_are_rejected(self):
        params = default_parameters(draws=481, trials=1, seed=11, trace=True)
        result = simulate(self.compiled, params)
        bonus = next(event for event in result.records if event.event_type == "draw" and event.source == "bonus")
        grants = [event for event in result.records if event.event_type == "character_grant"]
        wrong_quantities = list(result.records)
        for grant, quantity in zip(grants, (1, 3), strict=True):
            wrong_quantities[result.records.index(grant)] = replace(
                grant, grant={**grant.grant, "quantity": quantity})
        other = next(c for p in self.compiled.pool.rarity_pools for c in p.characters
                     if c.id != grants[0].grant["character_id"])
        wrong_target = replace(grants[0], grant={**grants[0].grant,
            "character_id": other.id, "rarity_id": other.rarity_id, "character_name": other.name,
            "is_up": other.is_up, "is_limited": other.is_limited})
        cases = ((replace(bonus, main_draws_completed=bonus.main_draws_completed + 1),
                  result.records.index(bonus), result.records),
                 (wrong_target, result.records.index(grants[0]), result.records),
                 (None, -1, wrong_quantities))
        for index, (invalid, position, baseline) in enumerate(cases):
            path = Path(self.temp.name) / f"invalid-{index}.sqlite3"
            writer = TraceWriter(path, limits=TraceLimits(max_records=None))
            self.addCleanup(writer.close)
            bad_records = list(baseline)
            if invalid is not None:
                bad_records[position] = invalid
            for event in bad_records:
                writer.append(event)
            with self.subTest(case=index), self.assertRaises(ValueError):
                writer.finish(self.compiled, result.parameters, result.counts)

    def test_validator_rejects_unknown_fields_and_bool_indexes(self):
        event = simulate(self.compiled, default_parameters(draws=1, trials=1, seed=1, trace=True)).records[0].to_dict()
        for invalid in ({**event, "unexpected": True}, {**event, "event_index": True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_event(invalid)


if __name__ == "__main__":
    unittest.main()
