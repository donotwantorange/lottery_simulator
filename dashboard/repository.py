from __future__ import annotations

from contextlib import closing, nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory, mkdtemp
from uuid import UUID

from lottery_simulator.formats import (
    CONFIG_FORMAT_VERSION, DATABASE_SCHEMA_VERSION,
    RESULT_FORMAT_VERSION, SAMPLING_VERSION, TRACE_STORE_FORMAT_VERSION, require_version,
)
from lottery_simulator.engine import SimulationCancelled
from lottery_simulator.rules.pool_config import PoolConfig
from dashboard.trace_store import TraceReader, validate_record


_SCHEMA = f"""
CREATE TABLE simulation_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    main_draws INTEGER NOT NULL,
    trials INTEGER NOT NULL,
    initial_pity INTEGER NOT NULL,
    initial_five_star_pity INTEGER NOT NULL,
    seed TEXT NOT NULL,
    trace_enabled INTEGER NOT NULL CHECK (trace_enabled IN (0, 1)),
    record_count INTEGER NOT NULL CHECK (
        typeof(record_count) = 'integer' AND record_count >= 0),
    pool_config_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = {DATABASE_SCHEMA_VERSION}),
    CHECK ((trace_enabled = 0 AND record_count = 0)
        OR (trace_enabled = 1 AND record_count > 0))
);
CREATE TABLE draw_records (
    run_id TEXT NOT NULL REFERENCES simulation_runs(id) ON DELETE CASCADE,
    trial_index INTEGER NOT NULL CHECK (typeof(trial_index) = 'integer' AND trial_index > 0),
    draw_index INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('main', 'bonus')),
    source_index INTEGER NOT NULL CHECK (typeof(source_index) = 'integer' AND source_index > 0),
    rarity INTEGER NOT NULL CHECK (typeof(rarity) = 'integer' AND rarity IN (4, 5, 6)),
    character_name TEXT,
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    PRIMARY KEY (run_id, trial_index, draw_index),
    CHECK (json_type(record_json, '$') IS 'object'),
    CHECK (trial_index IS json_extract(record_json, '$.trial_index')),
    CHECK (draw_index IS json_extract(record_json, '$.draw_index')),
    CHECK (source IS json_extract(record_json, '$.source')),
    CHECK (source_index IS json_extract(record_json, '$.source_index')),
    CHECK (rarity IS json_extract(record_json, '$.draw_result.outcome.rarity')),
    CHECK (character_name IS json_extract(record_json, '$.draw_result.outcome.character_name'))
);
CREATE INDEX draw_records_run_source_position_rarity
ON draw_records(run_id, source, source_index, rarity);
PRAGMA user_version = {DATABASE_SCHEMA_VERSION};
"""

_FILTERS = {
    "rule_name": "rule_name = ?",
    "trace_enabled": "trace_enabled = ?",
    "created_from": "created_at >= ?",
    "created_to": "created_at <= ?",
}

_COMPONENT_SUFFIXES = ("", "-journal", "-wal", "-shm")
_IMPORT_BATCH_SIZE = 1000
_SNAPSHOT_COLUMNS = (
    "rule_name", "rule_version", "main_draws", "trials", "initial_pity",
    "initial_five_star_pity", "seed", "trace_enabled", "record_count",
    "pool_config_json", "result_json", "schema_version",
)


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _validate_payload(value):
    payload = _object(value, "result")
    require_version(payload.get("result_format_version"), RESULT_FORMAT_VERSION, "结果")
    require_version(payload.get("sampling_version"), SAMPLING_VERSION, "抽样")
    if not isinstance(payload.get("rule_version"), str) or payload["rule_version"] != "2.0":
        raise ValueError("rule_version must be the supported string 2.0")
    config = _object(payload.get("pool_config"), "pool_config")
    require_version(config.get("format_version"), CONFIG_FORMAT_VERSION, "配置")
    PoolConfig.from_dict(config)
    if "records" in payload:
        raise ValueError("result summary must not contain records")
    if type(payload.get("trace_enabled")) is not bool:
        raise ValueError("trace_enabled must be a boolean")
    for key, minimum in (
        ("main_draws", 1), ("trials", 1), ("initial_pity", 0),
        ("initial_five_star_pity", 0), ("record_count", 0), ("bonus_draws", 0),
    ):
        value = payload.get(key)
        if type(value) is not int or value < minimum:
            raise ValueError(f"{key} must be an integer >= {minimum}")
    if payload.get("draws") != payload["main_draws"]:
        raise ValueError("draws and main_draws do not match")
    if payload.get("initial_main_draws") != payload["initial_pity"]:
        raise ValueError("initial draw configuration does not match")
    if payload.get("total_draws") != payload["main_draws"] + payload["bonus_draws"]:
        raise ValueError("draw configuration does not match")
    expected_count = payload["trials"] * payload["total_draws"]
    if payload["trace_enabled"]:
        if payload["record_count"] != expected_count:
            raise ValueError("Trace record_count does not match configuration")
    elif payload["record_count"] != 0:
        raise ValueError("Non-Trace result must have record_count=0")


def _validate_run_id(run_id):
    try:
        valid = type(run_id) is str and str(UUID(run_id)) == run_id
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("run_id must be a canonical UUID string")


def _cancel_if_requested(cancel_check):
    if cancel_check is not None and cancel_check():
        raise SimulationCancelled("simulation cancelled")


def _trace_connection(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


class HistoryRepository:
    """Persist immutable summaries and transactionally import complete traces."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _require_database_version(connection):
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != DATABASE_SCHEMA_VERSION:
            raise ValueError(
                f"历史数据库版本不兼容：当前版本 {version}，需要版本 {DATABASE_SCHEMA_VERSION}"
            )

    @staticmethod
    def _has_user_schema(connection):
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1"
        ).fetchone() is not None

    def _inspect_schema(self, path):
        # Callers pass a private TemporaryDirectory snapshot; recovery may write there.
        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            return version, version == 0 and self._has_user_schema(connection)

    def _read_components(self):
        components = []
        for suffix in _COMPONENT_SUFFIXES:
            try:
                components.append(Path(str(self.path) + suffix).read_bytes())
            except FileNotFoundError:
                components.append(None)
        return tuple(components)

    def _stable_snapshot(self, directory):
        for _ in range(3):
            snapshot = Path(mkdtemp(dir=directory)) / self.path.name
            copied = []
            for suffix in _COMPONENT_SUFFIXES:
                source = Path(str(self.path) + suffix)
                destination = Path(str(snapshot) + suffix)
                try:
                    shutil.copyfile(source, destination)
                except FileNotFoundError:
                    copied.append(None)
                else:
                    copied.append(destination.read_bytes())
            first = self._read_components()
            second = self._read_components()
            if tuple(copied) == first == second:
                return snapshot, first
        raise ValueError("历史数据库状态不稳定，无法安全初始化")

    def initialize(self):
        try:
            self.path.stat()
        except FileNotFoundError:
            pass
        else:
            with TemporaryDirectory() as directory:
                snapshot, components = self._stable_snapshot(directory)
                version, has_user_schema = self._inspect_schema(snapshot)
                if version == DATABASE_SCHEMA_VERSION:
                    return
                if version != 0 or has_user_schema:
                    raise ValueError(
                        f"历史数据库版本不兼容：当前版本 {version}，需要版本 {DATABASE_SCHEMA_VERSION}"
                    )
                confirmation, confirmed_components = self._stable_snapshot(directory)
                confirmed_version, confirmed_user_schema = self._inspect_schema(confirmation)
                if confirmed_version == DATABASE_SCHEMA_VERSION:
                    return
                if confirmed_version != 0 or confirmed_user_schema:
                    raise ValueError(
                        f"历史数据库版本不兼容：当前版本 {confirmed_version}，需要版本 {DATABASE_SCHEMA_VERSION}"
                    )
                if confirmed_components != components:
                    raise ValueError("历史数据库状态不稳定，无法安全初始化")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == DATABASE_SCHEMA_VERSION:
                return
            if version != 0 or self._has_user_schema(connection):
                raise ValueError(
                    f"历史数据库版本不兼容：当前版本 {version}，需要版本 {DATABASE_SCHEMA_VERSION}"
                )
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)

    def save_run(self, run_id: str, payload: dict, *, trace_path=None,
                 cancel_check=None, commit_guard=None) -> str:
        _validate_run_id(run_id)
        _validate_payload(payload)
        trace_enabled = payload["trace_enabled"]
        if trace_enabled != (trace_path is not None):
            raise ValueError("Trace result requires exactly one completed trace_path")
        seed = payload["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        summary = dict(payload)
        row = {
            "id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "rule_name": payload["rule_name"],
            "rule_version": payload["rule_version"],
            "main_draws": payload["main_draws"],
            "trials": payload["trials"],
            "initial_pity": payload["initial_pity"],
            "initial_five_star_pity": payload["initial_five_star_pity"],
            "seed": str(seed),
            "trace_enabled": int(trace_enabled),
            "record_count": payload["record_count"],
            "pool_config_json": json.dumps(payload["pool_config"], sort_keys=True, allow_nan=False),
            "result_json": json.dumps(summary, sort_keys=True, allow_nan=False),
            "schema_version": DATABASE_SCHEMA_VERSION,
        }
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        trace = _trace_connection(trace_path) if trace_enabled else None
        try:
            if trace is not None:
                trace.execute("BEGIN")
                metadata = trace.execute("SELECT * FROM metadata WHERE id=1").fetchone()
                expected = {
                    "format_version": TRACE_STORE_FORMAT_VERSION,
                    "complete": 1,
                    "record_count": payload["record_count"],
                    "trials": payload["trials"],
                    "draws": payload["main_draws"],
                    "initial_main_draws": payload["initial_main_draws"],
                    "bonus_per_trial": payload["bonus_draws"],
                }
                if metadata is None or any(metadata[key] != value for key, value in expected.items()):
                    raise ValueError("Trace metadata does not match result configuration")
            with closing(self._connect()) as connection:
                self._require_database_version(connection)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM simulation_runs WHERE id=?", (run_id,)
                    ).fetchone()
                    if existing is not None:
                        same = all(existing[key] == row[key] for key in _SNAPSHOT_COLUMNS)
                        stored_count = connection.execute(
                            "SELECT count(*) FROM draw_records WHERE run_id=?", (run_id,)
                        ).fetchone()[0]
                        if not same or stored_count != payload["record_count"]:
                            raise ValueError("run_id already has a different snapshot")
                        connection.rollback()
                        return run_id
                    connection.execute(
                        f"INSERT INTO simulation_runs ({columns}) VALUES ({placeholders})",
                        tuple(row.values()),
                    )
                    imported = 0
                    if trace is not None:
                        cursor = trace.execute(
                            "SELECT trial_index, draw_index, source, source_index, rarity, "
                            "character_name, record_json FROM records "
                            "ORDER BY trial_index, draw_index"
                        )
                        while batch := cursor.fetchmany(_IMPORT_BATCH_SIZE):
                            _cancel_if_requested(cancel_check)
                            values = []
                            for source_row in batch:
                                record = json.loads(source_row["record_json"])
                                validate_record(record)
                                projected = (
                                    record["trial_index"], record["draw_index"], record["source"],
                                    record["source_index"],
                                    record["draw_result"]["outcome"]["rarity"],
                                    record["draw_result"]["outcome"]["character_name"],
                                )
                                if tuple(source_row[:6]) != projected:
                                    raise ValueError("Trace query columns do not match record JSON")
                                values.append((run_id, *projected, source_row["record_json"]))
                            connection.executemany(
                                "INSERT INTO draw_records (run_id, trial_index, draw_index, source, "
                                "source_index, rarity, character_name, record_json) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values,
                            )
                            imported += len(values)
                    if imported != payload["record_count"]:
                        raise ValueError("Imported Trace record count does not match result")
                    guard = commit_guard() if commit_guard is not None else nullcontext()
                    with guard:
                        _cancel_if_requested(cancel_check)
                        connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        finally:
            if trace is not None:
                trace.close()
        return run_id

    @staticmethod
    def _summary(row):
        result = json.loads(row["result_json"])
        _validate_payload(result)
        require_version(row["schema_version"], DATABASE_SCHEMA_VERSION, "数据库记录")
        result.update({key: row[key] for key in row.keys()
                       if key not in ("result_json", "pool_config_json")})
        result["seed"] = int(row["seed"])
        result["trace_enabled"] = bool(row["trace_enabled"])
        result["pool_config"] = json.loads(row["pool_config_json"])
        _validate_payload(result)
        return result

    def get_run(self, id: str) -> dict | None:
        with closing(_trace_connection(self.path)) as connection:
            self._require_database_version(connection)
            row = connection.execute("SELECT * FROM simulation_runs WHERE id = ?", (id,)).fetchone()
            if row is None:
                return None
            return self._summary(row)

    def get_trace_reader(self, run_id: str) -> TraceReader:
        return TraceReader.for_history(self.path, run_id)

    def list_runs(self, filters: dict, limit: int, offset: int) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer in 1–100")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if filters.keys() - _FILTERS.keys():
            raise ValueError("Unsupported history filter")
        where = " AND ".join(_FILTERS[key] for key in filters)
        query = "SELECT * FROM simulation_runs"
        if where:
            query += " WHERE " + where
        query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        with closing(self._connect()) as connection:
            self._require_database_version(connection)
            return [self._summary(row) for row in connection.execute(
                query, (*filters.values(), limit, offset)
            )]

    def count_runs(self, filters: dict) -> int:
        if filters.keys() - _FILTERS.keys():
            raise ValueError("Unsupported history filter")
        where = " AND ".join(_FILTERS[key] for key in filters)
        query = "SELECT count(*) FROM simulation_runs"
        if where:
            query += " WHERE " + where
        with closing(self._connect()) as connection:
            self._require_database_version(connection)
            return connection.execute(query, tuple(filters.values())).fetchone()[0]

    def delete_run(self, id: str):
        with closing(self._connect()) as connection, connection:
            self._require_database_version(connection)
            connection.execute("DELETE FROM simulation_runs WHERE id = ?", (id,))

    def backup_to(self, path: str | Path):
        with closing(self._connect()) as connection, closing(sqlite3.connect(path)) as destination:
            self._require_database_version(connection)
            connection.backup(destination)
