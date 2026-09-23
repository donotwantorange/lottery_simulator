from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from dashboard.jobs import JobManager, validate_parameters_for_active_rule
from dashboard.models import RunParameters, read_json, write_json
from dashboard.repository import HistoryRepository
from dashboard.trace_export import export_trace
from dashboard.trace_store import TraceFilter, TraceWriter
from dashboard.views.simulation import _render_overview
from lottery_simulator.engine import SimulationCancelled, simulate
from lottery_simulator.rules.pool_config import load_pool_config
from tests.test_simulation_view import RecordingStreamlit


class TraceLifecycleTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.jobs = root / "jobs_v4"
        self.database = root / "history_v4.sqlite3"
        self.manager = JobManager(self.jobs, self.database)

    def test_worker_publishes_only_entered_phases_and_keeps_main_progress(self):
        for trace in (True, False):
            with self.subTest(trace=trace):
                phases = []

                def observe(path, value):
                    write_json(path, value)
                    if Path(path).name == "state.json" and value.get("phase"):
                        phase = value["phase"]
                        if not phases or phases[-1] != phase:
                            phases.append(phase)
                        if phase != "simulating":
                            self.assertEqual((value["completed_units"], value["total_units"]), (4, 4))

                with patch("dashboard.worker.write_json", side_effect=observe):
                    state = self.manager.start(RunParameters("rule1", 2, 2, 29, 42, trace),
                                               synchronous=True)
                self.assertEqual(state.status, "completed")
                self.assertEqual(phases, ["simulating", "theory"] +
                                 (["validating"] if trace else []) + ["saving", "committing"])

    def test_cancellation_inside_theory_validation_and_import_cleans_private_outputs(self):
        for phase in ("theory", "validating", "saving"):
            with self.subTest(phase=phase):
                entered = []

                def cancel_after(callback):
                    def notify(*args):
                        if callback is not None:
                            callback(*args)
                        current = self.manager.get_active()
                        if current.phase == phase:
                            entered.append(phase)
                            self.manager.cancel(current.job_id)
                    return notify

                def controlled_simulate(*args, **kwargs):
                    kwargs["phase_callback"] = cancel_after(kwargs.get("phase_callback"))
                    return simulate(*args, **kwargs)

                finish, save = TraceWriter.finish, HistoryRepository.save_run

                def controlled_finish(writer, **kwargs):
                    kwargs["progress_callback"] = cancel_after(kwargs.get("progress_callback"))
                    return finish(writer, **kwargs)

                def controlled_save(repository, *args, **kwargs):
                    kwargs["progress_callback"] = cancel_after(kwargs.get("progress_callback"))
                    return save(repository, *args, **kwargs)

                with (patch("dashboard.worker.simulate", side_effect=controlled_simulate),
                      patch.object(TraceWriter, "finish", new=controlled_finish),
                      patch.object(HistoryRepository, "save_run", new=controlled_save)):
                    state = self.manager.start(RunParameters("rule1", 2, 2, 29, 42, True),
                                               synchronous=True)
                self.assertEqual(entered, [phase], "cancellation must stop further phase work")
                self.assertEqual(state.status, "cancelled")
                self.assertIsNone(self.manager.get_result(state.job_id))
                self.assertEqual(sorted(p.name for p in (self.jobs / state.job_id).iterdir()),
                                 ["parameters.json", "state.json"])
                if self.database.exists():
                    self.assertEqual(HistoryRepository(self.database).list_runs({}, 20, 0), [])

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
        self.assertEqual((payload["trials"], payload["draws"], payload["bonus_draws"],
                          payload["total_draws"]), (3, 2, 10, 12))
        overview = RecordingStreamlit()
        _render_overview(overview, payload)
        self.assertEqual(overview.dataframes[0], [
            {"范围": "每轮", "主池抽数": 2, "赠送抽数": 10, "总抽数": 12},
            {"范围": "全实验（3轮）", "主池抽数": 6, "赠送抽数": 30, "总抽数": 36},
        ])
        self.assertTrue(any(value.get("实验轮数") == 3 for value in overview.writes))
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
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM draw_records WHERE run_id=?", (non_trace.job_id,)
            ).fetchone()[0], 0)
        repository.delete_run(state.job_id)
        self.assertIsNone(repository.get_run(state.job_id))
        self.assertIsNone(self.manager.get_result(state.job_id))
        self.assertIsNone(self.manager.get_trace_reader(state.job_id))
        with self.assertRaises(ValueError):
            reader.query_records(TraceFilter(), limit=50)

    def test_worker_cancel_at_validation_keeps_evidence_and_no_history(self):
        entered, release, cancelled_in_finish = Event(), Event(), Event()
        original_finish = TraceWriter.finish

        def pause_validation(writer, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("validation was not released")
            try:
                return original_finish(writer, **kwargs)
            except SimulationCancelled:
                cancelled_in_finish.set()
                raise

        with patch.object(TraceWriter, "finish", new=pause_validation):
            with ThreadPoolExecutor(max_workers=1) as pool:
                worker = pool.submit(
                    self.manager.start, RunParameters("rule1", 2, 3, 29, 42, True),
                    synchronous=True,
                )
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    active = self.manager.get_active()
                    self.assertIsNotNone(active)
                    job_dir = self.jobs / active.job_id
                    (job_dir / "worker.log").write_text("worker entered validation", encoding="utf-8")
                    self.assertTrue(self.manager.cancel(active.job_id).cancel_requested)
                finally:
                    release.set()
                state = worker.result(timeout=5)

        self.assertTrue(cancelled_in_finish.is_set())
        self.assertEqual(state.status, "cancelled")
        self.assertIsNone(state.cleanup_error)
        self.assertIsNone(self.manager.get_result(state.job_id))
        if self.database.exists():
            self.assertIsNone(HistoryRepository(self.database).get_run(state.job_id))
        self.assertEqual(sorted(path.name for path in job_dir.iterdir()),
                         ["parameters.json", "state.json", "worker.log"])
        self.assertEqual(read_json(job_dir / "parameters.json")["seed"], 42)
        self.assertEqual(read_json(job_dir / "state.json")["status"], "cancelled")
        self.assertEqual((job_dir / "worker.log").read_text(encoding="utf-8"),
                         "worker entered validation")

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
        self.assertEqual(self.manager.cancel(state.job_id).status, "completed")
        self.manager.reconcile_after_restart()
        self.assertIsNone(HistoryRepository(self.database).get_run(state.job_id))
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
