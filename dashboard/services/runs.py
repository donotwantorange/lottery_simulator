"""Authorized admission, jobs, immutable history and Trace access."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import re
import secrets
from uuid import UUID

from django.conf import settings
from django.db import transaction

from dashboard.jobs import JobAlreadyRunning, JobManager, timestamp
from dashboard.job_models import RunParameters, write_json
from dashboard.limits import SimulationLimits
from dashboard.models import Pool, SimulationRun
from dashboard.repository import HistoryRepository
from dashboard.services.accounts import AccountError
from dashboard.services.pools import _actor, visible_pools
from dashboard.trace_store import TraceFilter


class RunError(ValueError):
    def __init__(self, message, *, code="validation_error", status=400):
        super().__init__(message)
        self.code, self.status = code, status


def get_manager():
    return JobManager(settings.JOBS_DIR, settings.DATABASES["default"]["NAME"])


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise RunError("资源不存在或不可访问", code="not_found", status=404) from None


def decimal_integer(value, label, *, minimum=None, maximum=2**63 - 1):
    if isinstance(value, str) and re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
        try:
            value = int(value)
        except ValueError:
            raise RunError(f"{label}必须是十进制整数") from None
    elif type(value) is not int or abs(value) > 9007199254740991:
        raise RunError(f"{label}必须是整数，大整数请使用十进制字符串")
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise RunError(f"{label}超过允许范围")
    return value


def _parameters(raw):
    required = {"draws", "trials", "initial_pity", "initial_five_star_pity", "seed", "trace"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise RunError("实验参数字段无效")
    values = {key: decimal_integer(raw[key], key, minimum=1 if key in {"draws", "trials"} else 0)
              for key in required - {"seed", "trace"}}
    values["seed"] = None if raw["seed"] is None else decimal_integer(raw["seed"], "seed", maximum=None)
    if type(raw["trace"]) is not bool:
        raise RunError("trace必须是布尔值")
    return {**values, "trace": raw["trace"]}


def submit_job(actor, payload, *, synchronous=False):
    if not isinstance(payload, dict) or set(payload) != {"pool_id", "expected_revision", "parameters"}:
        raise RunError("提交必须包含pool_id、expected_revision和parameters")
    _actor(actor)
    manager = get_manager()
    request_payload = deepcopy(payload)

    def prepare():
        # Called only while the global admission lock is held.
        with transaction.atomic():
            fresh = _actor(actor)
            pool_id = _uuid(request_payload["pool_id"])
            try:
                pool = visible_pools(fresh).get(pk=pool_id)
            except Pool.DoesNotExist:
                raise RunError("角色池不存在或不可访问", code="not_found", status=404) from None
            revision = request_payload["expected_revision"]
            if type(revision) is not int or revision < 1:
                raise RunError("expected_revision必须是正整数")
            if pool.revision != revision:
                raise RunError("角色池已变化，请重新加载后确认", code="revision_conflict", status=409)
            values = _parameters(request_payload["parameters"])
            if values["seed"] is None:
                values["seed"] = secrets.randbits(64)
            parameters = RunParameters(rule_name=pool.rule_name, pool_config=deepcopy(pool.config_json), **values)
            source = {"id": str(pool.pk), "revision": pool.revision, "name": pool.name,
                      "original_author": pool.original_author}
            return parameters, str(fresh.pk), source, SimulationLimits.for_actor(fresh)

    try:
        return manager.start(prepare=prepare, synchronous=synchronous)
    except JobAlreadyRunning as error:
        raise RunError(str(error), code="system_busy", status=409) from error
    except (RunError, AccountError):
        raise
    except ValueError as error:
        raise RunError(str(error)) from error


def _authorize_job(actor, state):
    fresh = _actor(actor)
    if state is None or (state.owner_id != str(fresh.pk) and not fresh.is_superuser):
        raise RunError("任务不存在或不可访问", code="not_found", status=404)
    return state


def get_job_for_actor(actor, job_id):
    manager = get_manager()
    return _authorize_job(actor, manager.get(str(_uuid(job_id))))


def cancel_job(actor, job_id):
    return get_manager().cancel(str(_uuid(job_id)), authorize=lambda state: _authorize_job(actor, state))


def job_busy(actor):
    _actor(actor)
    manager = get_manager()
    manager.reconcile_after_restart()
    return {"busy": manager.get_active() is not None}


def pagination(page=1, page_size=50):
    if (type(page) is not int or not 1 <= page <= 2**31 - 1
            or type(page_size) is not int or not 1 <= page_size <= 200):
        raise RunError("分页参数无效")
    return (page - 1) * page_size


def job_summary(state):
    parameters = state.parameters
    return {"job_id": state.job_id, "accepted_at": state.accepted_at,
            "status": state.status, "phase": state.phase,
            "draws": str(parameters["draws"]), "trials": str(parameters["trials"]),
            "trace": parameters["trace"], "pool_name_snapshot": state.pool_source["name"],
            "run_id": state.run_id if state.history_saved else None}


def job_detail(state):
    parameters = {key: value for key, value in state.parameters.items()
                  if key in {"draws", "trials", "initial_pity", "initial_five_star_pity", "seed", "trace"}}
    for key in {"draws", "trials", "seed"}:
        parameters[key] = str(parameters[key]) if parameters[key] is not None else None
    return {**job_summary(state), "owner_id": state.owner_id, "parameters": parameters,
            "pool_source": state.pool_source, "completed_units": str(state.completed_units),
            "total_units": str(state.total_units), "phase_completed": (
                str(state.phase_completed) if state.phase_completed is not None else None),
            "phase_total": str(state.phase_total) if state.phase_total is not None else None,
            "error": state.error, "persistence_error": state.persistence_error,
            "history_saved": state.history_saved, "cancel_requested": state.cancel_requested,
            "duration_seconds": state.duration_seconds}


def list_my_jobs(actor, page=1, page_size=50):
    fresh = _actor(actor)
    start = pagination(page, page_size)
    manager = get_manager()
    manager.reconcile_after_restart()
    states = [state for path in manager.root.glob("*/state.json")
              if (state := manager.get(path.parent.name)) is not None and state.owner_id == str(fresh.pk)]
    states.sort(key=lambda state: (datetime.fromisoformat(state.accepted_at), state.job_id), reverse=True)
    return {"items": [job_summary(state) for state in states[start:start+page_size]],
            "total": len(states), "page": page, "page_size": page_size}


def get_run_for_actor(actor, run_id):
    fresh = _actor(actor)
    query = SimulationRun.objects.filter(pk=_uuid(run_id))
    if not fresh.is_superuser:
        query = query.filter(owner_id=fresh.pk)
    run = query.first()
    if run is None:
        raise RunError("历史不存在或不可访问", code="not_found", status=404)
    return run


def list_runs_for_actor(actor, page=1, page_size=50, *, filters=None):
    fresh = _actor(actor)
    start = pagination(page, page_size)
    query = SimulationRun.objects.all()
    if not fresh.is_superuser:
        query = query.filter(owner_id=fresh.pk)
    filters = filters or {}
    if set(filters) - {"rule_name", "trace_enabled", "created_at__gte", "created_at__lte"}:
        raise RunError("历史筛选字段无效")
    query = query.filter(**filters).order_by("-created_at", "-id")
    return {"items": [run_summary(run) for run in query[start:start+page_size]],
            "total": query.count(), "page": page, "page_size": page_size}


def run_summary(run):
    return {"id": str(run.pk), "owner_id": str(run.owner_id), "created_at": run.created_at.isoformat(),
            "rule_name": run.rule_name, "pool_name_snapshot": run.pool_name_snapshot,
            "original_author_snapshot": run.original_author_snapshot,
            "pool_id_snapshot": str(run.pool_id_snapshot), "pool_revision_snapshot": run.pool_revision_snapshot,
            "draws": str(run.main_draws), "trials": str(run.trials), "seed": run.seed,
            "trace": run.trace_enabled, "record_count": str(run.record_count)}


def safe_json(value, *, key=None):
    if isinstance(value, dict):
        return {name: safe_json(item, key=name) for name, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [safe_json(item) for item in value]
    if type(value) is int and (key == "seed" or abs(value) > 9007199254740991):
        return str(value)
    return value


def get_trace_reader_for_actor(actor, run_id):
    run = get_run_for_actor(actor, run_id)
    if not run.trace_enabled:
        raise RunError("此历史没有逐抽明细", code="not_found", status=404)
    return HistoryRepository().get_trace_reader(str(run.pk))


def get_job_result_for_actor(actor, job_id, *, serialize=True):
    state = get_job_for_actor(actor, job_id)
    result = get_manager().get_result(state.job_id)
    if result is None:
        raise RunError("任务结果尚不可用", code="not_found", status=404)
    return safe_json({**result, "pool_name_snapshot": state.pool_source["name"]}) if serialize else result


def get_job_trace_reader_for_actor(actor, job_id):
    state = get_job_for_actor(actor, job_id)
    if state.history_saved:
        return get_trace_reader_for_actor(actor, state.run_id)
    reader = get_manager().get_trace_reader(state.job_id)
    if reader is None:
        raise RunError("任务逐抽明细尚不可用", code="not_found", status=404)
    return reader


def query_trace_for_actor(actor, run_id, filters, *, page=1, page_size=50):
    start = pagination(page, page_size)
    if page_size not in {50, 100, 200}:
        raise RunError("逐抽分页大小必须是50、100或200")
    records, total = get_trace_reader_for_actor(actor, run_id).query_records(filters, limit=page_size, offset=start)
    return {"items": safe_json(records), "total": total, "page": page, "page_size": page_size}


def delete_run_for_actor(actor, run_id):
    from dashboard.downloads import cleanup_run_exports
    run = get_run_for_actor(actor, run_id)
    try:
        cleanup_run_exports(str(run.pk))
    except (OSError, ValueError) as error:
        raise RunError("历史临时导出清理失败，请稍后重试", code="storage_busy", status=503) from error
    with transaction.atomic():
        get_run_for_actor(actor, run_id).delete()


def resave_job_for_actor(actor, job_id):
    manager = get_manager()
    with manager._locked():
        state = _authorize_job(actor, manager.get(str(_uuid(job_id))))
        if state.status != "completed":
            raise RunError("任务尚未完成")
        payload = manager.get_result(state.job_id)
        if payload is None:
            raise RunError("任务结果不可用", code="not_found", status=404)
        if not state.history_saved:
            job_dir = manager._job_dir(state.job_id)
            HistoryRepository().save_run(state.job_id, payload,
                trace_path=job_dir / "trace.sqlite3" if state.parameters["trace"] else None,
                authorize=lambda: _authorize_job(actor, state))
            state = replace(state, history_saved=True, run_id=state.job_id,
                            persistence_error=None, updated_at=timestamp())
            write_json(job_dir / "state.json", state.to_dict())
            manager._clean_stopped_files(job_dir)
        return state
