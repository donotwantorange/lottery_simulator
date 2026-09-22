from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
import logging
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from threading import Thread
from uuid import UUID, uuid4

from dashboard.models import JobState, RunParameters, read_json, write_json
from dashboard.limits import TraceLimits
from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceFilter, TraceReader
from lottery_simulator.cli import RULES
from lottery_simulator.formats import RESULT_FORMAT_VERSION, require_version
from lottery_simulator.rules.pool_config import PoolConfig, load_pool_config
from lottery_simulator.rules.base import expected_bonus_draws


ACTIVE_STATUSES = {"queued", "running"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class JobAlreadyRunning(RuntimeError):
    pass


def validate_parameters_for_active_rule(parameters: RunParameters, limits=None) -> RunParameters:
    """Validate dashboard parameters against the selected rule without copying its limits."""
    parameters.validate()
    try:
        rule_factory = RULES[parameters.rule_name]
    except KeyError:
        raise ValueError("未知规则") from None
    config = (
        load_pool_config()
        if parameters.pool_config is None
        else PoolConfig.from_dict(parameters.pool_config)
    )
    rule = rule_factory(config=config)
    max_pity = rule.max_pity
    if isinstance(max_pity, bool) or not isinstance(max_pity, int) or max_pity <= 0:
        raise ValueError("当前规则的保底配置无效")
    if parameters.initial_pity >= max_pity:
        raise ValueError(f"初始保底必须在 0 到 {max_pity - 1} 之间")
    five_star = config.five_star
    if five_star.pity_enabled:
        if parameters.initial_five_star_pity >= five_star.hard_pity:
            raise ValueError(
                f"初始五星保底必须在 0 到 {five_star.hard_pity - 1} 之间"
            )
    elif parameters.initial_five_star_pity != 0:
        raise ValueError("关闭五星保底时初始五星保底必须为 0")
    if parameters.trace:
        limits = limits or TraceLimits.from_env()
        bonus = expected_bonus_draws(rule, parameters.initial_pity, parameters.draws)
        if parameters.trials * (parameters.draws + bonus) > limits.max_records:
            raise ValueError("Trace记录数超过上限")
    return replace(parameters, pool_config=config.to_dict())


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
        parameters = validate_parameters_for_active_rule(parameters)
        with self._locked():
            if any(self._active_states()):
                raise JobAlreadyRunning("已有模拟任务正在运行")
            state = JobState(str(uuid4()), "queued", parameters.to_dict(), 0,
                             parameters.draws * parameters.trials, updated_at=timestamp(),
                             phase="simulating")
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
            return JobState.from_dict(read_json(job_dir / "state.json"))
        except FileNotFoundError:
            return None
        except (OSError, TypeError, ValueError):
            logging.getLogger(__name__).warning("Ignoring invalid job state %s", job_id)
            return None

    def get_result(self, job_id) -> dict | None:
        state = self.get(job_id)
        if state is None or state.status != "completed" or state.result_path != "result.json":
            return None
        if state.history_saved:
            try:
                if HistoryRepository(self.database_path).get_run(state.run_id) is None:
                    return None
            except (OSError, sqlite3.Error, ValueError):
                return None
        job_dir = self._job_dir(job_id)
        result_path = job_dir / "result.json"
        if result_path.resolve().parent != job_dir:
            return None
        try:
            result = read_json(result_path)
            require_version(
                result.get("result_format_version"), RESULT_FORMAT_VERSION, "结果格式"
            )
            require_version(result.get("sampling_version"), state.sampling_version, "抽样")
            return result
        except FileNotFoundError:
            return None
        except (OSError, TypeError, ValueError):
            logging.getLogger(__name__).warning("Ignoring invalid job result %s", job_id)
            return None

    def get_trace_reader(self, job_id):
        state = self.get(job_id)
        if state is None or state.status != "completed":
            return None
        if state.history_saved:
            try:
                repository = HistoryRepository(self.database_path)
                if repository.get_run(state.run_id) is None:
                    return None
                return repository.get_trace_reader(state.run_id)
            except (OSError, sqlite3.Error, ValueError):
                return None
        trace_path = self._job_dir(job_id) / "trace.sqlite3"
        try:
            reader = TraceReader.for_trace_store(trace_path)
            reader.query_records(TraceFilter(), limit=50)
            return reader
        except (OSError, sqlite3.Error, ValueError):
            return None

    def cancel(self, job_id) -> JobState | None:
        with self._locked():
            state = self.get(job_id)
            if state is not None and state.status in ACTIVE_STATUSES:
                try:
                    saved = HistoryRepository(self.database_path).get_run(job_id)
                except (OSError, sqlite3.Error, ValueError):
                    saved = None
                if saved is not None:
                    completed = replace(
                        state, status="completed", phase=None, history_saved=True,
                        run_id=job_id, result_path="result.json", updated_at=timestamp(),
                    )
                    write_json(self._job_dir(job_id) / "state.json", completed.to_dict())
                    return completed
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
                committed = self._recover_committed(current, job_dir)
                if committed is None:
                    return
                if committed:
                    self._clean_stopped_files(job_dir)
                    return
                self._clean_stopped_files(job_dir, partial_result=True)
                write_json(job_dir / "state.json", replace(
                    current, status="failed", error="模拟任务失败", result_path=None,
                    updated_at=timestamp(),
                ).to_dict())
        except FileNotFoundError:
            # The containing data directory was removed after the child exited.
            return

    def _recover_committed(self, state, job_dir):
        if not self.database_path.exists():
            return False
        try:
            saved = HistoryRepository(self.database_path).get_run(state.job_id)
        except (OSError, sqlite3.Error, ValueError):
            logging.getLogger(__name__).warning(
                "History commit not confirmed for job %s; retaining active state", state.job_id
            )
            return None
        if saved is None:
            return False
        write_json(job_dir / "state.json", replace(
            state, status="completed", phase=None, history_saved=True,
            run_id=state.job_id, result_path="result.json", error=None,
            persistence_error=None, updated_at=timestamp(),
        ).to_dict())
        return True

    def reconcile_after_restart(self):
        with self._locked():
            for state in self._active_states():
                current = self.get(state.job_id)
                job_dir = self._job_dir(state.job_id)
                if current is None or job_dir is None or current.status not in ACTIVE_STATUSES:
                    continue
                if not self._stop_worker(current.pid, job_dir):
                    logging.getLogger(__name__).warning(
                        "Worker exit not confirmed for job %s; retaining active state", state.job_id
                    )
                    continue
                committed = self._recover_committed(current, job_dir)
                if committed is None:
                    continue
                if committed:
                    self._clean_stopped_files(job_dir)
                    continue
                self._clean_stopped_files(job_dir, partial_result=True)
                write_json(job_dir / "state.json", replace(
                    current, status="failed", error="服务重启，未完成任务已停止",
                    updated_at=timestamp(), result_path=None, phase=None,
                ).to_dict())

    @staticmethod
    def _clean_stopped_files(job_dir, *, partial_result=False):
        names = ["trace.sqlite3" + suffix for suffix in ("", "-journal", "-wal", "-shm")]
        names.append("cancel.request")
        if partial_result:
            names.append("result.json")
        for name in names:
            (job_dir / name).unlink(missing_ok=True)

    def _stop_worker(self, pid, job_dir):
        try:
            if not self._is_worker(pid, job_dir):
                return True
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 3
            while self._is_worker(pid, job_dir):
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.01)
            return True
        except ProcessLookupError:
            return True
        except OSError:
            return False

    @staticmethod
    def _is_worker(pid, job_dir):
        if sys.platform != "linux" or type(pid) is not int or pid <= 0:
            return False
        try:
            arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            return (len(arguments) > 3
                    and arguments[1:3] == [b"-m", b"dashboard.worker"]
                    and Path(os.fsdecode(arguments[3])).resolve() == job_dir)
        except (FileNotFoundError, ProcessLookupError):
            return False
