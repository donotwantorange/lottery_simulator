from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4


_SCHEMA = """
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
    pool_config_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 2)
);
CREATE TABLE draw_records (
    run_id TEXT NOT NULL REFERENCES simulation_runs(id) ON DELETE CASCADE,
    draw_index INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (run_id, draw_index)
);
PRAGMA user_version = 2;
"""

_FILTERS = {
    "rule_name": "rule_name = ?",
    "trace_enabled": "trace_enabled = ?",
    "created_from": "created_at >= ?",
    "created_to": "created_at <= ?",
}


class HistoryRepository:
    """Persist immutable result snapshots; load trace records only on request."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _has_user_schema(connection):
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1"
        ).fetchone() is not None

    def _inspect_schema(self, path):
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            return version, version == 0 and self._has_user_schema(connection)

    def _read_components(self):
        components = []
        for suffix in ("", "-wal", "-shm"):
            try:
                components.append(Path(str(self.path) + suffix).read_bytes())
            except FileNotFoundError:
                components.append(None)
        return tuple(components)

    def _stable_snapshot(self, directory):
        for attempt in range(3):
            snapshot = Path(directory) / f"{attempt}-{self.path.name}"
            copied = []
            for suffix in ("", "-wal", "-shm"):
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
                if version == 2:
                    return
                if version != 0 or has_user_schema:
                    raise ValueError(
                        f"历史数据库版本不兼容：当前版本 {version}，需要版本 2"
                    )
                confirmation, confirmed_components = self._stable_snapshot(directory)
                confirmed_version, confirmed_user_schema = self._inspect_schema(confirmation)
                if confirmed_version == 2:
                    return
                if confirmed_version != 0 or confirmed_user_schema:
                    raise ValueError(
                        f"历史数据库版本不兼容：当前版本 {confirmed_version}，需要版本 2"
                    )
                if confirmed_components != components:
                    raise ValueError("历史数据库状态不稳定，无法安全初始化")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 2:
                return
            if version != 0 or self._has_user_schema(connection):
                raise ValueError(f"历史数据库版本不兼容：当前版本 {version}，需要版本 2")
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)

    def save_run(self, payload: dict, trace_enabled: bool) -> str:
        if not isinstance(trace_enabled, bool):
            raise ValueError("trace_enabled must be a boolean")
        seed = payload["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        summary = {key: value for key, value in payload.items() if key != "records"}
        run_id = str(uuid4())
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
            "pool_config_json": json.dumps(payload["pool_config"], sort_keys=True),
            "result_json": json.dumps(summary, sort_keys=True),
            "schema_version": 2,
        }
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO simulation_runs ({columns}) VALUES ({placeholders})",
                tuple(row.values()),
            )
            if trace_enabled:
                connection.executemany(
                    "INSERT INTO draw_records (run_id, draw_index, record_json) VALUES (?, ?, ?)",
                    (
                        (run_id, record["draw_index"], json.dumps(record, sort_keys=True))
                        for record in payload["records"]
                    ),
                )
        return run_id

    @staticmethod
    def _summary(row):
        result = json.loads(row["result_json"])
        result.update({key: row[key] for key in row.keys()
                       if key not in ("result_json", "pool_config_json")})
        result["seed"] = int(row["seed"])
        result["trace_enabled"] = bool(row["trace_enabled"])
        result["pool_config"] = json.loads(row["pool_config_json"])
        return result

    def get_run(self, id: str, include_records: bool = False) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM simulation_runs WHERE id = ?", (id,)).fetchone()
            if row is None:
                return None
            result = self._summary(row)
            if include_records:
                result["records"] = [
                    json.loads(record["record_json"])
                    for record in connection.execute(
                        "SELECT record_json FROM draw_records "
                        "WHERE run_id = ? ORDER BY draw_index", (id,)
                    )
                ]
            return result

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
            return [self._summary(row) for row in connection.execute(
                query, (*filters.values(), limit, offset)
            )]

    def delete_run(self, id: str):
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM simulation_runs WHERE id = ?", (id,))

    def backup_to(self, path: str | Path):
        with closing(self._connect()) as connection, closing(sqlite3.connect(path)) as destination:
            connection.backup(destination)
