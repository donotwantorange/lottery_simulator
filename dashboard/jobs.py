from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Thread
from uuid import UUID, uuid4

from dashboard.models import JobState, RunParameters, read_json, write_json
from lottery_simulator.cli import RULES


ACTIVE_STATUSES = {"queued", "running"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class JobAlreadyRunning(RuntimeError):
    pass


def validate_parameters_for_active_rule(parameters: RunParameters) -> RunParameters:
    """Validate dashboard parameters against the selected rule without copying its limits."""
    parameters.validate()
    try:
        max_pity = RULES[parameters.rule_name]().max_pity
    except KeyError:
        raise ValueError("未知规则") from None
    if isinstance(max_pity, bool) or not isinstance(max_pity, int) or max_pity <= 0:
        raise ValueError("当前规则的保底配置无效")
    if parameters.initial_pity >= max_pity:
        raise ValueError(f"初始保底必须在 0 到 {max_pity - 1} 之间")
    return parameters


class JobManager:
    def __init__(self, root: str | Path, database_path: str | Path):
        self.root = Path(root).resolve()
        self.database_path = Path(database_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        with (self.root / "active.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _job_dir(self, job_id):
        try:
            directory = self.root / str(UUID(job_id))
        except (ValueError, TypeError, AttributeError):
            return None
        return directory if directory.resolve().parent == self.root else None

    def _active_states(self):
        for path in self.root.glob("*/state.json"):
            state = self.get(path.parent.name)
            if state is not None and state.status in ACTIVE_STATUSES:
                yield state

    def get_active(self) -> JobState | None:
        return next(self._active_states(), None)

    def start(self, parameters: RunParameters, *, synchronous=False) -> JobState:
        validate_parameters_for_active_rule(parameters)
        with self._locked():
            if any(self._active_states()):
                raise JobAlreadyRunning("已有模拟任务正在运行")
            state = JobState(str(uuid4()), "queued", parameters.to_dict(), 0,
                             parameters.draws * parameters.trials, updated_at=timestamp())
            job_dir = self.root / state.job_id
            write_json(job_dir / "parameters.json", parameters.to_dict())
            write_json(job_dir / "state.json", state.to_dict())
            if not synchronous:
                try:
                    process = subprocess.Popen(
                        [sys.executable, "-m", "dashboard.worker", str(job_dir),
                         str(self.database_path)],
                        cwd=Path(__file__).resolve().parents[1], start_new_session=True,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError:
                    logging.getLogger(__name__).exception("Could not launch job %s", state.job_id)
                    write_json(job_dir / "state.json", replace(
                        state, status="failed", error="模拟任务失败", updated_at=timestamp()
                    ).to_dict())
                    raise RuntimeError("模拟任务启动失败") from None
                state = replace(state, pid=process.pid)
                write_json(job_dir / "state.json", state.to_dict())
                # Reap the child even when a client stops polling its job.
                Thread(target=self._reap, args=(process, state.job_id), daemon=True).start()
                return state
        # The inline worker takes the same lock itself; release admission first.
        from dashboard.worker import run
        run(job_dir, self.database_path)
        return self.get(state.job_id)

    def get(self, job_id) -> JobState | None:
        job_dir = self._job_dir(job_id)
        if job_dir is None:
            return None
        try:
            return JobState(**read_json(job_dir / "state.json")).validate()
        except FileNotFoundError:
            return None

    def get_result(self, job_id) -> dict | None:
        state = self.get(job_id)
        if state is None or state.status != "completed" or state.result_path != "result.json":
            return None
        job_dir = self._job_dir(job_id)
        result_path = job_dir / "result.json"
        if result_path.resolve().parent != job_dir:
            return None
        try:
            return read_json(result_path)
        except FileNotFoundError:
            return None

    def cancel(self, job_id) -> JobState | None:
        with self._locked():
            state = self.get(job_id)
            if state is not None and state.status in ACTIVE_STATUSES:
                (self._job_dir(job_id) / "cancel.request").touch()
            return state

    def _reap(self, process, job_id) -> None:
        process.wait()
        try:
            with self._locked():
                current = self.get(job_id)
                job_dir = self._job_dir(job_id)
                if current is None or job_dir is None or current.status not in ACTIVE_STATUSES:
                    return
                write_json(job_dir / "state.json", replace(
                    current, status="failed", error="模拟任务失败", result_path=None,
                    updated_at=timestamp(),
                ).to_dict())
        except FileNotFoundError:
            # The containing data directory was removed after the child exited.
            return

    def reconcile_after_restart(self):
        with self._locked():
            for state in self._active_states():
                current = self.get(state.job_id)
                job_dir = self._job_dir(state.job_id)
                if current is None or job_dir is None or current.status not in ACTIVE_STATUSES:
                    continue
                (job_dir / "cancel.request").touch()
                if self._is_worker(current.pid, job_dir):
                    try:
                        os.kill(current.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
                write_json(job_dir / "state.json", replace(
                    current, status="failed", error="服务重启，未完成任务已停止",
                    updated_at=timestamp(), result_path=None,
                ).to_dict())

    @staticmethod
    def _is_worker(pid, job_dir):
        if sys.platform != "linux" or type(pid) is not int or pid <= 0:
            return False
        try:
            arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            return (len(arguments) > 3
                    and arguments[1:3] == [b"-m", b"dashboard.worker"]
                    and Path(os.fsdecode(arguments[3])).resolve() == job_dir)
        except OSError:
            return False
