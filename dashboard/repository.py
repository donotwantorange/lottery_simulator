"""Transactional v6 history persistence and read-only Trace access."""

from contextlib import closing, nullcontext
import json
from pathlib import Path
import sqlite3
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction

from dashboard.models import SimulationEvent, SimulationRun, User
from dashboard.trace_store import TraceReader, iter_validated_events, validate_event_row
from lottery_simulator.control import check_cancelled
from lottery_simulator.events import event_counts
from lottery_simulator.formats import DATABASE_SCHEMA_VERSION, EVENT_FORMAT_VERSION, RESULT_FORMAT_VERSION, RULE_VERSION, SAMPLING_VERSION, require_version
from lottery_simulator.rules.definitions import PoolDefinition, RuleDefinition, ExperimentParameters
from lottery_simulator.rules.runtime import compile_pool, normalize_parameters, initial_context


IMPORT_BATCH_SIZE = 1000


def _trace_connection(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("BEGIN")
    return db


def _validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("结果必须是对象")
    require_version(payload.get("result_format_version"), RESULT_FORMAT_VERSION, "结果")
    require_version(payload.get("event_format_version"), EVENT_FORMAT_VERSION, "事件")
    require_version(payload.get("sampling_version"), SAMPLING_VERSION, "抽样")
    if payload.get("rule_version") != RULE_VERSION:
        raise ValueError("规则版本不受支持")
    if "events" in payload or "records" in payload or not isinstance(payload.get("simulation"), dict) or not isinstance(payload.get("theoretical"), dict):
        raise ValueError("结果摘要格式无效")
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("结果包含无效或非有限数据") from None
    rule = RuleDefinition.from_dict(payload.get("rule_snapshot"))
    pool = PoolDefinition.from_dict(payload.get("pool_snapshot"))
    compiled = compile_pool(rule, pool)
    parameters = normalize_parameters(compiled, ExperimentParameters.from_dict(payload.get("parameters")))
    counts = event_counts(rule, parameters)
    if payload.get("counts") != {name: getattr(counts, name) for name in counts.__dataclass_fields__}:
        raise ValueError("事件计数与规则快照不一致")
    if (type(payload.get("trace_enabled")) is not bool or
            payload["trace_enabled"] is not parameters.trace or
            type(payload.get("event_count")) is not int or payload["event_count"] != counts.trace_events or
            type(payload.get("seed")) is not int or payload["parameters"].get("seed") != payload["seed"]):
        raise ValueError("Trace标记、抽样数量或种子无效")
    if payload.get("targets") != dict(compiled.targets):
        raise ValueError("机制目标与编译快照不一致")
    from dashboard.limits import SimulationLimits
    policy = SimulationLimits.from_dict(payload.get("limit_policy"))
    if policy.validate(compiled, parameters) != counts:
        raise ValueError("接受时限额与事件数量不一致")
    try:
        accepted = datetime.fromisoformat(payload["accepted_at"])
        if accepted.tzinfo is None:
            raise ValueError
        UUID(payload["owner_id"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("接受时间或所属账号无效") from None
    pool_source, rule_source = payload.get("pool_source"), payload.get("rule_source")
    for source, keys in ((pool_source, {"id", "name", "revision", "original_author"}),
                         (rule_source, {"id", "name", "revision", "author"})):
        if not isinstance(source, dict) or set(source) != keys or type(source["revision"]) is not int or source["revision"] < 1:
            raise ValueError("配置来源快照无效")
        if str(UUID(source["id"])) != source["id"]:
            raise ValueError("配置来源ID必须是标准UUID")
    if pool_source["id"] != pool.id or pool_source["name"] != pool.name:
        raise ValueError("池来源与池快照不一致")
    if rule_source["id"] != rule.id or rule_source["name"] != rule.name:
        raise ValueError("规则来源与规则快照不一致")
    if (pool_source["original_author"] != pool.original_author or
            rule_source["author"] != rule.original_author):
        raise ValueError("配置来源作者与快照不一致")
    if payload.get("initial_context") != initial_context(compiled).to_dict():
        raise ValueError("初始上下文无效")
    return rule, pool, compiled, parameters, counts


class HistoryRepository:
    """Internal persistence adapter; user-facing access is authorized in services.runs."""

    def __init__(self, path=None):
        self.path = Path(path or settings.DATABASES["default"]["NAME"]).resolve()
        if self.path != Path(settings.DATABASES["default"]["NAME"]).resolve():
            raise ValueError("历史路径必须与Django数据库设置一致")

    def initialize(self):
        if not self.path.is_file():
            raise ValueError("历史数据库尚未建立，请先运行migrate")
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA user_version")
            require_version(cursor.fetchone()[0], DATABASE_SCHEMA_VERSION, "数据库")

    def save_run(self, run_id, payload, *, trace_path=None, cancel_check=None,
                 progress_callback=None, commit_guard=None, authorize=None, before_commit=None):
        if type(run_id) is not str or str(UUID(run_id)) != run_id:
            raise ValueError("运行ID必须是标准UUID")
        self.initialize()
        rule, pool, compiled, parameters, counts = _validate_payload(payload)
        if payload["trace_enabled"] != (trace_path is not None):
            raise ValueError("Trace结果必须提供完整事件明细")
        owner_id = UUID(payload["owner_id"])
        pool_source, rule_source = payload["pool_source"], payload["rule_source"]
        values = dict(owner_id=owner_id, pool_id_snapshot=UUID(pool_source["id"]),
            pool_revision_snapshot=pool_source["revision"], pool_name_snapshot=pool_source["name"],
            pool_original_author_snapshot=pool_source["original_author"] or "",
            rule_id_snapshot=UUID(rule_source["id"]), rule_revision_snapshot=rule_source["revision"],
            rule_name_snapshot=rule_source["name"], rule_original_author_snapshot=rule_source["author"] or "",
            rule_version=payload["rule_version"], main_draws=parameters.draws, trials=parameters.trials,
            seed=str(payload["seed"]), trace_enabled=payload["trace_enabled"], event_count=payload["event_count"],
            pool_config_json=payload["pool_snapshot"], rule_config_json=payload["rule_snapshot"],
            parameters_json=payload["parameters"], initial_context_json=payload["initial_context"],
            result_json=payload, schema_version=DATABASE_SCHEMA_VERSION)
        trace = _trace_connection(trace_path) if trace_path is not None else None
        try:
            if trace is not None:
                meta = trace.execute("SELECT * FROM metadata WHERE id=1").fetchone()
                from lottery_simulator.formats import TRACE_STORE_FORMAT_VERSION
                expected = {"format_version": TRACE_STORE_FORMAT_VERSION, "complete": 1, "event_count": counts.trace_events,
                    "trials": parameters.trials, "main_draws": parameters.draws,
                    "initial_main_draws": parameters.initial_main_draws,
                    "bonus_draws": counts.bonus_draws // parameters.trials}
                if meta is None or any(meta[key] != value for key, value in expected.items()):
                    raise ValueError("Trace元数据与冻结实验不一致")
            guard = commit_guard() if commit_guard else nullcontext()
            with guard:
                with transaction.atomic():
                    if authorize:
                        authorize()
                    owner = User.objects.filter(pk=owner_id, deleting=False).first()
                    if owner is None:
                        raise ValueError("所属账号已删除或正在删除，拒绝保存")
                    existing = SimulationRun.objects.filter(pk=run_id).first()
                    if existing is not None:
                        if any(getattr(existing, key) != value for key, value in values.items()) or existing.events.count() != counts.trace_events:
                            raise ValueError("运行ID已有不同快照")
                        check_cancelled(cancel_check)
                        if before_commit:
                            before_commit()
                        check_cancelled(cancel_check)
                        return run_id
                    run = SimulationRun.objects.create(id=run_id, **values)
                    imported = 0
                    if trace is not None:
                        if progress_callback:
                            progress_callback(0, counts.trace_events)
                        rows = trace.execute("SELECT * FROM events ORDER BY trial_index,event_index")
                        def stored_events():
                            for row in rows:
                                yield validate_event_row(row)
                        iterator = iter_validated_events(compiled, parameters, counts,
                            stored_events(), batch_size=IMPORT_BATCH_SIZE,
                            cancel_check=cancel_check)
                        batch = []
                        for event in iterator:
                            trial = event["trial_index"]
                            event_index = event["event_index"]
                            if event["event_type"] == "draw":
                                outcome = event["draw_result"]["outcome"]
                                rarity, character = outcome["rarity_id"], outcome["character_id"]
                            else:
                                rarity, character = event["grant"]["rarity_id"], event["grant"]["character_id"]
                            batch.append(SimulationEvent(run_id=run.pk, trial_index=trial,
                                event_index=event_index, event_type=event["event_type"],
                                main_draws_completed=event["main_draws_completed"],
                                mechanism_id=event["mechanism_id"], draw_index=event["draw_index"],
                                source=event["source"], source_index=event["source_index"],
                                rarity_id=rarity, character_id=character, event_json=event))
                            imported += 1
                            if len(batch) == IMPORT_BATCH_SIZE:
                                SimulationEvent.objects.bulk_create(batch)
                                batch.clear()
                                if progress_callback and imported < counts.trace_events:
                                    progress_callback(imported, counts.trace_events)
                        if batch:
                            SimulationEvent.objects.bulk_create(batch)
                        if imported != counts.trace_events:
                            raise ValueError("Trace事件数量不一致")
                        if progress_callback:
                            progress_callback(imported, counts.trace_events)
                    check_cancelled(cancel_check)
                    if before_commit:
                        before_commit()
                    check_cancelled(cancel_check)
            return run_id
        finally:
            if trace is not None:
                trace.close()

    @staticmethod
    def summary(run):
        result = dict(run.result_json)
        _validate_payload(result)
        require_version(run.schema_version, DATABASE_SCHEMA_VERSION, "数据库记录")
        source, rule = result["pool_source"], result["rule_source"]
        stored = {"owner_id": str(run.owner_id), "pool_id_snapshot": str(run.pool_id_snapshot),
            "pool_revision_snapshot": run.pool_revision_snapshot, "pool_name_snapshot": run.pool_name_snapshot,
            "pool_original_author_snapshot": run.pool_original_author_snapshot,
            "rule_id_snapshot": str(run.rule_id_snapshot), "rule_revision_snapshot": run.rule_revision_snapshot,
            "rule_name_snapshot": run.rule_name_snapshot, "rule_original_author_snapshot": run.rule_original_author_snapshot,
            "main_draws": run.main_draws, "trials": run.trials, "seed": str(run.seed),
            "trace_enabled": run.trace_enabled, "event_count": run.event_count}
        expected = {"owner_id": result["owner_id"], "pool_id_snapshot": source["id"],
            "pool_revision_snapshot": source["revision"], "pool_name_snapshot": source["name"],
            "pool_original_author_snapshot": source["original_author"] or "",
            "rule_id_snapshot": rule["id"], "rule_revision_snapshot": rule["revision"],
            "rule_name_snapshot": rule["name"], "rule_original_author_snapshot": rule["author"] or "",
            "main_draws": result["parameters"]["draws"], "trials": result["parameters"]["trials"],
            "seed": str(result["seed"]), "trace_enabled": result["trace_enabled"],
            "event_count": result["event_count"]}
        if stored != expected:
            raise ValueError("历史列与结果快照不一致")
        result.update(id=str(run.pk), owner_id=str(run.owner_id), created_at=run.created_at.isoformat(),
            pool_id_snapshot=str(run.pool_id_snapshot), pool_revision_snapshot=run.pool_revision_snapshot,
            pool_name_snapshot=run.pool_name_snapshot, pool_original_author_snapshot=run.pool_original_author_snapshot,
            rule_id_snapshot=str(run.rule_id_snapshot), rule_revision_snapshot=run.rule_revision_snapshot,
            rule_name_snapshot=run.rule_name_snapshot, rule_original_author_snapshot=run.rule_original_author_snapshot)
        return result

    def get_run(self, run_id):
        self.initialize()
        try:
            run = SimulationRun.objects.filter(pk=run_id).first()
        except (ValueError, TypeError):
            return None
        return self.summary(run) if run else None

    def get_trace_reader(self, run_id):
        self.initialize()
        return TraceReader.for_history(self.path, str(run_id))

    def list_runs(self, filters=None, limit=50, offset=0):
        self.initialize()
        filters = filters or {}
        if set(filters) - {"owner_id", "rule_name", "trace_enabled"}:
            raise ValueError("不支持的历史筛选")
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ValueError("历史分页参数无效")
        query = SimulationRun.objects.filter(**{("rule_name_snapshot" if key == "rule_name" else key): value
            for key, value in filters.items()}).order_by("-created_at", "-id")
        return [self.summary(run) for run in query[offset:offset+limit]]

    def count_runs(self, filters=None):
        self.initialize()
        filters = filters or {}
        if set(filters) - {"owner_id", "rule_name", "trace_enabled"}:
            raise ValueError("不支持的历史筛选")
        return SimulationRun.objects.filter(**{("rule_name_snapshot" if key == "rule_name" else key): value
            for key, value in filters.items()}).count()

    def delete_run(self, run_id):
        self.initialize()
        with transaction.atomic():
            SimulationRun.objects.filter(pk=run_id).delete()

    def backup_to(self, path):
        self.initialize()
        connection.ensure_connection()
        with closing(sqlite3.connect(path)) as destination:
            connection.connection.backup(destination)
