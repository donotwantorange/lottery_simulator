"""v5 history adapter. Main database schema belongs exclusively to migrations."""

from contextlib import closing, nullcontext
import json
from pathlib import Path
import sqlite3
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction

from dashboard.models import SimulationRun, User
from dashboard.trace_store import TraceReader, validate_record
from lottery_simulator.control import check_cancelled
from lottery_simulator.formats import (
    CONFIG_FORMAT_VERSION, DATABASE_SCHEMA_VERSION, RESULT_FORMAT_VERSION,
    SAMPLING_VERSION, TRACE_STORE_FORMAT_VERSION, require_version,
)
from lottery_simulator.rules.pool_config import PoolConfig


_IMPORT_BATCH_SIZE = 1000
_FILTERS = {"rule_name": "rule_name", "trace_enabled": "trace_enabled",
            "created_from": "created_at__gte", "created_to": "created_at__lte",
            "owner_id": "owner_id"}


def _validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("结果必须是对象")
    require_version(payload.get("result_format_version"), RESULT_FORMAT_VERSION, "结果")
    require_version(payload.get("sampling_version"), SAMPLING_VERSION, "抽样")
    if payload.get("rule_version") != "2.0":
        raise ValueError("规则版本不受支持")
    config = payload.get("pool_config")
    if not isinstance(config, dict):
        raise ValueError("池快照无效")
    require_version(config.get("format_version"), CONFIG_FORMAT_VERSION, "配置")
    PoolConfig.from_dict(config)
    if "records" in payload or type(payload.get("trace_enabled")) is not bool:
        raise ValueError("结果摘要格式无效")
    for key, minimum in (("main_draws", 1), ("trials", 1), ("initial_pity", 0),
                         ("initial_five_star_pity", 0), ("record_count", 0), ("bonus_draws", 0)):
        if type(payload.get(key)) is not int or not minimum <= payload[key] <= 2**63 - 1:
            raise ValueError(f"{key}超过存储可表示范围或类型无效")
    if (payload.get("draws") != payload["main_draws"]
            or payload.get("initial_main_draws") != payload["initial_pity"]
            or payload.get("total_draws") != payload["main_draws"] + payload["bonus_draws"]):
        raise ValueError("结果抽数与参数不一致")
    expected = payload["trials"] * payload["total_draws"] if payload["trace_enabled"] else 0
    if payload["record_count"] != expected:
        raise ValueError("Trace条数与结果参数不一致")
    if type(payload.get("seed")) is not int:
        raise ValueError("种子必须是整数")
    UUID(payload["owner_id"])
    source = payload["pool_source"]
    UUID(source["id"])
    if type(source["revision"]) is not int or source["revision"] < 1:
        raise ValueError("池来源版本无效")


def _trace_connection(path):
    database = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    database.row_factory = sqlite3.Row
    return database


class HistoryRepository:
    """Internal trusted adapter; web callers authorize through services.runs."""

    def __init__(self, path=None):
        self.path = Path(path or settings.DATABASES["default"]["NAME"]).resolve()
        configured = Path(settings.DATABASES["default"]["NAME"]).resolve()
        if self.path != configured:
            raise ValueError("历史路径必须与Django数据库设置一致")

    def initialize(self):
        if not self.path.is_file():
            raise ValueError("历史数据库尚未建立，请先运行migrate")
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA user_version")
            require_version(cursor.fetchone()[0], DATABASE_SCHEMA_VERSION, "数据库")

    def save_run(self, run_id, payload, *, trace_path=None, cancel_check=None,
                 progress_callback=None, commit_guard=None, authorize=None):
        if type(run_id) is not str or str(UUID(run_id)) != run_id:
            raise ValueError("运行ID必须是标准UUID")
        self.initialize()
        _validate_payload(payload)
        if payload["trace_enabled"] != (trace_path is not None):
            raise ValueError("Trace结果必须提供完整明细")
        source = payload["pool_source"]
        values = {
            "owner_id": UUID(payload["owner_id"]),
            "pool_id_snapshot": UUID(source["id"]),
            "pool_revision_snapshot": source["revision"],
            "pool_name_snapshot": source["name"],
            "original_author_snapshot": source["original_author"],
            **{key: payload[key] for key in ("rule_name", "rule_version", "main_draws", "trials",
                "initial_pity", "initial_five_star_pity", "trace_enabled", "record_count")},
            "seed": str(payload["seed"]), "pool_config_json": payload["pool_config"],
            "result_json": payload, "schema_version": DATABASE_SCHEMA_VERSION,
        }
        trace = _trace_connection(trace_path) if trace_path is not None else None
        try:
            if trace is not None:
                trace.execute("BEGIN")
                metadata = trace.execute("SELECT * FROM metadata WHERE id=1").fetchone()
                expected = {"format_version": TRACE_STORE_FORMAT_VERSION, "complete": 1,
                    "record_count": payload["record_count"], "trials": payload["trials"],
                    "draws": payload["main_draws"], "initial_main_draws": payload["initial_pity"],
                    "bonus_per_trial": payload["bonus_draws"]}
                if metadata is None or any(metadata[key] != value for key, value in expected.items()):
                    raise ValueError("Trace元数据与结果不一致")
            # Acquire the job lock BEFORE the database write transaction.
            guard = commit_guard() if commit_guard else nullcontext()
            with guard:
                with transaction.atomic():
                    if authorize is not None:
                        authorize()
                    owner = User.objects.filter(pk=values["owner_id"], deleting=False).first()
                    if owner is None:
                        raise ValueError("所属账号已删除或正在删除，拒绝保存")
                    existing = SimulationRun.objects.filter(pk=run_id).first()
                    if existing is not None:
                        if (any(getattr(existing, key) != value for key, value in values.items())
                                or existing.draw_records.count() != payload["record_count"]):
                            raise ValueError("运行ID已有不同快照")
                    else:
                        SimulationRun.objects.create(id=run_id, **values)
                        imported = 0
                        if trace is not None:
                            source_cursor = trace.execute(
                                "SELECT trial_index, draw_index, source, source_index, rarity, "
                                "character_name, record_json FROM records ORDER BY trial_index, draw_index")
                            with connection.cursor() as cursor:
                                while batch := source_cursor.fetchmany(_IMPORT_BATCH_SIZE):
                                    check_cancelled(cancel_check)
                                    records = []
                                    for row in batch:
                                        record = json.loads(row["record_json"])
                                        validate_record(record)
                                        projected = (record["trial_index"], record["draw_index"],
                                            record["source"], record["source_index"],
                                            record["draw_result"]["outcome"]["rarity"],
                                            record["draw_result"]["outcome"]["character_name"])
                                        if tuple(row[:6]) != projected:
                                            raise ValueError("Trace索引与JSON不一致")
                                        records.append((UUID(run_id).hex, *projected, row["record_json"]))
                                    cursor.executemany(
                                        "INSERT INTO draw_records (run_id, trial_index, draw_index, source, "
                                        "source_index, rarity, character_name, record_json) "
                                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", records)
                                    imported += len(records)
                                    if progress_callback:
                                        progress_callback(imported, payload["record_count"])
                        if imported != payload["record_count"]:
                            raise ValueError("导入Trace条数不一致")
                    check_cancelled(cancel_check)
        finally:
            if trace is not None:
                trace.close()
        return run_id

    @staticmethod
    def summary(run):
        result = dict(run.result_json)
        _validate_payload(result)
        require_version(run.schema_version, DATABASE_SCHEMA_VERSION, "数据库记录")
        result.update(id=str(run.pk), owner_id=str(run.owner_id),
                      created_at=run.created_at.isoformat(), seed=int(run.seed),
                      pool_id_snapshot=str(run.pool_id_snapshot),
                      pool_revision_snapshot=run.pool_revision_snapshot,
                      pool_name_snapshot=run.pool_name_snapshot,
                      original_author_snapshot=run.original_author_snapshot)
        return result

    def get_run(self, id):
        self.initialize()
        try:
            run = SimulationRun.objects.filter(pk=id).first()
        except (ValueError, TypeError):
            return None
        return self.summary(run) if run else None

    def get_trace_reader(self, run_id):
        self.initialize()
        return TraceReader.for_history(self.path, str(run_id))

    def _query(self, filters):
        self.initialize()
        if filters.keys() - _FILTERS.keys():
            raise ValueError("不支持的历史筛选")
        return SimulationRun.objects.filter(**{_FILTERS[key]: value for key, value in filters.items()})

    def list_runs(self, filters, limit=50, offset=0):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ValueError("历史分页参数无效")
        return [self.summary(run) for run in self._query(filters).order_by("-created_at", "-id")[offset:offset+limit]]

    def count_runs(self, filters):
        return self._query(filters).count()

    def delete_run(self, id):
        self.initialize()
        with transaction.atomic():
            SimulationRun.objects.filter(pk=id).delete()

    def backup_to(self, path):
        self.initialize()
        connection.ensure_connection()
        with closing(sqlite3.connect(path)) as destination:
            connection.connection.backup(destination)
