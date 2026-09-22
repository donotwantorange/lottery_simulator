from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dashboard.jobs import JobManager, validate_parameters_for_active_rule
from dashboard.models import RunParameters
from dashboard.repository import HistoryRepository
from dashboard.trace_export import export_trace
from dashboard.trace_store import TraceFilter
from lottery_simulator.rules.pool_config import load_pool_config


class TraceLifecycleTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.jobs = root / "jobs_v4"
        self.database = root / "history_v4.sqlite3"
        self.manager = JobManager(self.jobs, self.database)

    def test_multitrial_trace_publishes_history_and_removes_staging_copy(self):
        config = load_pool_config().to_dict()
        config["four_star_characters"] = [{"name": "四星验收", "weight": 1}]
        config["five_star_characters"] = [{"name": "五星验收", "weight": 1}]
        parameters = RunParameters(
            "rule1", 2, 3, 29, 42, True, pool_config=config,
        )
        save_run = HistoryRepository.save_run

        def inspect_then_save(repository, run_id, payload, **kwargs):
            with closing(sqlite3.connect(kwargs["trace_path"])) as connection:
                self.assertEqual(connection.execute(
                    "SELECT complete, record_count, trials, draws, bonus_per_trial FROM metadata"
                ).fetchone(), (1, 36, 3, 2, 10))
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM records"
                ).fetchone()[0], 36)
            return save_run(repository, run_id, payload, **kwargs)

        with patch.object(HistoryRepository, "save_run", autospec=True,
                          side_effect=inspect_then_save) as save:
            state = self.manager.start(parameters, synchronous=True)
        save.assert_called_once()
        self.assertEqual((state.status, state.history_saved, state.run_id),
                         ("completed", True, state.job_id))
        payload = self.manager.get_result(state.job_id)
        self.assertEqual(payload["record_count"], 36)
        self.assertNotIn("records", payload)
        repository = HistoryRepository(self.database)
        stored = repository.get_run(state.job_id)
        self.assertEqual({key: stored[key] for key in payload}, payload)
        self.assertFalse((self.jobs / state.job_id / "trace.sqlite3").exists())
        reader = self.manager.get_trace_reader(state.job_id)
        rows, total = reader.query_records(TraceFilter(), limit=50)
        self.assertEqual((len(rows), total), (36, 36))
        self.assertEqual(reader.query_records(TraceFilter(), limit=50, offset=50), ([], 36))
        for trial in (1, 2, 3):
            selected = [row for row in rows if row["trial_index"] == trial]
            self.assertEqual([row["draw_index"] for row in selected], list(range(1, 13)))
            self.assertEqual([row["source"] for row in selected],
                             ["main"] + ["bonus"] * 10 + ["main"])
        for rarity, name in ((4, "四星验收"), (5, "五星验收")):
            selected, count = reader.query_records(
                TraceFilter(rarity=rarity, character_name=name), limit=50,
            )
            self.assertGreater(count, 0)
            self.assertEqual(selected, [row for row in rows
                             if row["draw_result"]["outcome"]["rarity"] == rarity])
        for source, last in (("main", 2), ("bonus", 10)):
            positions = reader.position_counts(
                source=source, trial_from=1, trial_to=3, source_from=1, source_to=last,
            )
            self.assertEqual(len(positions), last)
            for position in positions:
                self.assertEqual(position["observations"], 3)
                for rarity, prefix in ((4, "four"), (5, "five"), (6, "six")):
                    expected = sum(row["source"] == source
                                   and row["source_index"] == position["source_index"]
                                   and row["draw_result"]["outcome"]["rarity"] == rarity
                                   for row in rows)
                    self.assertEqual(position[f"{prefix}_count"], expected)
                    self.assertEqual(position[f"{prefix}_rate"], expected / 3)
        output = self.database.parent / "acceptance.jsonl"
        export_trace(self.database, state.job_id, output)
        lines = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 37)
        self.assertEqual((lines[0]["type"], lines[0]["matched_record_count"]), ("metadata", 36))
        self.assertEqual(lines[0]["run"], stored)
        self.assertTrue(all(line["type"] == "record" for line in lines[1:]))
        self.assertEqual([line["record"] for line in lines[1:]], rows)
        with (patch("dashboard.worker.TraceWriter", side_effect=AssertionError),
              patch("lottery_simulator.engine.DrawRecord", side_effect=AssertionError)):
            non_trace = self.manager.start(replace(parameters, trace=False), synchronous=True)
        self.assertEqual(non_trace.status, "completed")
        without = self.manager.get_result(non_trace.job_id)
        excluded = {"duration_seconds", "trace_enabled", "record_count"}
        self.assertEqual({key: value for key, value in payload.items() if key not in excluded},
                         {key: value for key, value in without.items() if key not in excluded})
        self.assertFalse((self.jobs / non_trace.job_id / "trace.sqlite3").exists())
        self.assertNotIn("records", without)
        repository.delete_run(state.job_id)
        self.assertIsNone(repository.get_run(state.job_id))
        self.assertIsNone(self.manager.get_result(state.job_id))
        self.assertIsNone(self.manager.get_trace_reader(state.job_id))
        with self.assertRaises(ValueError):
            reader.query_records(TraceFilter(), limit=50)

    def test_history_failure_keeps_complete_staging_trace_readable(self):
        HistoryRepository(self.database).initialize()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("""
                CREATE TRIGGER fail_save BEFORE INSERT ON simulation_runs
                BEGIN SELECT RAISE(ABORT, 'failure'); END
            """)
        state = self.manager.start(
            RunParameters("rule1", 2, 2, 29, 42, True), synchronous=True,
        )
        self.assertEqual(state.status, "completed")
        self.assertFalse(state.history_saved)
        self.assertEqual(state.persistence_error, "历史保存失败")
        self.assertTrue((self.jobs / state.job_id / "trace.sqlite3").is_file())
        _, total = self.manager.get_trace_reader(state.job_id).query_records(
            TraceFilter(), limit=50,
        )
        self.assertEqual(total, 24)

    def test_deleted_history_is_not_revived_from_job_result(self):
        state = self.manager.start(
            RunParameters("rule1", 2, 2, 29, 42, True), synchronous=True,
        )
        HistoryRepository(self.database).delete_run(state.job_id)
        self.assertIsNone(self.manager.get_result(state.job_id))
        self.assertIsNone(self.manager.get_trace_reader(state.job_id))

    def test_trace_capacity_counts_bonus_and_all_trials(self):
        parameters = RunParameters("rule1", 2, 3, 29, 42, True)
        with patch.dict("os.environ", {"LOTTERY_MAX_TRACE_RECORDS": "36"}, clear=False):
            validate_parameters_for_active_rule(parameters)
        with patch.dict("os.environ", {"LOTTERY_MAX_TRACE_RECORDS": "35"}, clear=False):
            with self.assertRaisesRegex(ValueError, "Trace记录数"):
                validate_parameters_for_active_rule(parameters)


if __name__ == "__main__":
    unittest.main()
