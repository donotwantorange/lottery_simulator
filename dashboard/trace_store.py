from contextlib import closing
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sqlite3

from dashboard.limits import TraceLimits
from lottery_simulator.engine import DrawRecord
from lottery_simulator.formats import (
    DATABASE_SCHEMA_VERSION, RECORD_FORMAT_VERSION, TRACE_STORE_FORMAT_VERSION, require_version,
)


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _state(value):
    state = _object(value, "state")
    for key in ("misses_since_six_star", "misses_since_five_or_higher"):
        _integer(state.get(key), key)


def _number(value, label):
    try:
        valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                 and math.isfinite(value) and value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be a finite non-negative number")


def validate_record(record: dict) -> None:
    """Validate the current record format, including every nested business field."""
    record = _object(record, "record")
    require_version(record.get("record_format_version"), RECORD_FORMAT_VERSION, "记录")
    for key in ("trial_index", "draw_index", "source_index"):
        _integer(record.get(key), key, 1)
    _integer(record.get("main_draws_completed"), "main_draws_completed")
    if record.get("source") not in ("main", "bonus"):
        raise ValueError("source must be main or bonus")
    if "bonus_event" not in record or (record["bonus_event"] is not None
                                        and not isinstance(record["bonus_event"], str)):
        raise ValueError("bonus_event must be a string or None")
    for key in ("main_state_before", "main_state_after"):
        _state(record.get(key))
    draw_result = _object(record.get("draw_result"), "draw_result")
    for key in ("state_before", "state_after"):
        _state(draw_result.get(key))
    probabilities = _object(draw_result.get("probabilities"), "probabilities")
    for key in ("four_star", "five_star", "six_star"):
        _number(probabilities.get(key), key)
    outcome = _object(draw_result.get("outcome"), "outcome")
    if type(outcome.get("rarity")) is not int or outcome["rarity"] not in (4, 5, 6):
        raise ValueError("rarity must be 4, 5 or 6")
    if "character_name" not in outcome or (outcome["character_name"] is not None
                                           and not isinstance(outcome["character_name"], str)):
        raise ValueError("character_name must be a string or None")
    for key in ("is_up", "is_limited", "five_star_pity_triggered", "six_star_hard_pity_triggered"):
        if type(outcome.get(key)) is not bool:
            raise ValueError(f"{key} must be a boolean")
    rewards = _object(outcome.get("rewards"), "rewards")
    for name, amount in rewards.items():
        if not isinstance(name, str) or not name:
            raise ValueError("reward names must be non-empty strings")
        _number(amount, "reward amount")


@dataclass(frozen=True)
class TraceFilter:
    trial_from: int | None = None
    trial_to: int | None = None
    source: str | None = None
    rarity: int | None = None
    character_name: str | None = None
    unnamed_character: bool = False
    source_from: int | None = None
    source_to: int | None = None

    def __post_init__(self):
        for name in ("trial_from", "trial_to", "source_from", "source_to"):
            value = getattr(self, name)
            if value is not None:
                _integer(value, name, 1)
        if (self.trial_from is not None and self.trial_to is not None
                and self.trial_from > self.trial_to):
            raise ValueError("trial range is reversed")
        if (self.source_from is not None and self.source_to is not None
                and self.source_from > self.source_to):
            raise ValueError("source range is reversed")
        if self.source is not None and self.source not in ("main", "bonus"):
            raise ValueError("source must be main or bonus")
        if self.rarity is not None and (type(self.rarity) is not int
                                        or self.rarity not in (4, 5, 6)):
            raise ValueError("rarity must be 4, 5 or 6")
        if self.character_name is not None and not isinstance(self.character_name, str):
            raise ValueError("character_name must be a string")
        if type(self.unnamed_character) is not bool:
            raise ValueError("unnamed_character must be a boolean")
        if self.character_name is not None and self.rarity is None:
            raise ValueError("character filter requires rarity")
        if self.unnamed_character and self.rarity is None:
            raise ValueError("unnamed character filter requires rarity")
        if self.unnamed_character and self.character_name is not None:
            raise ValueError("named and unnamed filters are mutually exclusive")


class TraceReader:
    """Read a complete trace store or one saved history run without exposing SQL."""

    def __init__(self, path, *, source_kind, run_id=None):
        if source_kind not in ("store", "history"):
            raise ValueError("unsupported trace source")
        self.path = Path(path)
        self._source_kind = source_kind
        self._run_id = run_id

    @classmethod
    def for_trace_store(cls, path):
        return cls(path, source_kind="store")

    @classmethod
    def for_history(cls, path, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        return cls(path, source_kind="history", run_id=run_id)

    def _connect(self):
        uri = self.path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            if self._source_kind == "store":
                metadata = connection.execute(
                    "SELECT format_version, complete FROM metadata WHERE id=1"
                ).fetchone()
                if (metadata is None or metadata["format_version"] != TRACE_STORE_FORMAT_VERSION
                        or metadata["complete"] != 1):
                    raise ValueError("Trace store is unavailable or incomplete")
            else:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version != DATABASE_SCHEMA_VERSION:
                    raise ValueError("History database version is incompatible")
                run = connection.execute(
                    "SELECT trace_enabled FROM simulation_runs WHERE id=?", (self._run_id,)
                ).fetchone()
                if run is None or run["trace_enabled"] != 1:
                    raise ValueError("Trace history run is unavailable")
            return connection
        except Exception:
            connection.close()
            raise

    def _where(self, filters):
        if not isinstance(filters, TraceFilter):
            raise ValueError("filters must be TraceFilter")
        clauses, parameters = [], []
        if self._source_kind == "history":
            clauses.append("run_id = ?")
            parameters.append(self._run_id)
        for field, operator, value in (
            ("trial_index", ">=", filters.trial_from),
            ("trial_index", "<=", filters.trial_to),
            ("source", "=", filters.source),
            ("rarity", "=", filters.rarity),
            ("source_index", ">=", filters.source_from),
            ("source_index", "<=", filters.source_to),
        ):
            if value is not None:
                clauses.append(f"{field} {operator} ?")
                parameters.append(value)
        if filters.character_name is not None:
            clauses.append("character_name = ?")
            parameters.append(filters.character_name)
        elif filters.unnamed_character:
            clauses.append("character_name IS NULL")
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", parameters

    @staticmethod
    def _decode(row):
        record = json.loads(row["record_json"])
        validate_record(record)
        projected = (record["trial_index"], record["draw_index"], record["source"],
                     record["source_index"], record["draw_result"]["outcome"]["rarity"],
                     record["draw_result"]["outcome"]["character_name"])
        if tuple(row[key] for key in ("trial_index", "draw_index", "source", "source_index",
                                      "rarity", "character_name")) != projected:
            raise ValueError("Trace query columns do not match record JSON")
        return record

    def query_records(self, filters, *, limit=100, offset=0):
        if type(limit) is not int or limit not in (50, 100, 200):
            raise ValueError("limit must be 50, 100 or 200")
        _integer(offset, "offset")
        where, parameters = self._where(filters)
        table = "records" if self._source_kind == "store" else "draw_records"
        columns = "trial_index, draw_index, source, source_index, rarity, character_name, record_json"
        with closing(self._connect()) as connection:
            total = connection.execute(
                f"SELECT count(*) FROM {table}{where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT {columns} FROM {table}{where} "
                "ORDER BY trial_index, draw_index LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
            return [self._decode(row) for row in rows], total

    def iter_records(self, filters, *, batch_size=1000):
        _integer(batch_size, "batch_size", 1)
        where, parameters = self._where(filters)
        table = "records" if self._source_kind == "store" else "draw_records"
        columns = "trial_index, draw_index, source, source_index, rarity, character_name, record_json"
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"SELECT {columns} FROM {table}{where} ORDER BY trial_index, draw_index",
                parameters,
            )
            while batch := cursor.fetchmany(batch_size):
                for row in batch:
                    yield self._decode(row)

    def position_counts(self, *, source, trial_from, trial_to, source_from, source_to):
        if source not in ("main", "bonus"):
            raise ValueError("source must be main or bonus")
        for name, value in (("trial_from", trial_from), ("trial_to", trial_to),
                            ("source_from", source_from), ("source_to", source_to)):
            _integer(value, name, 1)
        if trial_from > trial_to or source_from > source_to:
            raise ValueError("range is reversed")
        if source_to - source_from + 1 > 1000:
            raise ValueError("position range cannot exceed 1000")
        table = "records" if self._source_kind == "store" else "draw_records"
        clauses = ["source=?", "trial_index>=?", "trial_index<=?",
                   "source_index>=?", "source_index<=?"]
        parameters = [source, trial_from, trial_to, source_from, source_to]
        if self._source_kind == "history":
            clauses.insert(0, "run_id=?")
            parameters.insert(0, self._run_id)
        query = (
            "SELECT source_index, count(*) observations, "
            "sum(CASE WHEN rarity=4 THEN 1 ELSE 0 END) four_count, "
            "sum(CASE WHEN rarity=5 THEN 1 ELSE 0 END) five_count, "
            "sum(CASE WHEN rarity=6 THEN 1 ELSE 0 END) six_count "
            f"FROM {table} WHERE {' AND '.join(clauses)} "
            "GROUP BY source_index ORDER BY source_index"
        )
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
            result = []
            for row in rows:
                observations = row["observations"]
                item = {key: row[key] for key in (
                    "source_index", "observations", "four_count", "five_count", "six_count"
                )}
                item.update({
                    "four_rate": row["four_count"] / observations,
                    "five_rate": row["five_count"] / observations,
                    "six_rate": row["six_count"] / observations,
                })
                result.append(item)
            return result


_SCHEMA = f"""
CREATE TABLE metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    format_version INTEGER NOT NULL CHECK (format_version = {TRACE_STORE_FORMAT_VERSION}),
    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
    record_count INTEGER NOT NULL CHECK (typeof(record_count) = 'integer' AND record_count >= 0),
    trials INTEGER CHECK (trials IS NULL OR (typeof(trials) = 'integer' AND trials > 0)),
    draws INTEGER CHECK (draws IS NULL OR (typeof(draws) = 'integer' AND draws > 0)),
    initial_main_draws INTEGER CHECK (initial_main_draws IS NULL OR
        (typeof(initial_main_draws) = 'integer' AND initial_main_draws >= 0)),
    bonus_per_trial INTEGER CHECK (bonus_per_trial IS NULL OR
        (typeof(bonus_per_trial) = 'integer' AND bonus_per_trial >= 0)),
    CHECK (complete = 0 OR (trials IS NOT NULL AND draws IS NOT NULL
        AND initial_main_draws IS NOT NULL AND bonus_per_trial IS NOT NULL
        AND record_count = trials * (draws + bonus_per_trial)))
);
CREATE TABLE records (
    trial_index INTEGER NOT NULL CHECK (typeof(trial_index) = 'integer' AND trial_index > 0),
    draw_index INTEGER NOT NULL CHECK (typeof(draw_index) = 'integer' AND draw_index > 0),
    source TEXT NOT NULL CHECK (source IN ('main', 'bonus')),
    source_index INTEGER NOT NULL CHECK (typeof(source_index) = 'integer' AND source_index > 0),
    rarity INTEGER NOT NULL CHECK (typeof(rarity) = 'integer' AND rarity IN (4, 5, 6)),
    character_name TEXT,
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    PRIMARY KEY (trial_index, draw_index),
    CHECK (json_type(record_json, '$') IS 'object'),
    CHECK (json_type(record_json, '$.record_format_version') IS 'integer'
        AND json_extract(record_json, '$.record_format_version') = {RECORD_FORMAT_VERSION}),
    CHECK (json_type(record_json, '$.trial_index') IS 'integer'
        AND trial_index IS json_extract(record_json, '$.trial_index')),
    CHECK (json_type(record_json, '$.draw_index') IS 'integer'
        AND draw_index IS json_extract(record_json, '$.draw_index')),
    CHECK (json_type(record_json, '$.source') IS 'text'
        AND source IS json_extract(record_json, '$.source')),
    CHECK (json_type(record_json, '$.source_index') IS 'integer'
        AND source_index IS json_extract(record_json, '$.source_index')),
    CHECK (json_type(record_json, '$.main_draws_completed') IS 'integer'
        AND json_extract(record_json, '$.main_draws_completed') >= 0),
    CHECK (json_type(record_json, '$.draw_result.outcome.rarity') IS 'integer'
        AND rarity IS json_extract(record_json, '$.draw_result.outcome.rarity')),
    CHECK ((json_type(record_json, '$.draw_result.outcome.character_name') IS 'text'
        OR json_type(record_json, '$.draw_result.outcome.character_name') IS 'null')
        AND character_name IS json_extract(record_json, '$.draw_result.outcome.character_name'))
);
INSERT INTO metadata (id, format_version, complete, record_count)
VALUES (1, {TRACE_STORE_FORMAT_VERSION}, 0, 0);
"""

_INSERT = """
INSERT INTO records (trial_index, draw_index, source, source_index, rarity,
                     character_name, record_json)
SELECT json_extract(value, '$.trial_index'), json_extract(value, '$.draw_index'),
       json_extract(value, '$.source'), json_extract(value, '$.source_index'),
       json_extract(value, '$.draw_result.outcome.rarity'),
       json_extract(value, '$.draw_result.outcome.character_name'), value
FROM (SELECT ? AS value)
"""


class TraceWriter:
    """Batch records into a private SQLite store, publishing only validated traces."""

    def __init__(self, path: str | Path, *, limits: TraceLimits):
        _integer(limits.batch_size, "batch_size", 1)
        _integer(limits.max_records, "max_records", 1)
        self.path = Path(path)
        self.limits = limits
        self._buffer = []
        self._count = 0
        self._finished = False
        self._failed = False
        self._connection = sqlite3.connect(self.path)
        try:
            self._connection.executescript(_SCHEMA)
        except Exception:
            self.close()
            raise

    def _ensure_writable(self):
        if self._connection is None or self._finished or self._failed:
            raise RuntimeError("Trace writer is closed, complete or failed")

    def append(self, record: DrawRecord) -> None:
        self._ensure_writable()
        if self._count >= self.limits.max_records:
            raise ValueError("Trace record limit exceeded")
        value = asdict(record)
        validate_record(value)
        self._buffer.append((json.dumps(value, sort_keys=True, allow_nan=False),))
        self._count += 1
        if len(self._buffer) == self.limits.batch_size:
            self._flush()

    def _flush(self):
        if not self._buffer:
            return
        try:
            with self._connection:
                self._connection.executemany(_INSERT, self._buffer)
                self._connection.execute(
                    "UPDATE metadata SET record_count=? WHERE id=1", (self._count,)
                )
        except Exception:
            self._failed = True
            raise
        self._buffer.clear()

    def finish(self, *, trials: int, draws: int,
               initial_main_draws: int, bonus_per_trial: int) -> None:
        self._ensure_writable()
        for label, value, minimum in (
            ("trials", trials, 1), ("draws", draws, 1),
            ("initial_main_draws", initial_main_draws, 0),
            ("bonus_per_trial", bonus_per_trial, 0),
        ):
            _integer(value, label, minimum)
        self._flush()
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            trial = draw_index = main = bonus = count = 0
            previous_state = None
            for (record_json,) in self._connection.execute(
                "SELECT record_json FROM records ORDER BY trial_index, draw_index"
            ):
                record = json.loads(record_json)
                validate_record(record)
                if record["trial_index"] != trial:
                    if record["trial_index"] != trial + 1 or (trial and (
                        main != draws or bonus != bonus_per_trial
                    )):
                        raise ValueError("Missing trial or incorrect per-trial source counts")
                    trial = record["trial_index"]
                    draw_index = main = bonus = 0
                    previous_state = None
                draw_index += 1
                count += 1
                if record["draw_index"] != draw_index:
                    raise ValueError("Non-contiguous draw_index")
                before, after = record["main_state_before"], record["main_state_after"]
                if previous_state is not None and before != previous_state:
                    raise ValueError("Discontinuous main state")
                if record["source"] == "main":
                    main += 1
                    expected_source_index = main
                    result = record["draw_result"]
                    if (record["bonus_event"] is not None or before != result["state_before"]
                            or after != result["state_after"]):
                        raise ValueError("Invalid main record state semantics")
                else:
                    bonus += 1
                    expected_source_index = bonus
                    if not main or not record["bonus_event"] or before != after:
                        raise ValueError("Invalid bonus record state semantics")
                if record["source_index"] != expected_source_index:
                    raise ValueError("Non-contiguous source_index")
                if record["main_draws_completed"] != initial_main_draws + main:
                    raise ValueError("Incorrect cumulative main draws")
                previous_state = after
            if (trial != trials or main != draws or bonus != bonus_per_trial
                    or count != self._count or count != trials * (draws + bonus_per_trial)):
                raise ValueError("Incomplete trace")
            self._connection.execute(
                "UPDATE metadata SET complete=1, record_count=?, trials=?, draws=?, "
                "initial_main_draws=?, bonus_per_trial=? WHERE id=1",
                (count, trials, draws, initial_main_draws, bonus_per_trial),
            )
        self._finished = True

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._buffer.clear()
