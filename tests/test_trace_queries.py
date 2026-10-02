"""Task 9 event query and export-facing reader contracts."""

from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest

from dashboard.limits import TraceLimits
from dashboard.trace_store import TraceFilter, TraceReader, TraceWriter
from lottery_simulator.engine import simulate_draws as simulate
from tests.fixtures_rules import default_parameters, make_default_compiled


class TraceQueriesTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"
        self.compiled = make_default_compiled()
        parameters = default_parameters(draws=40, trials=3, seed=42, trace=True)
        writer = TraceWriter(self.path, limits=TraceLimits(batch_size=17, max_records=None))
        self.addCleanup(writer.close)
        result = simulate(self.compiled, parameters, record_sink=writer.append)
        writer.finish(self.compiled, result.parameters, result.counts)
        self.reader = TraceReader.for_trace_store(self.path)

    def test_filters_pagination_and_dynamic_ids(self):
        rows = self.reader.query_events(TraceFilter(trial_from=1, trial_to=1), limit=50)
        self.assertEqual(rows[0]["trial_index"], 1)
        self.assertEqual(self.reader.count_events(TraceFilter(trial_from=1, trial_to=1)),
                         sum(row["trial_index"] == 1 for row in self.reader.iter_events(TraceFilter())))
        tail = self.reader.query_events(TraceFilter(), limit=50,
            offset=self.reader.count_events(TraceFilter()) - 1)
        self.assertEqual(len(tail), 1)
        rarity_id = self.compiled.rule.rarities[0].id
        selected = self.reader.query_events(TraceFilter(rarity_id=rarity_id, event_type="draw"), limit=50)
        self.assertTrue(all(event["draw_result"]["outcome"]["rarity_id"] == rarity_id for event in selected))

    def test_keyset_iterator_and_draw_only_position_counts(self):
        events = list(self.reader.iter_events(TraceFilter(source="main", source_from=1,
                                                          source_to=2), batch_size=2))
        self.assertEqual(len(events), 6)
        rows = self.reader.position_counts(source="main", trial_from=1, trial_to=3,
                                           source_from=1, source_to=2)
        self.assertEqual([row["observations"] for row in rows], [3, 3])
        self.assertTrue(all(sum(row["rarity_counts"].values()) == row["observations"] for row in rows))
        self.assertTrue(all(event["event_type"] == "draw" for event in events))

    def test_filters_and_pages_reject_bad_values(self):
        for values in ({"trial_from": True}, {"trial_from": 0},
                       {"source": "invalid"}, {"rarity_id": "nope"},
                       {"event_type": "other"}, {"character_id": "bad", "unnamed_character": True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                TraceFilter(**values)
        for limit, offset in ((0, 0), (True, 0), (10, -1)):
            with self.subTest(limit=limit, offset=offset), self.assertRaises(ValueError):
                self.reader.query_events(TraceFilter(), limit=limit, offset=offset)

    def test_two_grants_are_events_and_never_position_observations(self):
        compiled = replace(self.compiled, rule=replace(self.compiled.rule,
                           grant=replace(self.compiled.rule.grant, quantity=2)))
        path = Path(self.temp.name) / "grants.sqlite3"
        writer = TraceWriter(path, limits=TraceLimits(max_records=None))
        self.addCleanup(writer.close)
        result = simulate(compiled, default_parameters(draws=480, trials=1, seed=7, trace=True),
                          record_sink=writer.append)
        writer.finish(compiled, result.parameters, result.counts)
        reader = TraceReader.for_trace_store(path)
        grants = reader.query_events(TraceFilter(event_type="character_grant"), limit=50, offset=0)
        self.assertEqual(len(grants), 2)
        self.assertEqual(sum(event["grant"]["quantity"] for event in grants), 4)
        self.assertTrue(all(event["source"] is None and "draw_result" not in event for event in grants))
        rows = reader.position_counts(source="main", trial_from=1, trial_to=1,
                                      source_from=239, source_to=241)
        self.assertEqual([row["observations"] for row in rows], [1, 1, 1])


if __name__ == "__main__":
    unittest.main()
