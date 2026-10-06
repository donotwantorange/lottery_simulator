from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
import errno
import logging
import os
from pathlib import Path
import signal
import stat
import sqlite3
import subprocess
import sys
import time
from threading import Thread
from uuid import UUID, uuid4

from dashboard.job_models import JobState, RunParameters, read_json, write_json
from dashboard.limits import SimulationLimits
from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceFilter, TraceReader
from lottery_simulator.formats import EVENT_FORMAT_VERSION, RESULT_FORMAT_VERSION, require_version
from lottery_simulator.rules.runtime import compile_pool


ACTIVE_STATUSES = {"queued", "running"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class JobAlreadyRunning(RuntimeError):
    pass


class JobStateUnavailable(RuntimeError):
    """State cannot be safely determined; retain admission and owned files."""


class JobManager:
    def __init__(self, root: str | Path, database_path: str | Path):
        self.root = Path(root).resolve()
        self.database_path = Path(database_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

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
        try:
            mode = directory.lstat().st_mode
        except FileNotFoundError:
            return directory
        except OSError as error:
            raise JobStateUnavailable("任务目录不可读") from error
        if not stat.S_ISDIR(mode):
            raise JobStateUnavailable("任务目录不安全")
        return directory

    def states(self):
        """Scan directories, not replaceable state files; fail closed on unknowns."""
        try:
            candidates = list(self.root.iterdir())
        except OSError as error:
            raise JobStateUnavailable("任务目录无法枚举") from error
        states = []
        for path in candidates:
            try:
                canonical = str(UUID(path.name)) == path.name
            except ValueError:
                continue
            if canonical:
                state = self.get(path.name)
                if state is not None:
                    states.append(state)
        return states

    def _active_states(self):
        for state in self.states():
            if state.status in ACTIVE_STATUSES:
                yield state

    def get_active(self) -> JobState | None:
        return next(self._active_states(), None)

    def start(self, *, prepare, synchronous=False) -> JobState:
        """Only service-owned admission may produce the accepted snapshot."""
        with self._locked():
            parameters, owner_id, pool_source, rule_source, policy = prepare()
            parameters.validate()
            if parameters.seed is None:
                raise ValueError("已接受任务必须冻结实际随机种子")
            compiled = compile_pool(parameters.rule_snapshot, parameters.pool_snapshot)
            counts = policy.validate(compiled, parameters.parameters)
            for previous in list(self._active_states()):
                directory = self._job_dir(previous.job_id)
                if not self._is_worker(previous.pid, directory):
                    self._finish_exited(previous, directory, "模拟进程已退出")
            if any(self._active_states()):
                raise JobAlreadyRunning("已有模拟任务正在运行")
            state = JobState(str(uuid4()), "queued", parameters.to_dict(), 0,
                             counts.total_draws + counts.grant_triggers, updated_at=timestamp(),
                             phase="simulating", owner_id=owner_id, accepted_at=timestamp(),
                             pool_source=pool_source, rule_source=rule_source,
                             limit_policy=policy.to_dict())
            state.validate()
            job_dir = self.root / state.job_id
            job_dir.mkdir(mode=0o700)
            write_json(job_dir / "parameters.json", parameters.to_dict())
            write_json(job_dir / "state.json", state.to_dict())
            if not synchronous:
                try:
                    from django.conf import settings
                    environment = os.environ.copy()
                    environment.update({
                        "DJANGO_SETTINGS_MODULE": os.environ.get("DJANGO_SETTINGS_MODULE", "webapp.settings"),
                        "LOTTERY_DATA_DIR": str(settings.DATA_DIR),
                        "LOTTERY_DB_PATH": str(self.database_path),
                        "LOTTERY_JOBS_DIR": str(self.root),
                        "LOTTERY_EXPORTS_DIR": str(settings.EXPORTS_DIR),
                    })
                    process = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve().parents[1] / "manage.py"),
                         "run_job", "--job-dir", str(job_dir)],
                        cwd=Path(__file__).resolve().parents[1], start_new_session=True,
                        env=environment,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError:
                    logging.getLogger(__name__).exception("Could not launch job %s", state.job_id)
                    write_json(job_dir / "state.json", replace(
                        state, status="failed", phase=None,
                        phase_completed=None, phase_total=None,
                        error="模拟任务失败", updated_at=timestamp()
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
        for attempt in range(3):
            try:
                state_path = job_dir / "state.json"
                if not stat.S_ISREG(state_path.lstat().st_mode):
                    raise ValueError("任务状态文件不安全")
                state = JobState.from_dict(read_json(state_path))
                if state.job_id != job_dir.name:
                    raise ValueError("任务状态与目录不一致")
                return state
            except (OSError, TypeError, ValueError) as error:
                if isinstance(error, FileNotFoundError) or (isinstance(error, OSError)
                        and error.errno in {errno.ENOENT, errno.ENODATA}):
                    if attempt < 2:
                        time.sleep(0.01 * (attempt + 1))
                        continue
                    try:
                        job_dir.lstat()
                    except FileNotFoundError:
                        return None
                    except OSError as metadata_error:
                        raise JobStateUnavailable("任务目录不可读") from metadata_error
                logging.getLogger(__name__).warning("Job state unavailable: %s", job_id, exc_info=True)
                raise JobStateUnavailable("任务状态不可读") from error

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
            require_version(result.get("event_format_version"), EVENT_FORMAT_VERSION, "事件")
            parameters = RunParameters.from_dict(state.parameters)
            compiled = compile_pool(parameters.rule_snapshot, parameters.pool_snapshot)
            counts = SimulationLimits.from_dict(state.limit_policy).validate(compiled, parameters.parameters)
            if (result.get("parameters") != parameters.parameters.to_dict()
                    or result.get("rule_snapshot") != parameters.rule_snapshot.to_dict()
                    or result.get("pool_snapshot") != parameters.pool_snapshot.to_dict()
                    or result.get("initial_context") != parameters.initial_context.to_dict()
                    or result.get("targets") != dict(parameters.resolved_targets)
                    or result.get("seed") != parameters.seed
                    or result.get("trace_enabled") is not parameters.trace
                    or result.get("owner_id") != state.owner_id
                    or result.get("accepted_at") != state.accepted_at
                    or result.get("pool_source") != state.pool_source
                    or result.get("rule_source") != state.rule_source
                    or result.get("limit_policy") != state.limit_policy
                    or result.get("counts") != {name: getattr(counts, name)
                                                  for name in counts.__dataclass_fields__}
                    or result.get("event_count") != counts.trace_events):
                raise ValueError("任务结果与接受快照不一致")
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
            reader.count_events(TraceFilter())
            return reader
        except (OSError, sqlite3.Error, ValueError):
            return None

    def cancel(self, job_id, *, authorize=None) -> JobState | None:
        with self._locked():
            state = self.get(job_id)
            if authorize is not None:
                authorize(state)
            if state is not None and state.status in ACTIVE_STATUSES:
                try:
                    saved = self._saved_run(state)
                except (OSError, sqlite3.Error, ValueError):
                    saved = None
                if saved is not None:
                    completed = replace(
                        state, status="completed", phase=None,
                        phase_completed=None, phase_total=None, history_saved=True,
                        run_id=job_id, result_path="result.json", cancel_requested=False,
                        updated_at=timestamp(),
                    )
                    write_json(self._job_dir(job_id) / "state.json", completed.to_dict())
                    return completed
                (self._job_dir(job_id) / "cancel.request").touch()
                state = replace(state, cancel_requested=True, updated_at=timestamp())
                write_json(self._job_dir(job_id) / "state.json", state.to_dict())
            return state

    def _reap(self, process, job_id) -> None:
        process.wait()
        try:
            with self._locked():
                current = self.get(job_id)
                job_dir = self._job_dir(job_id)
                if current is None or job_dir is None:
                    return
                self._finish_exited(current, job_dir, "模拟任务失败")
        except FileNotFoundError:
            # The containing data directory was removed after the child exited.
            return
        except JobStateUnavailable:
            logging.getLogger(__name__).exception("Retaining unavailable job %s after exit", job_id)

    def _saved_run(self, state):
        saved = HistoryRepository(self.database_path).get_run(state.job_id)
        if saved is None:
            return None
        parameters = RunParameters.from_dict(state.parameters)
        expected = dict(owner_id=state.owner_id, accepted_at=state.accepted_at,
                        pool_source=state.pool_source, rule_source=state.rule_source,
                        limit_policy=state.limit_policy, parameters=parameters.parameters.to_dict(),
                        pool_snapshot=parameters.pool_snapshot.to_dict(),
                        rule_snapshot=parameters.rule_snapshot.to_dict(),
                        initial_context=parameters.initial_context.to_dict(),
                        targets=dict(parameters.resolved_targets))
        if any(saved.get(key) != value for key, value in expected.items()):
            raise JobStateUnavailable("历史与任务冻结快照不一致")
        return saved

    def _recover_committed(self, state, job_dir):
        if not self.database_path.exists():
            logging.getLogger(__name__).warning(
                "History database unavailable for job %s; retaining active state", state.job_id
            )
            return None
        try:
            saved = self._saved_run(state)
        except (OSError, sqlite3.Error, ValueError):
            logging.getLogger(__name__).warning(
                "History commit not confirmed for job %s; retaining active state", state.job_id
            )
            return None
        if saved is None:
            return False
        write_json(job_dir / "state.json", replace(
            state, status="completed", phase=None,
            phase_completed=None, phase_total=None, history_saved=True,
            run_id=state.job_id, result_path="result.json", error=None,
            persistence_error=None, cancel_requested=False, updated_at=timestamp(),
        ).to_dict())
        return True

    def _finish_exited(self, current, job_dir, error):
        if (current.status not in ACTIVE_STATUSES and not current.cleanup_error
                and not (job_dir / "cancel.request").exists()):
            return
        if current.status in ACTIVE_STATUSES:
            committed = self._recover_committed(current, job_dir)
            if committed is None:
                return
            if committed:
                current = self.get(current.job_id)
            else:
                cancelled = current.cancel_requested or (job_dir / "cancel.request").exists()
                current = replace(
                    current, status="cancelled" if cancelled else "failed",
                    error=None if cancelled else error, result_path=None,
                    phase=None, phase_completed=None, phase_total=None,
                )
        cleanup_error = self._clean_stopped_files(
            job_dir, partial_result=current.status != "completed",
        )
        write_json(job_dir / "state.json", replace(
            current, cleanup_error=cleanup_error, updated_at=timestamp(),
        ).to_dict())

    def reconcile_after_restart(self):
        with self._locked():
            for current in self.states():
                job_dir = self._job_dir(current.job_id)
                if (current is None or job_dir is None or
                        (current.status not in ACTIVE_STATUSES and not current.cleanup_error
                         and not (job_dir / "cancel.request").exists())):
                    continue
                if self._is_worker(current.pid, job_dir):
                    continue
                self._finish_exited(current, job_dir, "模拟进程已退出")

    @staticmethod
    def _clean_stopped_files(job_dir, *, partial_result=False):
        names = ["trace.sqlite3" + suffix for suffix in ("", "-journal", "-wal", "-shm")]
        if partial_result:
            names.append("result.json")
        cleanup_error = None
        for name in names:
            try:
                (job_dir / name).unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).exception("Could not clean job file %s", job_dir / name)
                cleanup_error = "残次文件清理未完成"
        # Keep the retry marker until every owned output has been removed.
        try:
            if cleanup_error:
                (job_dir / "cancel.request").touch(exist_ok=True)
            else:
                (job_dir / "cancel.request").unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).exception("Could not update cleanup marker for %s", job_dir)
            cleanup_error = "残次文件清理未完成"
        return cleanup_error

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
            return (len(arguments) > 4
                    and Path(os.fsdecode(arguments[1])).resolve() == Path(__file__).resolve().parents[1] / "manage.py"
                    and arguments[2:4] == [b"run_job", b"--job-dir"]
                    and Path(os.fsdecode(arguments[4])).resolve() == job_dir.resolve())
        except (FileNotFoundError, ProcessLookupError):
            return False
