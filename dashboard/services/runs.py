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
from dashboard.services.pools import _actor, load_rule_definition, pool_document, visible_pools
from dashboard.services.rules import RuleError, validate_rule_pool_reference
from dashboard.services.initial_conditions import require_initial_context
from lottery_simulator.rules.definitions import ExperimentParameters
from lottery_simulator.config_documents import load_pool_document
from lottery_simulator.rules.runtime import compile_pool, initial_context
from lottery_simulator.events import event_counts
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
        text = value
        try:
            value = int(value)
        except ValueError:
            raise RunError(f"{label}必须是十进制整数") from None
        if str(value) != text:
            raise RunError(f"{label}必须是规范十进制整数")
    elif type(value) is not int or abs(value) > 9007199254740991:
        raise RunError(f"{label}必须是整数，大整数请使用十进制字符串")
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise RunError(f"{label}超过允许范围")
    return value


def submit_job(actor, payload, *, synchronous=False):
    required = {"pool_id", "expected_pool_revision", "expected_rule_revision", "parameters", "initial_context"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise RunError("提交字段无效")
    _actor(actor)
    expected_auth_version = getattr(actor, "auth_version", None)
    manager = get_manager()
    request_payload = deepcopy(payload)

    def prepare():
        # Called only while the global admission lock is held.
        with transaction.atomic():
            fresh, pool, compiled, experiment, context = _prepare_submission(
                actor, request_payload, expected_auth_version=expected_auth_version)
            if experiment.seed is None:
                experiment = ExperimentParameters.from_dict({**experiment.to_dict(), "seed": secrets.randbits(64)})
            parameters = RunParameters(experiment, compiled.rule, compiled.pool, dict(compiled.targets), context)
            source = {"id": str(pool.pk), "revision": pool.revision, "name": pool.name,
                      "original_author": pool.original_author}
            rule_source = {"id": str(pool.rule_id), "revision": pool.rule.revision,
                           "name": pool.rule.name, "author": pool.rule.original_author}
            return parameters, str(fresh.pk), source, rule_source, SimulationLimits.for_actor(fresh)

    try:
        return manager.start(prepare=prepare, synchronous=synchronous)
    except JobAlreadyRunning as error:
        raise RunError(str(error), code="system_busy", status=409) from error
    except (RunError, AccountError):
        raise
    except ValueError as error:
        raise RunError(str(error)) from error


def _prepare_submission(actor, payload, *, expected_auth_version=None):
    """Resolve current resources and validate normalized parameters without side effects."""
    required = {"pool_id", "expected_pool_revision", "expected_rule_revision", "parameters", "initial_context"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise RunError("提交字段无效")
    fresh = _actor(actor, expected_auth_version=expected_auth_version)
    pool_id = _uuid(payload["pool_id"])
    try:
        pool = visible_pools(fresh).select_related("rule", "owner").get(pk=pool_id)
    except Pool.DoesNotExist:
        raise RunError("角色池不存在或不可访问", code="not_found", status=404) from None
    pool_revision, rule_revision = payload["expected_pool_revision"], payload["expected_rule_revision"]
    if type(pool_revision) is not int or pool_revision < 1 or type(rule_revision) is not int or rule_revision < 1:
        raise RunError("revision必须是正整数")
    if pool.revision != pool_revision or pool.rule.revision != rule_revision:
        raise RunError("角色池或规则已变化，请重新加载并确认", code="revision_conflict", status=409)
    raw = payload["parameters"]
    required_params = {"draws", "trials", "seed", "trace", "initial_main_draws",
                       "initial_small_pity", "initial_big_pity"}
    if not isinstance(raw, dict) or set(raw) != required_params:
        raise RunError("实验参数字段无效")
    values = dict(raw)
    for key in ("draws", "trials", "initial_main_draws"):
        values[key] = decimal_integer(values[key], key, minimum=1 if key != "initial_main_draws" else 0)
    values["seed"] = None if raw["seed"] is None else decimal_integer(raw["seed"], "seed", maximum=None)
    if type(raw["trace"]) is not bool:
        raise RunError("trace必须是布尔值")
    if not isinstance(raw["initial_small_pity"], dict):
        raise RunError("小保底初始计数必须是对象")
    values["initial_small_pity"] = {
        key: decimal_integer(value, "小保底初始计数")
        for key, value in raw["initial_small_pity"].items()
    }
    if not isinstance(raw["initial_big_pity"], dict) or set(raw["initial_big_pity"]) != {"target_obtained", "misses"}:
        raise RunError("大保底初始状态字段无效")
    values["initial_big_pity"] = {
        "target_obtained": raw["initial_big_pity"]["target_obtained"],
        "misses": decimal_integer(raw["initial_big_pity"]["misses"], "大保底未命中数"),
    }
    try:
        experiment = ExperimentParameters.from_dict(values)
        rule = load_rule_definition(pool.rule)
        pool_def = load_pool_document(pool_document(pool))
        compiled = compile_pool(rule, pool_def)
        validate_rule_pool_reference(fresh, pool.rule, pool_owner=pool.owner,
                                     pool_kind=pool.kind, pool_visibility=pool.visibility)
        experiment = require_initial_context(compiled, experiment, payload["initial_context"])
        return fresh, pool, compiled, experiment, initial_context(compiled)
    except RuleError as error:
        raise RunError(str(error), code=error.code, status=error.status) from error
    except (TypeError, ValueError) as error:
        if isinstance(error, RunError):
            raise
        raise RunError(str(error)) from error


def preview_submission(actor, payload):
    """Read-only admission preview; never creates a seed, job, or history row."""
    expected_auth_version = getattr(actor, "auth_version", None)
    try:
        fresh, pool, compiled, parameters, context = _prepare_submission(
            actor, payload, expected_auth_version=expected_auth_version)
        _actor(fresh, expected_auth_version=expected_auth_version)
        limits = SimulationLimits.for_actor(fresh)
        total = limits.validate(compiled, parameters)
        per_trial_parameters = ExperimentParameters.from_dict({
            **parameters.to_dict(), "trials": 1,
        })
        per_trial = event_counts(compiled.rule, per_trial_parameters)
        start = parameters.initial_main_draws
        return {
            "parameters": {**parameters.to_dict(), "seed": str(parameters.seed) if parameters.seed is not None else None,
                           "draws": str(parameters.draws), "trials": str(parameters.trials),
                           "initial_main_draws": str(parameters.initial_main_draws),
                           "initial_small_pity": {key: str(value) for key, value in parameters.initial_small_pity.items()},
                           "initial_big_pity": {"target_obtained": parameters.initial_big_pity.target_obtained,
                                                "misses": str(parameters.initial_big_pity.misses)}},
            "current_context": context.to_dict(),
            "counts": {"per_trial": {field: str(getattr(per_trial, field)) for field in per_trial.__dataclass_fields__},
                "total": {field: str(getattr(total, field)) for field in total.__dataclass_fields__}},
            "next_triggers": {
                "first_bonus_main_draw": (str(compiled.rule.bonus.at_main_draw)
                    if compiled.rule.bonus.enabled and compiled.rule.bonus.at_main_draw > start else None),
                "periodic_grant_main_draw": (str((start // compiled.rule.grant.period + 1) * compiled.rule.grant.period)
                    if compiled.rule.grant.enabled else None),
            },
            "pool_source": {"id": str(pool.pk), "name": pool.name, "revision": pool.revision},
            "rule_source": {"id": str(pool.rule_id), "name": pool.rule.name, "revision": pool.rule.revision},
        }
    except RunError:
        raise
    except ValueError as error:
        raise RunError(str(error)) from error


def _authorize_job(actor, state):
    fresh = _actor(actor)
    if state is None or (state.owner_id != str(fresh.pk) and not fresh.is_superuser):
        raise RunError("任务不存在或不可访问", code="not_found", status=404)
    return state


def get_job_for_actor(actor, job_id):
    _actor(actor)
    manager = get_manager()
    return _authorize_job(actor, manager.get(str(_uuid(job_id))))


def cancel_job(actor, job_id):
    _actor(actor)
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
    parameters = state.parameters["parameters"]
    return {"job_id": state.job_id, "accepted_at": state.accepted_at,
            "status": state.status, "phase": state.phase,
            "draws": str(parameters["draws"]), "trials": str(parameters["trials"]),
            "trace": parameters["trace"], "pool_name_snapshot": state.pool_source["name"],
            "rule_name_snapshot": state.rule_source["name"],
            "run_id": state.run_id if state.history_saved else None}


def job_detail(state):
    parameters = dict(state.parameters["parameters"])
    for key in {"draws", "trials", "seed", "initial_main_draws"}:
        parameters[key] = str(parameters[key]) if parameters[key] is not None else None
    parameters["initial_small_pity"] = {key: str(value) for key, value in parameters["initial_small_pity"].items()}
    parameters["initial_big_pity"] = dict(parameters["initial_big_pity"])
    parameters["initial_big_pity"]["misses"] = str(parameters["initial_big_pity"]["misses"])
    return {**job_summary(state), "owner_id": state.owner_id, "parameters": parameters,
            "pool_source": state.pool_source, "rule_source": state.rule_source,
            "initial_context": state.parameters["initial_context"],
            "completed_units": str(state.completed_units),
            "total_units": str(state.total_units), "phase_completed": (
                str(state.phase_completed) if state.phase_completed is not None else None),
            "phase_total": str(state.phase_total) if state.phase_total is not None else None,
            "error": state.error, "persistence_error": state.persistence_error,
            "cleanup_error": state.cleanup_error,
            "history_saved": state.history_saved, "cancel_requested": state.cancel_requested,
            "duration_seconds": state.duration_seconds}


def list_my_jobs(actor, page=1, page_size=50):
    fresh = _actor(actor)
    start = pagination(page, page_size)
    manager = get_manager()
    manager.reconcile_after_restart()
    states = [state for state in manager.states() if state.owner_id == str(fresh.pk)]
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
    mapped = {"rule_name": "rule_name_snapshot", "trace_enabled": "trace_enabled",
              "created_at__gte": "created_at__gte", "created_at__lte": "created_at__lte"}
    query = query.filter(**{mapped[key]: value for key, value in filters.items()}).order_by("-created_at", "-id")
    return {"items": [run_summary(run) for run in query[start:start+page_size]],
            "total": query.count(), "page": page, "page_size": page_size}


def run_summary(run):
    return {"id": str(run.pk), "owner_id": str(run.owner_id), "created_at": run.created_at.isoformat(),
            "rule_name": run.rule_name_snapshot, "pool_name_snapshot": run.pool_name_snapshot,
            "original_author_snapshot": run.pool_original_author_snapshot,
            "pool_id_snapshot": str(run.pool_id_snapshot), "pool_revision_snapshot": run.pool_revision_snapshot,
            "rule_id_snapshot": str(run.rule_id_snapshot), "rule_revision_snapshot": run.rule_revision_snapshot,
            "draws": str(run.main_draws), "trials": str(run.trials), "seed": run.seed,
            "trace": run.trace_enabled, "event_count": str(run.event_count)}


def safe_json(value, *, key=None, path=(), count_map=False):
    if isinstance(value, dict):
        map_counts = count_map or key in {
            "counts", "initial_small_pity", "small_pity", "rarity_counts", "character_counts",
            "category_counts", "pity_triggers", "reward_totals", "distributions",
        }
        return {name: (str(item) if map_counts and type(item) is int else
                       safe_json(item, key=name, path=path + (name,), count_map=map_counts))
                for name, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [safe_json(item, path=path, count_map=count_map) for item in value]
    if (type(value) is int and "rule_snapshot" not in path and "pool_snapshot" not in path
            and key in {
            "seed", "draws", "trials", "initial_main_draws", "misses", "event_count",
            "trial_index", "event_index", "main_draws_completed", "draw_index",
            "source_index", "quantity", "trigger_main_draw", "main_draws", "bonus_draws",
            "total_draws", "grant_triggers", "granted_characters", "trace_events", "draw_count",
            } or (type(value) is int and "rule_snapshot" not in path and "pool_snapshot" not in path
                  and abs(value) > 9007199254740991)):
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
    if not state.parameters["parameters"]["trace"]:
        raise RunError("此任务没有逐事件明细", code="not_found", status=404)
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
    reader = get_trace_reader_for_actor(actor, run_id)
    return {"items": safe_json(reader.query_events(filters, limit=page_size, offset=start)),
            "total": reader.count_events(filters), "page": page, "page_size": page_size}


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
    _actor(actor)
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
                trace_path=job_dir / "trace.sqlite3" if state.parameters["parameters"]["trace"] else None,
                authorize=lambda: _authorize_job(actor, state))
            state = replace(state, history_saved=True, run_id=state.job_id,
                            persistence_error=None, updated_at=timestamp())
            write_json(job_dir / "state.json", state.to_dict())
            manager._clean_stopped_files(job_dir)
        return state
