from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
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
    seed TEXT NOT NULL,
    trace_enabled INTEGER NOT NULL CHECK (trace_enabled IN (0, 1)),
    bonus_draws INTEGER NOT NULL,
    total_draws INTEGER NOT NULL,
    initial_main_draws INTEGER NOT NULL,
    final_main_draws INTEGER NOT NULL,
    mean_main_six_stars REAL NOT NULL,
    mean_bonus_six_stars REAL NOT NULL,
    mean_six_stars REAL NOT NULL,
    theoretical_expected_main_count REAL NOT NULL,
    theoretical_expected_bonus_count REAL NOT NULL,
    theoretical_expected_count REAL NOT NULL,
    mean_count_error REAL NOT NULL,
    mean_count_relative_error REAL,
    at_least_one_rate REAL NOT NULL,
    observed_mean_interval REAL,
    theoretical_mean_interval REAL NOT NULL,
    count_distribution_json TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    result_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL
);
CREATE INDEX simulation_runs_created_at ON simulation_runs(created_at DESC);
CREATE INDEX simulation_runs_rule_name ON simulation_runs(rule_name);
CREATE TABLE draw_records (
    run_id TEXT NOT NULL REFERENCES simulation_runs(id) ON DELETE CASCADE,
    draw_index INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_index INTEGER NOT NULL,
    bonus_event TEXT,
    main_draws_completed INTEGER NOT NULL,
    pity_position INTEGER NOT NULL,
    probability REAL NOT NULL,
    is_six_star INTEGER NOT NULL CHECK (is_six_star IN (0, 1)),
    misses_after_draw INTEGER NOT NULL,
    PRIMARY KEY (run_id, draw_index)
);
PRAGMA user_version = 1;
"""

_SUMMARY_FIELDS = """
rule_name rule_version main_draws trials initial_pity bonus_draws total_draws
initial_main_draws final_main_draws mean_main_six_stars mean_bonus_six_stars
mean_six_stars theoretical_expected_main_count theoretical_expected_bonus_count
theoretical_expected_count mean_count_error mean_count_relative_error
at_least_one_rate observed_mean_interval theoretical_mean_interval duration_seconds
""".split()

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

    def initialize(self):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 1:
                return
            if version != 0:
                raise ValueError(f"Unsupported database schema version: {version}")
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
        row = {key: payload[key] for key in _SUMMARY_FIELDS}
        run_id = str(uuid4())
        row.update(
            id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            seed=str(seed),
            trace_enabled=int(trace_enabled),
            count_distribution_json=json.dumps(payload["count_distribution"], sort_keys=True),
            result_json=json.dumps(summary, sort_keys=True),
            schema_version=1,
        )
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO simulation_runs ({columns}) VALUES ({placeholders})",
                tuple(row.values()),
            )
            if trace_enabled:
                connection.executemany(
                    """INSERT INTO draw_records (
                        run_id, draw_index, source, source_index, bonus_event,
                        main_draws_completed, pity_position, probability,
                        is_six_star, misses_after_draw
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        (run_id, record["draw_index"], record["source"], record["source_index"],
                         record["bonus_event"], record["main_draws_completed"],
                         record["pity_position"], record["probability"],
                         int(record["is_six_star"]), record["state_after"]["misses_since_six_star"])
                        for record in payload["records"]
                    ),
                )
        return run_id

    @staticmethod
    def _summary(row):
        result = json.loads(row["result_json"])
        result.update({key: row[key] for key in row.keys()
                       if key not in ("result_json", "count_distribution_json")})
        result["seed"] = int(row["seed"])
        result["trace_enabled"] = bool(row["trace_enabled"])
        result["count_distribution"] = json.loads(row["count_distribution_json"])
        return result

    def get_run(self, id: str, include_records: bool = False) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM simulation_runs WHERE id = ?", (id,)).fetchone()
            if row is None:
                return None
            result = self._summary(row)
            if include_records:
                result["records"] = []
                for row in connection.execute(
                    "SELECT * FROM draw_records WHERE run_id = ? ORDER BY draw_index", (id,)
                ):
                    record = dict(row)
                    del record["run_id"]
                    record["state_after"] = {"misses_since_six_star": record.pop("misses_after_draw")}
                    record["is_six_star"] = bool(record["is_six_star"])
                    result["records"].append(record)
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
