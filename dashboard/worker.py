from contextlib import contextmanager
from dataclasses import replace
import logging
import os
from pathlib import Path
import sys
import time

from dashboard.jobs import ACTIVE_STATUSES, JobManager, timestamp, validate_parameters_for_active_rule
from dashboard.limits import TraceLimits
from dashboard.models import RunParameters, read_json, result_payload, write_json
from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceWriter
from lottery_simulator.cli import RULES
from lottery_simulator.engine import SimulationCancelled, simulate
from lottery_simulator.rules.pool_config import PoolConfig
from lottery_simulator.rules.base import expected_bonus_draws


def run(job_dir: Path, database_path: Path):
    manager = JobManager(job_dir.parent, database_path)
    state_path = job_dir / "state.json"
    result_path = job_dir / "result.json"
    trace_path = job_dir / "trace.sqlite3"
    cancel_path = job_dir / "cancel.request"
    with manager._locked():
        state = manager.get(job_dir.name)
        if state is None or state.status != "queued":
            return
        try:
            parameters = RunParameters.from_dict(read_json(job_dir / "parameters.json"))
        except (OSError, TypeError, ValueError):
            logging.getLogger(__name__).exception(
                "Invalid parameters for job %s", state.job_id
            )
            cleanup_error = manager._clean_stopped_files(job_dir, partial_result=True)
            write_json(state_path, replace(
                state, status="failed", error="模拟任务失败", result_path=None,
                phase=None, phase_completed=None, phase_total=None,
                cleanup_error=cleanup_error, updated_at=timestamp(),
            ).to_dict())
            return
        state = replace(state, status="running", phase="simulating", phase_completed=None,
                        phase_total=None, pid=os.getpid(),
                        started_at=timestamp(), updated_at=timestamp())
        write_json(state_path, state.to_dict())
    started = time.monotonic()
    last_phase = None
    last_notification = started

    def publish_phase(phase, completed=None, total=None):
        nonlocal last_phase, last_notification
        now = time.monotonic()
        final = total is not None and completed == total
        if phase == last_phase and not final and now - last_notification < 0.5:
            return
        with manager._locked():
            current = manager.get(state.job_id)
            if current is None or current.status not in ACTIVE_STATUSES:
                raise SimulationCancelled()
            if phase == "simulating" and completed is not None:
                current = replace(current, completed_units=completed, total_units=total)
            write_json(state_path, replace(
                current, phase=phase, phase_completed=completed, phase_total=total,
                updated_at=timestamp(), duration_seconds=now - started,
            ).to_dict())
        last_phase, last_notification = phase, now

    status, error = "completed", None
    writer = None
    try:
        if parameters.pool_config is None:
            raise ValueError("worker requires a serialized pool configuration")
        limits = TraceLimits.from_env()
        parameters = validate_parameters_for_active_rule(parameters, limits=limits)
        rule = RULES[parameters.rule_name](
            config=PoolConfig.from_dict(parameters.pool_config)
        )
        if parameters.trace:
            writer = TraceWriter(trace_path, limits=limits)
        result = simulate(
            rule, parameters.draws, parameters.trials, parameters.seed, parameters.initial_pity,
            progress_callback=lambda completed, total: publish_phase("simulating", completed, total),
            cancel_check=cancel_path.exists,
            collect_records=parameters.trace,
            initial_five_star_pity=parameters.initial_five_star_pity,
            record_sink=writer.append if writer is not None else None,
            phase_callback=publish_phase,
        )
        if writer is not None:
            writer.finish(
                trials=parameters.trials, draws=parameters.draws,
                initial_main_draws=parameters.initial_pity,
                bonus_per_trial=expected_bonus_draws(rule, parameters.initial_pity, parameters.draws),
                cancel_check=cancel_path.exists,
                progress_callback=lambda completed, total: publish_phase("validating", completed, total),
            )
            writer.close()
            writer = None
        payload = result_payload(result, rule, time.monotonic() - started)
        if parameters.seed is None:
            parameters = replace(parameters, seed=result.seed)
            write_json(job_dir / "parameters.json", parameters.to_dict())
    except SimulationCancelled:
        status = "cancelled"
    except Exception:
        logging.getLogger(__name__).exception("Simulation failed for job %s", state.job_id)
        status, error = "failed", "模拟任务失败"

    if writer is not None:
        writer.close()
    with manager._locked():
        current = manager.get(state.job_id)
        if current is None or current.status not in ACTIVE_STATUSES:
            return
        if status == "completed" and cancel_path.exists():
            status = "cancelled"
        if status == "completed":
            try:
                write_json(result_path, payload)
            except Exception:
                logging.getLogger(__name__).exception("Result write failed for job %s", state.job_id)
                status, error = "failed", "模拟任务失败"
        if status != "completed":
            cleanup_error = manager._clean_stopped_files(job_dir, partial_result=True)
            write_json(state_path, replace(
                current, status=status, phase=None, phase_completed=None,
                phase_total=None, error=error,
                result_path=None, cleanup_error=cleanup_error, updated_at=timestamp(),
                duration_seconds=time.monotonic() - started,
            ).to_dict())
            return
        current = replace(current, parameters=parameters.to_dict(),
                          result_path="result.json", updated_at=timestamp(),
                          duration_seconds=time.monotonic() - started)
        write_json(state_path, current.to_dict())

    published = False

    @contextmanager
    def commit_guard():
        nonlocal published
        with manager._locked():
            current_state = manager.get(state.job_id)
            if current_state is None or current_state.status not in ACTIVE_STATUSES:
                raise SimulationCancelled()
            if cancel_path.exists():
                raise SimulationCancelled()
            current_state = replace(
                current_state, phase="committing", phase_completed=None, phase_total=None,
                updated_at=timestamp(), duration_seconds=time.monotonic() - started,
            )
            write_json(state_path, current_state.to_dict())
            yield
            write_json(state_path, replace(
                current_state, status="completed", phase=None,
                phase_completed=None, phase_total=None, history_saved=True,
                run_id=state.job_id, result_path="result.json", cancel_requested=False,
                updated_at=timestamp(),
                duration_seconds=time.monotonic() - started,
            ).to_dict())
            published = True

    try:
        repository = HistoryRepository(database_path)
        repository.initialize()
        publish_phase("saving")
        repository.save_run(
            state.job_id, payload,
            trace_path=trace_path if parameters.trace else None,
            cancel_check=cancel_path.exists, commit_guard=commit_guard,
            progress_callback=lambda completed, total: publish_phase("saving", completed, total),
        )
        if published:
            with manager._locked():
                cleanup_error = manager._clean_stopped_files(job_dir)
                if cleanup_error:
                    write_json(state_path, replace(
                        manager.get(state.job_id), cleanup_error=cleanup_error,
                    ).to_dict())
    except SimulationCancelled:
        with manager._locked():
            current = manager.get(state.job_id)
            if current is not None and current.status in ACTIVE_STATUSES:
                cleanup_error = manager._clean_stopped_files(job_dir, partial_result=True)
                write_json(state_path, replace(
                    current, status="cancelled", phase=None,
                    phase_completed=None, phase_total=None, result_path=None,
                    cleanup_error=cleanup_error, updated_at=timestamp(),
                    duration_seconds=time.monotonic() - started,
                ).to_dict())
    except Exception:
        logging.getLogger(__name__).exception("History save failed for job %s", state.job_id)
        try:
            history_committed = HistoryRepository(database_path).get_run(state.job_id) is not None
        except Exception:
            history_committed = None
        with manager._locked():
            current = manager.get(state.job_id)
            if current is not None and current.status in ACTIVE_STATUSES:
                if history_committed is None:
                    # Neither failure nor success is proven: retain admission and all outputs.
                    write_json(state_path, replace(
                        current, persistence_error="历史提交状态无法确认", updated_at=timestamp(),
                    ).to_dict())
                elif history_committed:
                    cleanup_error = manager._clean_stopped_files(job_dir)
                    write_json(state_path, replace(
                        current, status="completed", phase=None,
                        phase_completed=None, phase_total=None, history_saved=True,
                        run_id=state.job_id, persistence_error=None,
                        result_path="result.json", cancel_requested=False,
                        cleanup_error=cleanup_error, updated_at=timestamp(),
                        duration_seconds=time.monotonic() - started,
                    ).to_dict())
                elif cancel_path.exists():
                    cleanup_error = manager._clean_stopped_files(job_dir, partial_result=True)
                    write_json(state_path, replace(
                        current, status="cancelled", phase=None, phase_completed=None,
                        phase_total=None, result_path=None, cleanup_error=cleanup_error,
                        updated_at=timestamp(), duration_seconds=time.monotonic() - started,
                    ).to_dict())
                else:
                    write_json(state_path, replace(
                        current, status="completed", phase=None,
                        phase_completed=None, phase_total=None, history_saved=False,
                        run_id=None, persistence_error="历史保存失败",
                        result_path="result.json", updated_at=timestamp(),
                        duration_seconds=time.monotonic() - started,
                    ).to_dict())


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m dashboard.worker JOB_DIR DATABASE")
    directory = Path(sys.argv[1]).resolve()
    logging.basicConfig(filename=directory / "worker.log", encoding="utf-8", level=logging.INFO)
    run(directory, Path(sys.argv[2]).resolve())
