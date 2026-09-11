from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import fcntl
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

from dashboard.jobs import JobAlreadyRunning, JobManager
from dashboard.models import JobState, RunParameters, read_json, write_json
from dashboard.repository import HistoryRepository


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

    def counts(self):
        with closing(sqlite3.connect(self.database)) as connection:
            return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                         for table in ("simulation_runs", "draw_records"))

    def prepare_job(self, status="queued", pid=None, parameters=None):
        parameters = parameters or self.parameters
        state = JobState(str(uuid4()), status, parameters, 0,
                         parameters.draws * parameters.trials, pid=pid)
        job_dir = self.root / state.job_id
        write_json(job_dir / "parameters.json", parameters.to_dict())
        write_json(job_dir / "state.json", state.to_dict())
        return state, job_dir

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
        self.assertEqual(len(payload["records"]), 12)
        self.assertEqual(self.counts(), (1, 12))
        job_dir = self.root / state.job_id
        self.assertEqual(read_json(job_dir / "parameters.json"), self.parameters.to_dict())
        self.assertNotIn("records", read_json(job_dir / "state.json"))
        self.assertLess((job_dir / "state.json").stat().st_size, 2000)
        self.assertEqual(list(job_dir.glob("*.tmp")), [])
        self.assertEqual(self.manager.cancel(state.job_id).status, "completed")
        self.assertEqual(self.counts(), (1, 12))

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
        self.assertTrue(all(self.manager.get(state.job_id).status == "failed" for state in states))

    def test_recovery_marks_queued_and_running_failed_without_a_live_pid(self):
        states = [self.prepare_job("running", 2_147_483_647)[0], self.prepare_job()[0]]
        self.manager.reconcile_after_restart()
        for state in states:
            recovered = self.manager.get(state.job_id)
            self.assertEqual(recovered.status, "failed")
            self.assertEqual(recovered.error, "服务重启，未完成任务已停止")
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

    def test_unknown_and_traversal_ids_cannot_access_job_files(self):
        for job_id in (str(uuid4()), "../outside", "/tmp", "", None):
            with self.subTest(job_id=job_id):
                self.assertIsNone(self.manager.get(job_id))
                self.assertIsNone(self.manager.cancel(job_id))
                self.assertIsNone(self.manager.get_result(job_id))

    def test_get_result_rejects_an_external_result_path(self):
        state, job_dir = self.prepare_job("completed")
        outside = self.root.parent / "private.json"
        write_json(outside, {"secret": "not a simulation"})
        write_json(job_dir / "state.json", replace(state, result_path=str(outside)).to_dict())
        self.assertIsNone(self.manager.get_result(state.job_id))


if __name__ == "__main__":
    unittest.main()
