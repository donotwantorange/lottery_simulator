from contextlib import closing
from dataclasses import replace
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from uuid import uuid4

from dashboard.limits import TraceLimits
from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceFilter, TraceReader, TraceWriter
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1


class TraceQueriesTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.trace_path = self.root / "trace.sqlite3"
        records = list(simulate(
            Rule1(), 81, trials=3, seed=42, initial_pity=29,
            collect_records=True,
        ).records)
        desired = {(1, 1): (4, "same"), (2, 1): (5, "same"), (3, 1): (6, "six"),
                   (1, 2): (4, None), (2, 2): (4, None), (3, 2): (5, "five")}
        adjusted = []
        for record in records:
            key = (record.trial_index, record.source_index)
            if record.source == "main" and key in desired:
                rarity, name = desired[key]
                outcome = replace(record.draw_result.outcome, rarity=rarity, character_name=name)
                record = replace(record, draw_result=replace(record.draw_result, outcome=outcome))
            adjusted.append(record)
        writer = TraceWriter(self.trace_path, limits=TraceLimits(batch_size=17))
        self.addCleanup(writer.close)
        for record in adjusted:
            writer.append(record)
        writer.finish(trials=3, draws=81, initial_main_draws=29, bonus_per_trial=10)

    def test_trace_store_pagination_filters_and_injection_are_safe(self):
        reader = TraceReader.for_trace_store(self.trace_path)
        rows, total = reader.query_records(TraceFilter(trial_from=1, trial_to=1), limit=50)
        self.assertEqual(total, 91)
        self.assertEqual([(row["trial_index"], row["draw_index"]) for row in rows[:2]],
                         [(1, 1), (1, 2)])
        tail, tail_total = reader.query_records(
            TraceFilter(trial_from=1, trial_to=1), limit=50, offset=100,
        )
        self.assertEqual(tail, [])
        self.assertEqual(tail_total, 91)
        named, named_total = reader.query_records(
            TraceFilter(rarity=4, character_name="same'; DROP TABLE records; --"), limit=50,
        )
        self.assertEqual((named, named_total), ([], 0))
        same_four, _ = reader.query_records(TraceFilter(rarity=4, character_name="same"), limit=50)
        same_five, _ = reader.query_records(TraceFilter(rarity=5, character_name="same"), limit=50)
        self.assertEqual(len(same_four), 1)
        self.assertEqual(len(same_five), 1)
        unnamed, unnamed_total = reader.query_records(
            TraceFilter(rarity=4, unnamed_character=True), limit=50,
        )
        self.assertGreaterEqual(unnamed_total, 2)
        self.assertTrue(all(row["draw_result"]["outcome"]["character_name"] is None
                            for row in unnamed))

    def test_filter_and_page_validation(self):
        invalid = (
            {"trial_from": True}, {"trial_from": 0}, {"trial_from": 2, "trial_to": 1},
            {"source": "other"}, {"rarity": 3}, {"character_name": "x"},
            {"rarity": 4, "character_name": "x", "unnamed_character": True},
            {"unnamed_character": 1}, {"source_from": 3, "source_to": 2},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                TraceFilter(**values)
        reader = TraceReader.for_trace_store(self.trace_path)
        for limit, offset in ((49, 0), (100, True), (100, -1)):
            with self.subTest(limit=limit, offset=offset), self.assertRaises(ValueError):
                reader.query_records(TraceFilter(), limit=limit, offset=offset)

    def test_iter_records_uses_full_filter_and_order(self):
        reader = TraceReader.for_trace_store(self.trace_path)
        rows = list(reader.iter_records(
            TraceFilter(source="main", source_from=80, source_to=81), batch_size=2,
        ))
        self.assertEqual(len(rows), 6)
        self.assertEqual([(row["trial_index"], row["source_index"]) for row in rows],
                         [(1, 80), (1, 81), (2, 80), (2, 81), (3, 80), (3, 81)])

    def test_position_counts_have_exact_denominators_and_bonus_is_separate(self):
        reader = TraceReader.for_trace_store(self.trace_path)
        rows = reader.position_counts(
            source="main", trial_from=1, trial_to=3, source_from=1, source_to=2,
        )
        self.assertEqual(rows, [
            {"source_index": 1, "observations": 3, "four_count": 1, "five_count": 1,
             "six_count": 1, "four_rate": 1 / 3, "five_rate": 1 / 3, "six_rate": 1 / 3},
            {"source_index": 2, "observations": 3, "four_count": 2, "five_count": 1,
             "six_count": 0, "four_rate": 2 / 3, "five_rate": 1 / 3, "six_rate": 0.0},
        ])
        eighty_one = reader.position_counts(
            source="main", trial_from=1, trial_to=3, source_from=81, source_to=81,
        )
        self.assertEqual(eighty_one[0]["source_index"], 81)
        self.assertEqual(eighty_one[0]["observations"], 3)
        bonus = reader.position_counts(
            source="bonus", trial_from=1, trial_to=3, source_from=1, source_to=10,
        )
        self.assertEqual(len(bonus), 10)
        self.assertTrue(all(row["observations"] == 3 for row in bonus))
        empty = reader.position_counts(
            source="bonus", trial_from=1, trial_to=3, source_from=11, source_to=11,
        )
        self.assertEqual(empty, [])
        with self.assertRaises(ValueError):
            reader.position_counts(source="main", trial_from=1, trial_to=3,
                                   source_from=1, source_to=1001)

    def test_history_factory_reads_same_rows_and_rejects_missing_target(self):
        history_path = self.root / "history.sqlite3"
        repository = HistoryRepository(history_path)
        repository.initialize()
        run_id = str(uuid4())
        with closing(sqlite3.connect(history_path)) as history, \
                closing(sqlite3.connect(self.trace_path)) as trace:
            history.execute(
                "INSERT INTO simulation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, "2026-09-20T00:00:00+00:00", "rule1", "2.0", 81, 3, 29, 0,
                 "42", 1, 273, "{}", "{}", 4),
            )
            history.executemany(
                "INSERT INTO draw_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ((run_id, *row) for row in trace.execute(
                    "SELECT trial_index, draw_index, source, source_index, rarity, "
                    "character_name, record_json FROM records"
                )),
            )
            history.commit()
        rows, total = repository.get_trace_reader(run_id).query_records(
            TraceFilter(source="main", source_from=81, source_to=81), limit=50,
        )
        self.assertEqual((len(rows), total), (3, 3))
        with self.assertRaises(ValueError):
            repository.get_trace_reader(str(uuid4())).query_records(TraceFilter(), limit=50)


if __name__ == "__main__":
    unittest.main()
