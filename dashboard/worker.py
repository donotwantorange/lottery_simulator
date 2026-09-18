from dataclasses import replace
import logging
import os
from pathlib import Path
import sys
import time

from dashboard.jobs import ACTIVE_STATUSES, JobManager, timestamp, validate_parameters_for_active_rule
from dashboard.models import RunParameters, read_json, result_payload, write_json
from dashboard.repository import HistoryRepository
from lottery_simulator.cli import RULES
from lottery_simulator.engine import SimulationCancelled, simulate
from lottery_simulator.rules.pool_config import PoolConfig


def run(job_dir: Path, database_path: Path):
    manager = JobManager(job_dir.parent, database_path)
    state_path = job_dir / "state.json"
    result_path = job_dir / "result.json"
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
            result_path.unlink(missing_ok=True)
            write_json(state_path, replace(
                state, status="failed", error="模拟任务失败", result_path=None,
                updated_at=timestamp(),
            ).to_dict())
            return
        state = replace(state, status="running", pid=os.getpid(), started_at=timestamp(),
                        updated_at=timestamp())
        write_json(state_path, state.to_dict())
    started = time.monotonic()

    def progress(completed, total):
        with manager._locked():
            current = manager.get(state.job_id)
            if current is None or current.status not in ACTIVE_STATUSES:
                raise SimulationCancelled()
            write_json(state_path, replace(
                current, completed_units=completed, total_units=total, updated_at=timestamp(),
                duration_seconds=time.monotonic() - started,
            ).to_dict())

    status, error = "completed", None
    try:
        if parameters.pool_config is None:
            raise ValueError("worker requires a serialized pool configuration")
        parameters = validate_parameters_for_active_rule(parameters)
        rule = RULES[parameters.rule_name](
            config=PoolConfig.from_dict(parameters.pool_config)
        )
        result = simulate(
            rule, parameters.draws, parameters.trials, parameters.seed, parameters.initial_pity,
            progress_callback=progress, cancel_check=cancel_path.exists,
            collect_records=parameters.trace,
            initial_five_star_pity=parameters.initial_five_star_pity,
        )
        payload = result_payload(result, rule, time.monotonic() - started)
        if not parameters.trace:
            payload.pop("records", None)
    except SimulationCancelled:
        status = "cancelled"
    except Exception:
        logging.getLogger(__name__).exception("Simulation failed for job %s", state.job_id)
        status, error = "failed", "模拟任务失败"

    with manager._locked():
        current = manager.get(state.job_id)
        if current is None or current.status not in ACTIVE_STATUSES:
            return
        if status == "completed" and cancel_path.exists():
            status = "cancelled"
        persistence_error = None
        if status == "completed":
            try:
                write_json(result_path, payload)
            except Exception:
                logging.getLogger(__name__).exception("Result write failed for job %s", state.job_id)
                status, error = "failed", "模拟任务失败"
        if status == "completed":
            try:
                repository = HistoryRepository(database_path)
                repository.initialize()
                repository.save_run(payload, trace_enabled=parameters.trace)
            except Exception:
                logging.getLogger(__name__).exception("History save failed for job %s", state.job_id)
                persistence_error = "历史保存失败"
        else:
            result_path.unlink(missing_ok=True)
        write_json(state_path, replace(
            current, status=status, error=error, persistence_error=persistence_error,
            result_path="result.json" if status == "completed" else None,
            updated_at=timestamp(), duration_seconds=time.monotonic() - started,
        ).to_dict())


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m dashboard.worker JOB_DIR DATABASE")
    directory = Path(sys.argv[1]).resolve()
    logging.basicConfig(filename=directory / "worker.log", encoding="utf-8", level=logging.INFO)
    run(directory, Path(sys.argv[2]).resolve())
