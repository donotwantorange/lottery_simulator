from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from dashboard.jobs import JobAlreadyRunning, JobManager, validate_parameters_for_active_rule
from dashboard.models import JobState, RunParameters, read_json, result_payload, write_json
from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceFilter
from dashboard.views.configuration import render_pool_config_editor, set_pool_config_editor_state
from lottery_simulator.engine import simulate
from lottery_simulator.rules.pool_config import PoolConfig, load_pool_config
from lottery_simulator.rules.rule_1 import Rule1
from tests.test_configuration_view import EditorBoundary


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"completed", "cancelled", "failed"}


class JobManagerTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "jobs"
        self.database = Path(directory.name) / "history.sqlite3"
        self.manager = JobManager(self.root, self.database)
        self.repository = HistoryRepository(self.database)
        self.repository.initialize()
        self.parameters = RunParameters("rule1", 2, 1, 29, 42, True)
        self.processes = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        # Only test-owned processes/worker directories may be stopped here.
        self.manager.reconcile_after_restart()
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            workers = self.live_workers()
            if not workers:
                return
            time.sleep(0.01)
        self.fail(f"test workers did not exit: {workers}")

    def live_workers(self):
        workers = []
        for process_dir in Path("/proc").glob("[0-9]*"):
            try:
                arguments = (process_dir / "cmdline").read_bytes().split(b"\0")
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
            if (len(arguments) > 3 and arguments[1:3] == [b"-m", b"dashboard.worker"]
                    and Path(os.fsdecode(arguments[3])).parent == self.root):
                workers.append(int(process_dir.name))
        return workers

    def wait_for(self, job_id, statuses=TERMINAL, progress=False):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.manager.get(job_id)
            if state.status in statuses and (not progress or state.completed_units > 0):
                return state
            if state.status in TERMINAL and state.status not in statuses:
                self.fail(f"unexpected terminal state: {state}")
            time.sleep(0.01)
        self.fail(f"job deadline exceeded: {self.manager.get(job_id)}")

    def wait_for_status(self, job_id, status, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.manager.get(job_id)
            if state is not None and state.status == status:
                return state
            time.sleep(0.01)
        self.fail(f"job did not reach {status}: {self.manager.get(job_id)}")

    def counts(self):
        with closing(sqlite3.connect(self.database)) as connection:
            return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                         for table in ("simulation_runs", "draw_records"))

    def prepare_job(self, status="queued", pid=None, parameters=None):
        parameters = parameters or self.parameters
        if parameters.pool_config is None:
            parameters = replace(parameters, pool_config=load_pool_config().to_dict())
        state = JobState(str(uuid4()), status, parameters, 0,
                         parameters.draws * parameters.trials, pid=pid,
                         phase=self._prepared_phase,
                         phase_completed=self._prepared_phase_completed,
                         phase_total=self._prepared_phase_total)
        job_dir = self.root / state.job_id
        write_json(job_dir / "parameters.json", parameters.to_dict())
        write_json(job_dir / "state.json", state.to_dict())
        return state, job_dir

    _prepared_phase = None
    _prepared_phase_completed = None
    _prepared_phase_total = None

    def prepare_controlled_job(self, status="queued", pid=None, parameters=None):
        self._prepared_phase = "theory"
        self._prepared_phase_completed = 1
        self._prepared_phase_total = 2
        try:
            return self.prepare_job(status, pid, parameters)
        finally:
            self._prepared_phase = None
            self._prepared_phase_completed = None
            self._prepared_phase_total = None

    def assert_phase_progress_cleared(self, state):
        self.assertIsNone(state.phase)
        self.assertIsNone(state.phase_completed)
        self.assertIsNone(state.phase_total)

    def launch_worker(self, job_dir):
        process = subprocess.Popen(
            [sys.executable, "-m", "dashboard.worker", str(job_dir), str(self.database)],
            cwd=PROJECT_ROOT, start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.processes.append(process)
        return process

    def test_completed_job_has_separate_result_and_saves_once(self):
        queued = self.manager.start(self.parameters)
        state = self.wait_for(queued.job_id)
        self.assertEqual(state.status, "completed")
        self.assertEqual((state.completed_units, state.total_units), (2, 2))
        self.assertEqual(state.parameters["seed"], 42)
        self.assertEqual(state.result_path, "result.json")
        self.assertIsNone(state.persistence_error)
        self.assertGreater(state.pid, 0)
        self.assertIsNotNone(state.started_at)
        self.assertGreaterEqual(state.duration_seconds, 0)
        payload = self.manager.get_result(state.job_id)
        self.assertEqual((payload["seed"], payload["main_draws"], payload["bonus_draws"]),
                         (42, 2, 10))
        self.assertNotIn("records", payload)
        self.assertEqual(len(list(self.manager.get_trace_reader(state.job_id).iter_records(
            TraceFilter(), batch_size=5))), 12)
        self.assertEqual(self.counts(), (1, 12))
        job_dir = self.root / state.job_id
        self.assertEqual(read_json(job_dir / "parameters.json"), state.parameters)
        self.assertNotIn("records", read_json(job_dir / "state.json"))
        self.assertLess((job_dir / "state.json").stat().st_size, 2000)
        self.assertEqual(list(job_dir.glob("*.tmp")), [])
        self.assertEqual(self.manager.cancel(state.job_id).status, "completed")
        self.assertEqual(self.counts(), (1, 12))

    def test_cancel_after_history_commit_clears_phase_progress(self):
        state, _ = self.prepare_controlled_job("running")
        with patch.object(
            HistoryRepository, "get_run", return_value={"id": state.job_id}
        ):
            completed = self.manager.cancel(state.job_id)

        self.assertEqual(completed.status, "completed")
        self.assert_phase_progress_cleared(completed)

    def test_worker_launch_failure_clears_terminal_phase_progress(self):
        with patch("dashboard.jobs.subprocess.Popen", side_effect=OSError("launch")):
            with self.assertRaisesRegex(RuntimeError, "启动失败"):
                self.manager.start(self.parameters)

        states = [self.manager.get(path.parent.name)
                  for path in self.root.glob("*/state.json")]
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].status, "failed")
        self.assert_phase_progress_cleared(states[0])

    def test_edited_optional_rosters_bonus_trace_and_v4_history_round_trip(self):
        raw = load_pool_config().to_dict()
        raw["four_star_characters"] = [
            {"name": "四星甲", "weight": 1},
            {"name": "四星乙", "weight": 3},
        ]
        raw["five_star_characters"] = [{"name": "五星甲"}]
        imported = PoolConfig.from_dict(raw)
        editor = EditorBoundary()
        set_pool_config_editor_state(editor, imported)
        characters = deepcopy(editor.session_state["pool_character_rows"])
        rewards = deepcopy(editor.session_state["pool_reward_rows"])
        editor.session_state["pool_up_share"] = 0.6
        characters[0].update({"角色名称": "集成UP", "UP权重": 2})
        rewards[0]["六星"] = 30
        editor.edited_rows = {
            "pool_character_editor": characters,
            "pool_reward_editor": rewards,
        }

        edited = render_pool_config_editor(editor)
        self.assertEqual(edited.four_star_characters, imported.four_star_characters)
        self.assertEqual(edited.five_star_characters, imported.five_star_characters)
        self.assertEqual(edited.up_share, 0.6)
        self.assertEqual(edited.six_star_characters[0].name, "集成UP")
        self.assertEqual(edited.rewards[0].six_star, 30)

        parameters = RunParameters(
            "rule1", 1, 1, 29, 42, True, pool_config=edited.to_dict()
        )
        first_state = self.manager.start(parameters, synchronous=True)
        first = self.manager.get_result(first_state.job_id)
        records = list(self.manager.get_trace_reader(first_state.job_id).iter_records(
            TraceFilter(), batch_size=5))

        self.assertEqual(first_state.status, "completed")
        self.assertEqual(first["seed"], 42)
        self.assertEqual((first["initial_main_draws"], first["final_main_draws"]), (29, 30))
        self.assertEqual(
            (first["pool_config"]["format_version"], first["result_format_version"],
             first["sampling_version"]),
            (1, 2, 1),
        )
        self.assertEqual(first["pool_config"], edited.to_dict())
        self.assertEqual(len(records), 11)
        self.assertEqual([record["source"] for record in records], ["main"] + ["bonus"] * 10)
        self.assertEqual({record["main_draws_completed"] for record in records}, {30})
        self.assertEqual({record["record_format_version"] for record in records}, {2})
        main_state = records[0]["main_state_after"]
        for record in records[1:]:
            self.assertEqual(record["main_state_before"], main_state)
            self.assertEqual(record["main_state_after"], main_state)

        names_by_rarity = {
            4: {character.name for character in edited.four_star_characters},
            5: {character.name for character in edited.five_star_characters},
            6: {character.name for character in edited.six_star_characters},
        }
        for record in records:
            outcome = record["draw_result"]["outcome"]
            self.assertIn(outcome["character_name"], names_by_rarity[outcome["rarity"]])

        runs = self.repository.list_runs({}, 10, 0)
        self.assertEqual(len(runs), 1)
        first_run_id = runs[0]["id"]
        stored = self.repository.get_run(first_run_id)
        self.assertEqual(stored["schema_version"], 4)
        self.assertEqual(stored["pool_config"], edited.to_dict())
        self.assertEqual(list(self.repository.get_trace_reader(first_run_id).iter_records(
            TraceFilter(), batch_size=5)), records)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)

        second_state = self.manager.start(parameters, synchronous=True)
        second = self.manager.get_result(second_state.job_id)
        self.assertEqual(second_state.status, "completed")
        self.assertIsNone(second_state.persistence_error)
        self.assertNotIn("records", second)
        runs = self.repository.list_runs({}, 10, 0)
        self.assertEqual(len(runs), 2)
        second_run_ids = {run["id"] for run in runs} - {first_run_id}
        self.assertEqual(len(second_run_ids), 1)
        second_stored_id = second_run_ids.pop()
        self.assertEqual(list(self.repository.get_trace_reader(second_stored_id).iter_records(
            TraceFilter(), batch_size=5)), records)

    def test_get_result_rejects_missing_or_mismatched_versions(self):
        state = self.manager.start(self.parameters, synchronous=True)
        job_dir = self.root / state.job_id
        original = read_json(job_dir / "result.json")
        self.assertIsNotNone(self.manager.get_result(state.job_id))

        for field, value in (("result_format_version", None), ("sampling_version", 2)):
            with self.subTest(field=field):
                invalid = dict(original)
                if value is None:
                    invalid.pop(field)
                else:
                    invalid[field] = value
                write_json(job_dir / "result.json", invalid)
                self.assertIsNone(self.manager.get_result(state.job_id))

    def test_invalid_state_version_is_skipped_and_cannot_drive_kill(self):
        state, job_dir = self.prepare_job("running", os.getpid())
        raw = read_json(job_dir / "state.json")
        raw.pop("job_format_version", None)
        write_json(job_dir / "state.json", raw)

        with (patch("dashboard.jobs.os.kill", side_effect=AssertionError("unsafe signal")),
              self.assertLogs("dashboard.jobs", level="WARNING")):
            self.manager.reconcile_after_restart()

        self.assertIsNone(self.manager.get(state.job_id))
        self.assertFalse((job_dir / "cancel.request").exists())
        following = self.manager.start(self.parameters, synchronous=True)
        self.assertEqual(following.status, "completed")

    def test_worker_rejects_unversioned_parameters_before_running(self):
        state, job_dir = self.prepare_controlled_job()
        raw = read_json(job_dir / "parameters.json")
        raw.pop("job_format_version", None)
        write_json(job_dir / "parameters.json", raw)
        written_statuses = []

        def record_write(path, value):
            if Path(path).name == "state.json":
                written_statuses.append(value.get("status"))
            write_json(path, value)

        with (patch("dashboard.worker.write_json", side_effect=record_write),
              patch("dashboard.worker.simulate") as simulate_mock,
              self.assertLogs("dashboard.worker", level="ERROR")):
            from dashboard.worker import run
            run(job_dir, self.database)

        simulate_mock.assert_not_called()
        self.assertEqual(written_statuses, ["failed"])
        self.assertNotIn("running", written_statuses)
        failed = self.manager.get(state.job_id)
        self.assertEqual(failed.status, "failed")
        self.assert_phase_progress_cleared(failed)
        self.assertIsNone(failed.result_path)
        self.assertFalse((job_dir / "result.json").exists())
        self.assertEqual(self.counts(), (0, 0))

    def test_worker_terminal_states_clear_phase_progress(self):
        from dashboard.worker import run
        from lottery_simulator.engine import SimulationCancelled

        cases = (
            ("completed", None),
            ("cancelled", SimulationCancelled()),
            ("failed", ValueError("test failure")),
        )
        for expected_status, simulated_error in cases:
            with self.subTest(status=expected_status):
                state, job_dir = self.prepare_controlled_job()
                if simulated_error is None:
                    simulation = patch("dashboard.worker.simulate", wraps=simulate)
                else:
                    simulation = patch(
                        "dashboard.worker.simulate", side_effect=simulated_error
                    )
                with simulation:
                    run(job_dir, self.database)
                terminal = self.manager.get(state.job_id)
                self.assertEqual(terminal.status, expected_status)
                self.assert_phase_progress_cleared(terminal)

    def test_progress_and_cancel_leave_no_result_or_history(self):
        parameters = replace(self.parameters, draws=10_000, trials=10_000, trace=False)
        state = self.manager.start(parameters)
        running = self.wait_for(state.job_id, {"running"}, progress=True)
        self.assertLess(running.completed_units, running.total_units)
        self.assertIsNone(self.manager.get_result(state.job_id))
        self.manager.cancel(state.job_id)
        cancelled = self.wait_for(state.job_id)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertLess(cancelled.completed_units, cancelled.total_units)
        self.assertIsNone(cancelled.result_path)
        self.assertIsNone(self.manager.get_result(state.job_id))
        self.assertFalse((self.root / state.job_id / "result.json").exists())
        self.assertEqual(self.counts(), (0, 0))
        following = self.manager.start(self.parameters)
        self.assertNotEqual(following.job_id, state.job_id)
        self.assertEqual(self.wait_for(following.job_id).status, "completed")

    def test_second_manager_cannot_start_an_active_job(self):
        state = self.manager.start(replace(self.parameters, draws=10_000, trials=10_000,
                                           trace=False))
        other_manager = JobManager(self.root, self.database)
        with self.assertRaises(JobAlreadyRunning):
            other_manager.start(self.parameters)
        self.manager.cancel(state.job_id)
        self.assertEqual(self.wait_for(state.job_id).status, "cancelled")

    def test_synchronous_start_uses_real_worker_and_persistence(self):
        state = self.manager.start(self.parameters, synchronous=True)
        self.assertEqual(state.status, "completed")
        self.assertEqual((state.completed_units, state.total_units), (2, 2))
        self.assertEqual(state.pid, os.getpid())
        self.assertEqual(self.manager.get_result(state.job_id)["seed"], 42)
        self.assertEqual(self.counts(), (1, 12))

    def test_synchronous_start_rejects_invalid_and_already_active_jobs(self):
        with self.assertRaises(ValueError):
            self.manager.start(replace(self.parameters, draws=0), synchronous=True)
        for field in ("job_format_version", "sampling_version"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "版本不支持"):
                self.manager.start(
                    replace(self.parameters, **{field: 3 if field == "job_format_version" else 2}), synchronous=True
                )
        self.assertEqual(list(self.root.glob("*/state.json")), [])
        state, _ = self.prepare_job()
        with self.assertRaises(JobAlreadyRunning):
            self.manager.start(self.parameters, synchronous=True)
        self.assertEqual([path.parent.name for path in self.root.glob("*/state.json")],
                         [state.job_id])
        self.assertEqual(self.counts(), (0, 0))

    def test_start_rejects_initial_pity_outside_the_active_rule_before_creating_a_job(self):
        invalid = replace(self.parameters, initial_pity=80)
        with patch("dashboard.jobs.subprocess.Popen",
                   side_effect=AssertionError("invalid parameters reached worker launch")):
            with self.assertRaisesRegex(ValueError, "0 到 79"):
                self.manager.start(invalid)
        self.assertEqual(list(self.root.glob("*/state.json")), [])
        self.assertEqual(self.counts(), (0, 0))

    def test_start_rejects_initial_five_star_pity_outside_snapshot_before_creating_job(self):
        config = load_pool_config().to_dict()
        config["five_star"]["hard_pity"] = 8
        invalid = RunParameters("rule1", 2, 1, 0, 42, True, 8, config)

        with self.assertRaisesRegex(ValueError, "初始五星保底必须在 0 到 7"):
            self.manager.start(invalid, synchronous=True)

        self.assertEqual(list(self.root.glob("*/state.json")), [])
        self.assertEqual(self.counts(), (0, 0))

    def test_start_rejects_nonzero_five_star_pity_when_snapshot_disables_it(self):
        config = load_pool_config().to_dict()
        config["five_star"]["pity_enabled"] = False
        invalid = RunParameters("rule1", 2, 1, 0, 42, True, 1, config)

        with self.assertRaisesRegex(ValueError, "关闭五星保底时.*必须为 0"):
            self.manager.start(invalid, synchronous=True)

        self.assertEqual(list(self.root.glob("*/state.json")), [])
        self.assertEqual(self.counts(), (0, 0))

    def test_invalid_bonus_configuration_is_rejected_before_admission_and_job_creation(self):
        config = load_pool_config().to_dict()
        config["five_star"].update(base_probability=1.0, hard_pity=1)
        for draws in (29, 30, 31):
            with self.subTest(draws=draws):
                parameters = RunParameters("rule1", draws, 1, 0, 42, False, 0, config)
                with self.assertRaisesRegex(ValueError, "赠送池.*五星.*六星"):
                    validate_parameters_for_active_rule(parameters)
                with self.assertRaisesRegex(ValueError, "赠送池.*五星.*六星"):
                    self.manager.start(parameters, synchronous=True)
                self.assertEqual(list(self.root.glob("*/state.json")), [])
                self.assertEqual(self.counts(), (0, 0))

    def test_default_configuration_is_frozen_into_job_parameters_before_worker(self):
        state = self.manager.start(self.parameters, synchronous=True)

        self.assertEqual(state.parameters["pool_config"], load_pool_config().to_dict())
        self.assertEqual(
            read_json(self.root / state.job_id / "parameters.json")["pool_config"],
            load_pool_config().to_dict(),
        )

    def test_worker_uses_serialized_pool_config_and_initial_five_pity(self):
        config = load_pool_config().to_dict()
        config["up_share"] = 0.6
        parameters = RunParameters("rule1", 10, 1, 0, 42, True, 7, config)

        state = self.manager.start(parameters, synchronous=True)
        payload = self.manager.get_result(state.job_id)

        self.assertEqual(payload["pool_config"]["up_share"], 0.6)
        self.assertEqual(payload["initial_five_star_pity"], 7)

    def test_worker_does_not_reload_default_configuration(self):
        config = load_pool_config().to_dict()
        parameters = RunParameters("rule1", 2, 1, 0, 42, True, 0, config)

        with patch("lottery_simulator.rules.rule_1.load_pool_config",
                   side_effect=AssertionError("worker reloaded default config")):
            state = self.manager.start(parameters, synchronous=True)

        self.assertEqual(state.status, "completed")

    def test_worker_cold_import_and_snapshot_rule_never_open_default_configuration(self):
        serialized = json.dumps(load_pool_config().to_dict())
        script = f'''
import json
from pathlib import Path

real_open = Path.open
def reject_default(path, *args, **kwargs):
    if path.name == "rule1_default.json":
        raise AssertionError("cold worker read default configuration")
    return real_open(path, *args, **kwargs)
Path.open = reject_default

import dashboard.worker
from lottery_simulator.engine import simulate
from lottery_simulator.rules.pool_config import PoolConfig
from lottery_simulator.rules.rule_1 import Rule1

config = PoolConfig.from_dict(json.loads({serialized!r}))
rule = Rule1(config=config)
result = simulate(rule, 1, seed=42)
assert result.pool_config == config.to_dict()
'''

        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=PROJECT_ROOT,
            text=True, capture_output=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_start_waits_for_flock_before_checking_and_creating(self):
        self.root.mkdir(parents=True, exist_ok=True)
        script = (
            "from dashboard.jobs import JobAlreadyRunning, JobManager; "
            "from dashboard.models import RunParameters; import sys; "
            "manager=JobManager(sys.argv[1], sys.argv[2]); "
            "print('ready', flush=True); "
            "manager.start(RunParameters('rule1', 2, 1, 29, 42, True))"
        )
        with (self.root / "active.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            process = subprocess.Popen([sys.executable, "-u", "-c", script,
                                        str(self.root), str(self.database)], cwd=PROJECT_ROOT,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.processes.append(process)
            self.assertTrue(select.select([process.stdout], [], [], 3)[0])
            self.assertEqual(process.stdout.readline().strip(), "ready")
            time.sleep(0.1)
            self.assertIsNone(process.poll(), "start ignored active.lock")
            self.assertEqual(list(self.root.glob("*/state.json")), [])
            state, _ = self.prepare_job()
            fcntl.flock(lock, fcntl.LOCK_UN)
        output, error = process.communicate(timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("JobAlreadyRunning", error)
        self.assertEqual([path.parent.name for path in self.root.glob("*/state.json")],
                         [state.job_id])

    def test_lock_remains_held_between_active_check_and_job_creation(self):
        entered, release = Event(), Event()

        def pause_creation(path, value):
            if path.name == "parameters.json" and not entered.is_set():
                entered.set()
                if not release.wait(timeout=3):
                    raise TimeoutError("test did not release job creation")
            write_json(path, value)

        parameters = replace(self.parameters, draws=10_000, trials=10_000, trace=False)
        other_manager = JobManager(self.root, self.database)
        with patch("dashboard.jobs.write_json", new=pause_creation), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.manager.start, parameters)
            try:
                self.assertTrue(entered.wait(timeout=3))
                second = pool.submit(other_manager.start, parameters)
                time.sleep(0.05)
                self.assertFalse(second.done(), "lock was released before creating the job")
                self.assertEqual(list(self.root.glob("*/state.json")), [])
            finally:
                release.set()
            state = first.result(timeout=3)
            with self.assertRaises(JobAlreadyRunning):
                second.result(timeout=3)
        self.manager.cancel(state.job_id)
        self.assertEqual(self.wait_for(state.job_id).status, "cancelled")

    def test_recovery_never_signals_invalid_pids_or_when_proc_is_unreadable(self):
        states = [self.prepare_job("running", pid)[0] for pid in (None, -1, 0, True, "42")]
        with patch("dashboard.jobs.os.kill", side_effect=AssertionError("unsafe signal")):
            self.manager.reconcile_after_restart()
        states.append(self.prepare_job("running", os.getpid())[0])
        with (patch("dashboard.jobs.Path.read_bytes", side_effect=PermissionError("no proc")),
              patch("dashboard.jobs.os.kill", side_effect=AssertionError("unverified signal"))):
            self.manager.reconcile_after_restart()
        self.assertTrue(all(self.manager.get(state.job_id).status == "failed" for state in states[:-1]))
        self.assertEqual(self.manager.get(states[-1].job_id).status, "running")

    def test_recovery_cleans_uncommitted_files_only_after_worker_exit(self):
        state, job_dir = self.prepare_controlled_job("running", 123456)
        partials = [job_dir / name for name in (
            "result.json", "trace.sqlite3", "trace.sqlite3-wal",
            "trace.sqlite3-shm", "trace.sqlite3-journal",
        )]
        for path in partials:
            path.touch()
        checks = []

        def worker_running(*args):
            checks.append(1)
            self.assertTrue(all(path.exists() for path in partials))
            self.assertEqual(self.manager.get(state.job_id).status, "running")
            return len(checks) < 3

        with (patch.object(self.manager, "_is_worker", side_effect=worker_running),
              patch("dashboard.jobs.os.kill")):
            self.manager.reconcile_after_restart()
        self.assertGreaterEqual(len(checks), 3)
        failed = self.manager.get(state.job_id)
        self.assertEqual(failed.status, "failed")
        self.assert_phase_progress_cleared(failed)
        self.assertFalse(any(path.exists() for path in partials))

    def test_recovery_signal_denied_keeps_active_files_and_blocks_admission(self):
        state, job_dir = self.prepare_job("running", 123456)
        (job_dir / "trace.sqlite3").touch()
        with (patch.object(self.manager, "_is_worker", return_value=True),
              patch("dashboard.jobs.os.kill", side_effect=PermissionError)):
            self.manager.reconcile_after_restart()
        self.assertEqual(self.manager.get(state.job_id).status, "running")
        self.assertTrue((job_dir / "trace.sqlite3").exists())
        with self.assertRaises(JobAlreadyRunning):
            self.manager.start(self.parameters, synchronous=True)

    def test_committed_recovery_waits_for_worker_exit_before_publishing_or_cleanup(self):
        completed = self.manager.start(self.parameters, synchronous=True)
        job_dir = self.root / completed.job_id
        write_json(job_dir / "state.json", replace(
            completed, status="running", history_saved=False, run_id=None,
        ).to_dict())
        (job_dir / "trace.sqlite3").touch()
        with (patch.object(self.manager, "_is_worker", return_value=True),
              patch("dashboard.jobs.os.kill", side_effect=PermissionError)):
            self.manager.reconcile_after_restart()
        self.assertEqual(self.manager.get(completed.job_id).status, "running")
        self.assertTrue((job_dir / "trace.sqlite3").exists())
        with patch.object(self.manager, "_is_worker", return_value=False):
            self.manager.reconcile_after_restart()
        recovered = self.manager.get(completed.job_id)
        self.assertEqual(recovered.status, "completed")
        self.assert_phase_progress_cleared(recovered)
        self.assertFalse((job_dir / "trace.sqlite3").exists())

    def test_reaper_cleans_uncommitted_result_and_trace_after_wait(self):
        state, job_dir = self.prepare_job("running")
        partials = [job_dir / name for name in ("result.json", "trace.sqlite3", "trace.sqlite3-wal")]
        for path in partials:
            path.touch()
        testcase = self

        class ExitedProcess:
            def wait(self):
                testcase.assertTrue(all(path.exists() for path in partials))
                return 1

        self.manager._reap(ExitedProcess(), state.job_id)
        self.assertFalse(any(path.exists() for path in partials))
        self.assertEqual(self.manager.get(state.job_id).status, "failed")

    def test_recovery_marks_queued_and_running_failed_without_a_live_pid(self):
        states = [self.prepare_controlled_job("running", 2_147_483_647)[0],
                  self.prepare_controlled_job()[0]]
        self.manager.reconcile_after_restart()
        for state in states:
            recovered = self.manager.get(state.job_id)
            self.assertEqual(recovered.status, "failed")
            self.assertEqual(recovered.error, "服务重启，未完成任务已停止")
            self.assert_phase_progress_cleared(recovered)
        self.assertEqual(self.counts(), (0, 0))

    def test_recovery_terminates_verified_worker_and_keeps_failed_state(self):
        state = self.manager.start(replace(self.parameters, draws=10_000, trials=10_000,
                                           trace=False))
        running = self.wait_for(state.job_id, {"running"}, progress=True)
        self.assertIn(running.pid, self.live_workers())
        self.manager.reconcile_after_restart()
        self.assertEqual(self.manager.get(state.job_id).status, "failed")
        deadline = time.monotonic() + 3
        while self.live_workers() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.live_workers(), [])
        self.assertEqual(self.manager.get(state.job_id).status, "failed")
        self.assertEqual(self.counts(), (0, 0))

    def test_recovery_does_not_signal_an_unrelated_process(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.processes.append(process)
        state, _ = self.prepare_job("running", process.pid)
        self.manager.reconcile_after_restart()
        self.assertEqual(self.manager.get(state.job_id).status, "failed")
        time.sleep(0.05)
        self.assertIsNone(process.poll())

    def test_reaper_marks_an_unexpected_child_exit_failed_without_history(self):
        real_popen = subprocess.Popen

        def exited_worker(*unused_args, **unused_kwargs):
            process = real_popen(
                [sys.executable, "-c", "raise SystemExit(7)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.processes.append(process)
            return process

        with patch("dashboard.jobs.subprocess.Popen", side_effect=exited_worker):
            state = self.manager.start(self.parameters)

        failed = self.wait_for_status(state.job_id, "failed")
        self.assertEqual(failed.error, "模拟任务失败")
        self.assert_phase_progress_cleared(failed)
        self.assertIsNone(self.manager.get_result(state.job_id))
        self.assertEqual(self.counts(), (0, 0))

    def test_reaper_never_overwrites_worker_completed_or_cancelled_state(self):
        class ExitedProcess:
            def wait(self):
                return 1

        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                state, _ = self.prepare_job(status)
                self.manager._reap(ExitedProcess(), state.job_id)
                self.assertEqual(self.manager.get(state.job_id).status, status)

    def test_reaper_ignores_a_job_root_removed_after_the_child_exits(self):
        class ExitedProcess:
            def wait(self):
                return 1

        self.addCleanup(self.root.mkdir, parents=True, exist_ok=True)
        self.root.rmdir()

        self.manager._reap(ExitedProcess(), str(uuid4()))
        self.assertFalse(self.root.exists())

    def test_restart_crash_window_keeps_committed_history_once_when_state_is_active(self):
        completed = self.manager.start(self.parameters, synchronous=True)
        job_dir = self.root / completed.job_id
        write_json(job_dir / "state.json", replace(completed, status="running").to_dict())

        self.manager.reconcile_after_restart()

        recovered = self.manager.get(completed.job_id)
        self.assertEqual(recovered.status, "completed")
        self.assert_phase_progress_cleared(recovered)
        self.assertTrue(recovered.history_saved)
        self.assertEqual(self.counts(), (1, 12))
        self.assertEqual([row["id"] for row in self.repository.list_runs({}, 10, 0)],
                         [completed.job_id])

    def test_reaper_recovers_committed_history_before_restart(self):
        class ExitedProcess:
            def wait(self):
                return 1

        completed = self.manager.start(replace(self.parameters, trials=3), synchronous=True)
        job_dir = self.root / completed.job_id
        write_json(job_dir / "state.json", replace(
            completed, status="running", history_saved=False, run_id=None,
            result_path=None, phase="theory", phase_completed=1, phase_total=2,
        ).to_dict())

        self.manager._reap(ExitedProcess(), completed.job_id)
        self.manager.reconcile_after_restart()

        recovered = self.manager.get(completed.job_id)
        self.assertEqual(recovered.status, "completed")
        self.assertTrue(recovered.history_saved)
        self.assertEqual(recovered.run_id, completed.job_id)
        self.assertEqual(self.manager.get_result(completed.job_id)["seed"], 42)
        self.assertEqual(self.counts(), (1, 36))

    def test_recovery_preserves_result_when_history_commit_cannot_be_checked(self):
        class ExitedProcess:
            def wait(self):
                return 1

        for via_reaper in (False, True):
            with self.subTest(via_reaper=via_reaper):
                completed = self.manager.start(self.parameters, synchronous=True)
                job_dir = self.root / completed.job_id
                write_json(job_dir / "state.json", replace(
                    completed, status="running", history_saved=False, run_id=None,
                ).to_dict())
                before = (job_dir / "result.json").read_bytes()
                with patch.object(HistoryRepository, "get_run", side_effect=sqlite3.DatabaseError("unavailable")):
                    if via_reaper:
                        self.manager._reap(ExitedProcess(), completed.job_id)
                    else:
                        self.manager.reconcile_after_restart()
                self.assertEqual(self.manager.get(completed.job_id).status, "running")
                self.assertEqual((job_dir / "result.json").read_bytes(), before)
                self.manager.reconcile_after_restart()
                self.assertEqual(self.manager.get(completed.job_id).status, "completed")

    def test_reaper_preserves_result_while_history_database_is_temporarily_missing(self):
        class ExitedProcess:
            def wait(self):
                return 1

        completed = self.manager.start(self.parameters, synchronous=True)
        job_dir = self.root / completed.job_id
        write_json(job_dir / "state.json", replace(
            completed, status="running", history_saved=False, run_id=None,
        ).to_dict())
        original_result = (job_dir / "result.json").read_bytes()
        offline_database = self.database.with_name("history.offline.sqlite3")
        self.database.rename(offline_database)
        try:
            self.manager._reap(ExitedProcess(), completed.job_id)
            self.assertEqual(self.manager.get(completed.job_id).status, "running")
            self.assertEqual((job_dir / "result.json").read_bytes(), original_result)
        finally:
            offline_database.rename(self.database)
        self.manager.reconcile_after_restart()
        self.assertEqual(self.manager.get(completed.job_id).status, "completed")

    def test_persistence_failure_keeps_completed_result_and_safe_error(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript("""
                CREATE TRIGGER fail_save BEFORE INSERT ON simulation_runs
                BEGIN SELECT RAISE(ABORT, 'private database failure'); END;
            """)
        state = self.wait_for(self.manager.start(self.parameters).job_id)
        self.assertEqual(state.status, "completed")
        self.assertIsNone(state.error)
        self.assertEqual(state.persistence_error, "历史保存失败")
        self.assertEqual(state.result_path, "result.json")
        self.assertEqual(self.manager.get_result(state.job_id)["seed"], 42)
        self.assertEqual(self.counts(), (0, 0))
        self.assertNotIn("private database failure", str(state.to_dict()))

    def test_simulation_failure_exposes_only_safe_message_and_logs_traceback(self):
        state, job_dir = self.prepare_job(parameters=replace(self.parameters,
                                                             initial_pity=80))
        process = self.launch_worker(job_dir)
        failed = self.wait_for(state.job_id)
        process.wait(timeout=3)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "模拟任务失败")
        self.assertNotIn("ValueError", str(failed.to_dict()))
        self.assertIsNone(self.manager.get_result(state.job_id))
        self.assertEqual(self.counts(), (0, 0))
        self.assertIn("Traceback", (job_dir / "worker.log").read_text())

    def test_queued_cancellation_removes_partial_result_and_never_saves(self):
        state, job_dir = self.prepare_job()
        write_json(job_dir / "result.json", {"partial": True})
        self.manager.cancel(state.job_id)
        process = self.launch_worker(job_dir)
        cancelled = self.wait_for(state.job_id)
        process.wait(timeout=3)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertFalse((job_dir / "result.json").exists())
        self.assertEqual(self.counts(), (0, 0))

    def test_non_trace_result_does_not_expose_records(self):
        state = self.wait_for(self.manager.start(replace(self.parameters, trace=False)).job_id)
        self.assertEqual(state.status, "completed")
        self.assertNotIn("records", self.manager.get_result(state.job_id))
        self.assertEqual(self.counts(), (1, 0))

    def test_non_trace_worker_explicitly_disables_engine_record_collection(self):
        def require_record_opt_out(*args, **kwargs):
            self.assertIs(kwargs.get("collect_records"), False)
            return simulate(*args, **kwargs)

        with patch("dashboard.worker.simulate", side_effect=require_record_opt_out):
            state = self.manager.start(replace(self.parameters, trace=False), synchronous=True)

        self.assertEqual(state.status, "completed")
        self.assertNotIn("records", self.manager.get_result(state.job_id))

    def test_unknown_and_traversal_ids_cannot_access_job_files(self):
        for job_id in (str(uuid4()), "../outside", "/tmp", "", None):
            with self.subTest(job_id=job_id):
                self.assertIsNone(self.manager.get(job_id))
                self.assertIsNone(self.manager.cancel(job_id))
                self.assertIsNone(self.manager.get_result(job_id))

    def test_cancel_persists_request_even_when_history_read_is_unavailable(self):
        state, job_dir = self.prepare_job("running")
        (job_dir / "result.json").touch()
        with patch.object(HistoryRepository, "get_run", side_effect=sqlite3.DatabaseError):
            requested = self.manager.cancel(state.job_id)
        self.assertTrue(requested.cancel_requested)
        self.assertTrue(self.manager.get(state.job_id).cancel_requested)
        self.assertTrue((job_dir / "cancel.request").exists())
        self.assertTrue((job_dir / "result.json").exists())
        self.assertEqual(requested.status, "running")

    def test_main_progress_is_throttled_but_final_update_is_immediate(self):
        clock = [100.0]
        updates = []

        def observed_write(path, value):
            write_json(path, value)
            if value.get("phase") == "simulating" and value.get("completed_units", 0):
                updates.append(value["completed_units"])

        def controlled_simulation(*args, **kwargs):
            progress = kwargs["progress_callback"]

            def advance(completed, total):
                clock[0] = 100.0 + [0, 0.1, 0.4, 0.6, 0.7][completed]
                progress(completed, total)

            kwargs["progress_callback"] = advance
            kwargs["progress_interval"] = 1
            return simulate(*args, **kwargs)

        with (patch("dashboard.worker.time.monotonic", side_effect=lambda: clock[0]),
              patch("dashboard.worker.simulate", side_effect=controlled_simulation),
              patch("dashboard.worker.write_json", side_effect=observed_write)):
            state = self.manager.start(replace(self.parameters, draws=4), synchronous=True)
        self.assertEqual(state.status, "completed")
        self.assertEqual(updates, [3, 4])

    def test_cancel_waiting_for_commit_lock_cannot_remove_committed_outputs(self):
        from dashboard.worker import run
        state, job_dir = self.prepare_job()
        committed, cancelling, release = Event(), Event(), Event()

        def pause_publication(path, value):
            if value.get("status") == "completed":
                committed.set()
                self.assertTrue(release.wait(5))
            write_json(path, value)

        def late_cancel():
            cancelling.set()
            return self.manager.cancel(state.job_id)

        with patch("dashboard.worker.write_json", side_effect=pause_publication):
            with ThreadPoolExecutor(max_workers=2) as pool:
                worker = pool.submit(run, job_dir, self.database)
                try:
                    self.assertTrue(committed.wait(5))
                    cancel = pool.submit(late_cancel)
                    self.assertTrue(cancelling.wait(5))
                    self.assertEqual(self.counts(), (1, 12))
                    self.assertFalse((job_dir / "cancel.request").exists())
                finally:
                    release.set()
                worker.result(timeout=5)
                self.assertEqual(cancel.result(timeout=5).status, "completed")
        self.assertIsNotNone(self.manager.get_result(state.job_id))
        self.assertEqual(self.counts(), (1, 12))

    def test_worker_keeps_active_files_when_save_and_commit_probe_fail(self):
        with (patch.object(HistoryRepository, "save_run", side_effect=sqlite3.DatabaseError),
              patch.object(HistoryRepository, "get_run", side_effect=sqlite3.DatabaseError)):
            state = self.manager.start(self.parameters, synchronous=True)
        self.assertEqual(state.status, "running")
        self.assertTrue((self.root / state.job_id / "result.json").exists())
        self.assertTrue((self.root / state.job_id / "trace.sqlite3").exists())
        with self.assertRaises(JobAlreadyRunning):
            self.manager.start(self.parameters, synchronous=True)

    def test_committed_history_survives_terminal_write_failure_and_late_cancel(self):
        failures = []

        def fail_first_terminal(path, value):
            if value.get("status") == "completed" and not failures:
                failures.append(True)
                raise OSError("state publication failed")
            write_json(path, value)

        with patch("dashboard.worker.write_json", side_effect=fail_first_terminal):
            state = self.manager.start(self.parameters, synchronous=True)
        self.assertTrue(failures)
        self.assertEqual((state.status, state.history_saved), ("completed", True))
        late = self.manager.cancel(state.job_id)
        self.assertEqual(late.status, "completed")
        self.assertEqual(self.counts(), (1, 12))
        self.assertIsNotNone(self.manager.get_result(state.job_id))
        self.assertFalse((self.root / state.job_id / "cancel.request").exists())

    def test_cancel_cleanup_permission_failure_is_retryable_and_scoped(self):
        from dashboard.worker import run
        state, job_dir = self.prepare_job()
        self.manager.cancel(state.job_id)
        for name in ("result.json", "trace.sqlite3", "trace.sqlite3-wal", "trace.sqlite3-shm",
                     "trace.sqlite3-journal", "worker.log", "unowned.tmp"):
            (job_dir / name).touch()
        other, other_dir = self.prepare_job("completed")
        untouched = [job_dir / "worker.log", job_dir / "unowned.tmp",
                     job_dir / "parameters.json", other_dir / "state.json",
                     self.database.parent / "config.json", self.database.parent / "history.sqlite3.backup"]
        for path in untouched[-2:]:
            path.touch()
        original_unlink = Path.unlink

        def deny_trace(path, *args, **kwargs):
            if path == job_dir / "trace.sqlite3":
                raise PermissionError("private error detail")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", new=deny_trace):
            run(job_dir, self.database)
        stopped = self.manager.get(state.job_id)
        self.assertEqual(stopped.status, "cancelled")
        self.assertIsNotNone(stopped.cleanup_error)
        self.assertNotIn("private error detail", stopped.cleanup_error)
        self.assertTrue((job_dir / "cancel.request").exists())
        self.assertTrue(all(path.exists() for path in untouched))
        self.manager.reconcile_after_restart()
        self.manager.reconcile_after_restart()
        stopped = self.manager.get(state.job_id)
        self.assertEqual(stopped.status, "cancelled")
        self.assertIsNone(stopped.cleanup_error)
        self.assertFalse((job_dir / "cancel.request").exists())
        self.assertFalse((job_dir / "trace.sqlite3").exists())
        self.assertTrue(all(path.exists() for path in untouched))

    def test_reaper_honors_cancel_marker_and_is_idempotent(self):
        class ExitedProcess:
            def wait(self):
                return 1

        state, job_dir = self.prepare_job("running")
        self.manager.cancel(state.job_id)
        (job_dir / "result.json").touch()
        self.manager._reap(ExitedProcess(), state.job_id)
        self.manager._reap(ExitedProcess(), state.job_id)
        self.assertEqual(self.manager.get(state.job_id).status, "cancelled")
        self.assertFalse((job_dir / "result.json").exists())
        self.assertFalse((job_dir / "cancel.request").exists())

    def test_terminal_cleanup_marker_is_retried_only_after_worker_exit(self):
        for via_reaper in (False, True):
            with self.subTest(via_reaper=via_reaper):
                state, job_dir = self.prepare_job("cancelled", 123456)
                (job_dir / "cancel.request").touch()
                (job_dir / "trace.sqlite3-wal").touch()
                with patch.object(self.manager, "_stop_worker", return_value=False):
                    self.manager.reconcile_after_restart()
                self.assertTrue((job_dir / "trace.sqlite3-wal").exists())

                class ExitedProcess:
                    def wait(self):
                        return 1

                if via_reaper:
                    self.manager._reap(ExitedProcess(), state.job_id)
                else:
                    with patch.object(self.manager, "_stop_worker", return_value=True):
                        self.manager.reconcile_after_restart()
                self.assertEqual(self.manager.get(state.job_id).status, "cancelled")
                self.assertFalse((job_dir / "trace.sqlite3-wal").exists())
                self.assertFalse((job_dir / "cancel.request").exists())

    def test_invalid_parameters_cleanup_removes_trace_companions(self):
        from dashboard.worker import run
        state, job_dir = self.prepare_job()
        parameters = read_json(job_dir / "parameters.json")
        parameters.pop("job_format_version")
        write_json(job_dir / "parameters.json", parameters)
        (job_dir / "trace.sqlite3-wal").touch()
        with self.assertLogs("dashboard.worker", level="ERROR"):
            run(job_dir, self.database)
        self.assertEqual(self.manager.get(state.job_id).status, "failed")
        self.assertFalse((job_dir / "trace.sqlite3-wal").exists())

    def test_get_result_rejects_an_external_result_path(self):
        state, job_dir = self.prepare_job("completed")
        outside = self.root.parent / "private.json"
        write_json(outside, {"secret": "not a simulation"})
        write_json(job_dir / "state.json", replace(state, result_path=str(outside)).to_dict())
        self.assertIsNone(self.manager.get_result(state.job_id))


if __name__ == "__main__":
    unittest.main()
