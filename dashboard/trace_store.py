"""Validated, batched storage and read-only queries for process events."""

from contextlib import closing
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3
from dataclasses import replace
from uuid import UUID

from dashboard.limits import TraceLimits
from lottery_simulator.control import ProgressCallback, check_cancelled
from lottery_simulator.formats import EVENT_FORMAT_VERSION, TRACE_STORE_FORMAT_VERSION, require_version
from lottery_simulator.results import ProcessEvent
from lottery_simulator.rules.runtime import (
    DrawState, advance_state, character_probabilities, initial_state,
    normalize_parameters, pity_status, rarity_probabilities,
)
from lottery_simulator.engine import bonus_pool
from lottery_simulator.events import event_counts


def _integer(value, name, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ValueError(f"{name} must be an integer in storage range")


def _uuid(value, name):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{name} must be a canonical UUID") from None


def validate_event(event):
    """Validate serialized ProcessEvent data at every storage boundary."""
    if isinstance(event, ProcessEvent):
        event = event.to_dict()
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    require_version(event.get("event_format_version"), EVENT_FORMAT_VERSION, "事件")
    required = {"event_format_version", "trial_index", "event_index", "event_type",
                "main_draws_completed", "mechanism_id", "draw_index", "source",
                "source_index"}
    if set(event) not in (required | {"draw_result", "main_state_before", "main_state_after"},
                          required | {"grant"}):
        raise ValueError("event fields do not match event type")
    _integer(event["trial_index"], "trial_index", 1)
    _integer(event["event_index"], "event_index", 1)
    _integer(event["main_draws_completed"], "main_draws_completed")
    if event["mechanism_id"] is not None and (not isinstance(event["mechanism_id"], str) or not event["mechanism_id"]):
        raise ValueError("mechanism_id must be text or null")
    if event["event_type"] == "draw":
        if event.get("source") not in ("main", "bonus"):
            raise ValueError("invalid draw source")
        for key in ("draw_index", "source_index"):
            _integer(event.get(key), key, 1)
        result = event["draw_result"]
        if not isinstance(result, dict) or set(result) != {
                "outcome", "probabilities", "character_probability", "state_before", "state_after"}:
            raise ValueError("draw_result is invalid")
        outcome = result["outcome"]
        if not isinstance(outcome, dict):
            raise ValueError("draw outcome is invalid")
        if set(outcome) != {"rarity_id", "character_id", "character_name", "is_up", "is_limited", "rewards", "pity_status"}:
            raise ValueError("draw outcome fields are invalid")
        _uuid(outcome["rarity_id"], "rarity_id")
        character_id = outcome.get("character_id")
        if character_id is not None:
            _uuid(character_id, "character_id")
        if type(outcome.get("is_up")) is not bool or type(outcome.get("is_limited")) is not bool:
            raise ValueError("draw flags must be booleans")
        if outcome["is_up"] and not outcome["is_limited"]:
            raise ValueError("UP outcome must be limited")
        if (outcome["character_name"] is not None and
                (not isinstance(outcome["character_name"], str) or not outcome["character_name"].strip())):
            raise ValueError("character name is invalid")
        if (character_id is None) != (outcome["character_name"] is None):
            raise ValueError("character identity and name do not match")
        if character_id is None and (outcome["is_up"] or outcome["is_limited"]):
            raise ValueError("unnamed outcome cannot carry character flags")
        rewards = outcome.get("rewards")
        if not isinstance(rewards, dict):
            raise ValueError("draw rewards are invalid")
        for key, value in rewards.items():
            _uuid(key, "reward id")
            try:
                valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("reward amount is invalid")
        status = outcome.get("pity_status")
        if not isinstance(status, dict) or set(status) != {"soft_active", "hard_active", "big_forced"}:
            raise ValueError("pity status is invalid")
        if type(status["big_forced"]) is not bool:
            raise ValueError("big_forced must be a boolean")
        for key in ("soft_active", "hard_active"):
            if not isinstance(status[key], list):
                raise ValueError("active pity IDs must be a list")
            for rarity_id in status[key]:
                _uuid(rarity_id, "active pity id")
        probs = result["probabilities"]
        if not isinstance(probs, dict):
            raise ValueError("draw probabilities are invalid")
        if any(not isinstance(key, str) for key in probs):
            raise ValueError("rarity probability IDs are invalid")
        for key, value in probs.items():
            _uuid(key, "probability id")
            try:
                valid = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("draw probability is invalid")
        try:
            total_probability = math.fsum(probs.values())
        except (OverflowError, ValueError):
            total_probability = math.inf
        if abs(total_probability - 1) > 1e-12:
            raise ValueError("rarity probabilities do not sum to one")
        character_probability = result["character_probability"]
        if character_probability is not None:
            try:
                valid = (type(character_probability) in (int, float) and
                         math.isfinite(character_probability) and 0 <= character_probability <= 1)
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("character probability is invalid")
        if character_probability is None and character_id is not None:
            raise ValueError("named character needs a non-null probability")
        for key in ("main_state_before", "main_state_after", "state_before", "state_after"):
            state = event.get(key) if key.startswith("main_") else result.get(key)
            DrawState.from_dict(state)
    elif event["event_type"] == "character_grant":
        if any(event.get(key) is not None for key in ("draw_index", "source", "source_index")):
            raise ValueError("grant event contains draw coordinates")
        grant = event["grant"]
        if not isinstance(grant, dict) or set(grant) != {
                "character_id", "rarity_id", "character_name", "is_up", "is_limited",
                "quantity", "trigger_main_draw"}:
            raise ValueError("grant data is invalid")
        _uuid(grant["character_id"], "grant character id")
        _uuid(grant["rarity_id"], "grant rarity id")
        if not isinstance(grant["character_name"], str):
            raise ValueError("grant character name is invalid")
        if not grant["character_name"].strip():
            raise ValueError("grant character name is empty")
        if type(grant["is_up"]) is not bool or type(grant["is_limited"]) is not bool:
            raise ValueError("grant flags must be booleans")
        if grant["is_up"] and not grant["is_limited"]:
            raise ValueError("UP grant must be limited")
        _integer(grant["quantity"], "quantity", 1)
        _integer(grant["trigger_main_draw"], "trigger_main_draw", 1)
        if grant["trigger_main_draw"] != event["main_draws_completed"]:
            raise ValueError("grant trigger position does not match event")
    else:
        raise ValueError("event_type is invalid")
    return event


def iter_validated_events(compiled, parameters, counts, events, *, batch_size=1000,
                           cancel_check=None, progress_callback=None):
    """Yield events only after matching their order and semantics to frozen snapshots."""
    parameters = normalize_parameters(compiled, parameters)
    expected_counts = event_counts(compiled.rule, parameters)
    if not parameters.trace or counts != expected_counts:
        raise ValueError("Trace parameters/counts do not match compiled experiment")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be positive")
    total, seen = counts.trace_events, 0
    check_cancelled(cancel_check)
    if progress_callback:
        progress_callback(0, total)
    source = iter(events)
    rule = compiled.rule
    characters = {c.id: c for p in compiled.pool.rarity_pools for c in p.characters}
    rarities = {r.id for r in rule.rarities}
    rewards = {r.id: r for r in compiled.pool.rewards}
    grant_target = characters.get(compiled.targets.get("periodic_grant"))
    bonus_compiled = bonus_pool(compiled) if expected_counts.bonus_draws else None
    target_bonus_params = replace(parameters, initial_main_draws=0, initial_small_pity={},
        initial_big_pity=replace(parameters.initial_big_pity, target_obtained=False, misses=0))

    def expect_one(trial, event_index, main_index, source_kind, source_index, mechanism,
                   main_state, draw_state, draw_compiled):
        nonlocal seen
        try:
            event = validate_event(next(source))
        except StopIteration:
            raise ValueError("Trace is missing expected events") from None
        absolute = parameters.initial_main_draws + main_index
        event_index += 1
        expected_type = "character_grant" if source_kind is None else "draw"
        if (event["trial_index"], event["event_index"], event["event_type"],
                event["main_draws_completed"], event["mechanism_id"]) != (
                trial, event_index, expected_type, absolute, mechanism):
            raise ValueError("Trace event order or trigger position is invalid")
        if source_kind is None:
            if grant_target is None:
                raise ValueError("Compiled grant target is missing")
            grant = event["grant"]
            if (grant["character_id"], grant["rarity_id"], grant["quantity"],
                    grant["character_name"], grant["is_up"], grant["is_limited"]) != (
                    grant_target.id, grant_target.rarity_id, rule.grant.quantity,
                    grant_target.name, grant_target.is_up, grant_target.is_limited):
                raise ValueError("Trace grant differs from frozen rule")
        else:
            draw_index = main_index + (rule.bonus.draws if rule.bonus.enabled and
                parameters.initial_main_draws < rule.bonus.at_main_draw <= absolute and
                absolute > rule.bonus.at_main_draw else 0) + (source_index if source_kind == "bonus" else 0)
            if (event["draw_index"], event["source"], event["source_index"]) != (
                    draw_index, source_kind, source_index):
                raise ValueError("Trace draw coordinates are invalid")
            result, outcome = event["draw_result"], event["draw_result"]["outcome"]
            state_before = draw_state.to_dict()
            expected_probabilities = rarity_probabilities(draw_compiled, draw_state)
            if result["state_before"] != state_before or result["probabilities"] != expected_probabilities:
                raise ValueError("Trace draw state/probabilities differ from frozen rule")
            rarity_id = outcome["rarity_id"]
            if rarity_id not in rarities:
                raise ValueError("Trace rarity is absent from frozen rule")
            character = characters.get(outcome["character_id"])
            if outcome["character_id"] is not None and (character is None or
                    (character.rarity_id, character.name, character.is_up, character.is_limited) !=
                    (rarity_id, outcome["character_name"], outcome["is_up"], outcome["is_limited"])):
                raise ValueError("Trace character differs from frozen pool")
            character_probs = character_probabilities(draw_compiled, rarity_id, draw_state)
            selected_probability = character_probs.get(outcome["character_id"]) if character_probs else None
            if result["character_probability"] != selected_probability:
                raise ValueError("Trace character probability differs from frozen pool")
            if expected_probabilities[rarity_id] <= 0 or (selected_probability is not None and selected_probability <= 0):
                raise ValueError("Trace outcome has zero probability")
            next_state = advance_state(draw_compiled, draw_state, rarity_id, outcome["character_id"])
            if result["state_after"] != next_state.to_dict() or outcome["pity_status"] != pity_status(draw_compiled, draw_state):
                raise ValueError("Trace pity state differs from frozen rule")
            expected_rewards = {key: reward.amounts.get(rarity_id, 0.0) for key, reward in rewards.items()}
            if outcome["rewards"] != expected_rewards:
                raise ValueError("Trace rewards differ from frozen pool")
            if source_kind == "main":
                if event["main_state_before"] != main_state.to_dict() or event["main_state_after"] != next_state.to_dict():
                    raise ValueError("Trace main state is discontinuous")
            elif event["main_state_before"] != main_state.to_dict() or event["main_state_after"] != main_state.to_dict():
                raise ValueError("Bonus event modified main state")
        seen += 1
        if seen % batch_size == 0:
            check_cancelled(cancel_check)
            if progress_callback:
                progress_callback(seen, total)
        return event, event_index

    for trial in range(1, parameters.trials + 1):
        main_state = initial_state(compiled, parameters)
        bonus_state = None
        event_index = draw_index = 0
        for main_index in range(1, parameters.draws + 1):
            absolute = parameters.initial_main_draws + main_index
            event, event_index = expect_one(trial, event_index, main_index, "main", main_index,
                                            None, main_state, main_state, compiled)
            yield event
            outcome = event["draw_result"]["outcome"]
            main_state = advance_state(compiled, main_state, outcome["rarity_id"], outcome["character_id"])
            draw_index += 1
            if rule.bonus.enabled and absolute == rule.bonus.at_main_draw:
                bonus_state = initial_state(bonus_compiled, target_bonus_params)
                for position in range(1, rule.bonus.draws + 1):
                    event, event_index = expect_one(trial, event_index, main_index, "bonus", position,
                        "first_bonus", main_state, bonus_state, bonus_compiled)
                    yield event
                    outcome = event["draw_result"]["outcome"]
                    bonus_state = advance_state(bonus_compiled, bonus_state,
                                                outcome["rarity_id"], outcome["character_id"])
                    draw_index += 1
            if rule.grant.enabled and absolute % rule.grant.period == 0:
                event, event_index = expect_one(trial, event_index, main_index, None, None,
                    "periodic_grant", main_state, None, None)
                yield event
        check_cancelled(cancel_check)
    if seen != total:
        raise ValueError("Trace event count does not match frozen experiment")
    try:
        next(source)
    except StopIteration:
        pass
    else:
        raise ValueError("Trace contains extra events")
    check_cancelled(cancel_check)
    if progress_callback:
        progress_callback(total, total)
    check_cancelled(cancel_check)


@dataclass(frozen=True, slots=True)
class TraceFilter:
    trial_from: int | None = None
    trial_to: int | None = None
    source: str | None = None
    source_from: int | None = None
    source_to: int | None = None
    rarity_id: str | None = None
    character_id: str | None = None
    unnamed_character: bool = False
    event_type: str | None = None
    main_from: int | None = None
    main_to: int | None = None

    def __post_init__(self):
        for name in ("trial_from", "trial_to", "source_from", "source_to", "main_from", "main_to"):
            value = getattr(self, name)
            if value is not None:
                _integer(value, name, 1)
        for lo, hi in ((self.trial_from, self.trial_to), (self.source_from, self.source_to),
                       (self.main_from, self.main_to)):
            if lo is not None and hi is not None and lo > hi:
                raise ValueError("trace range is reversed")
        if self.source is not None and self.source not in ("main", "bonus"):
            raise ValueError("source must be main or bonus")
        if self.event_type is not None and self.event_type not in ("draw", "character_grant"):
            raise ValueError("event_type is invalid")
        if type(self.unnamed_character) is not bool:
            raise ValueError("unnamed_character must be a boolean")
        if self.unnamed_character and self.character_id is not None:
            raise ValueError("named and unnamed filters are mutually exclusive")
        if self.unnamed_character and self.event_type == "character_grant":
            raise ValueError("grant events always have a character")
        if self.source is not None and self.event_type == "character_grant":
            raise ValueError("source filters apply only to draws")
        if (self.source_from is not None or self.source_to is not None) and self.event_type == "character_grant":
            raise ValueError("source positions apply only to draws")
        for value in (self.rarity_id, self.character_id):
            if value is not None:
                _uuid(value, "trace filter ID")


_EVENT_SCHEMA = f"""
CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), format_version INTEGER NOT NULL,
 complete INTEGER NOT NULL CHECK(complete IN (0,1)), event_count INTEGER NOT NULL,
 trials INTEGER, main_draws INTEGER, initial_main_draws INTEGER, bonus_draws INTEGER,
 CHECK(complete=0 OR (trials>0 AND main_draws>0 AND initial_main_draws>=0 AND bonus_draws>=0)));
INSERT INTO metadata VALUES(1, {TRACE_STORE_FORMAT_VERSION}, 0, 0, NULL, NULL, NULL, NULL);
CREATE TABLE events (trial_index INTEGER NOT NULL, event_index INTEGER NOT NULL,
 event_type TEXT NOT NULL, main_draws_completed INTEGER NOT NULL, mechanism_id TEXT,
 draw_index INTEGER, source TEXT, source_index INTEGER, rarity_id TEXT, character_id TEXT,
 event_json TEXT NOT NULL CHECK(json_valid(event_json)),
 PRIMARY KEY(trial_index,event_index),
 CHECK(typeof(trial_index)='integer' AND trial_index>0 AND typeof(event_index)='integer' AND event_index>0),
 CHECK(event_type IN ('draw','character_grant')),
 CHECK(json_type(event_json,'$') IS 'object' AND json_type(event_json,'$.event_format_version') IS 'integer'
  AND json_extract(event_json,'$.event_format_version')={EVENT_FORMAT_VERSION}),
 CHECK(trial_index IS json_extract(event_json,'$.trial_index') AND event_index IS json_extract(event_json,'$.event_index')
  AND event_type IS json_extract(event_json,'$.event_type')
  AND main_draws_completed IS json_extract(event_json,'$.main_draws_completed')
  AND mechanism_id IS json_extract(event_json,'$.mechanism_id')
  AND draw_index IS json_extract(event_json,'$.draw_index') AND source IS json_extract(event_json,'$.source')
  AND source_index IS json_extract(event_json,'$.source_index')),
 CHECK((event_type='draw' AND source IN ('main','bonus') AND draw_index>0 AND source_index>0
  AND rarity_id IS json_extract(event_json,'$.draw_result.outcome.rarity_id')
  AND character_id IS json_extract(event_json,'$.draw_result.outcome.character_id')
  AND json_type(event_json,'$.grant') IS NULL)
  OR (event_type='character_grant' AND source IS NULL AND draw_index IS NULL AND source_index IS NULL
  AND rarity_id IS json_extract(event_json,'$.grant.rarity_id')
  AND character_id IS json_extract(event_json,'$.grant.character_id')
  AND json_type(event_json,'$.draw_result') IS NULL)));
CREATE INDEX events_type ON events(event_type);
CREATE INDEX events_source_position ON events(source,source_index);
CREATE INDEX events_rarity ON events(rarity_id);
CREATE INDEX events_character ON events(character_id);
"""


def _columns(event):
    if event["event_type"] == "draw":
        outcome = event["draw_result"]["outcome"]
        rarity, character = outcome["rarity_id"], outcome["character_id"]
    else:
        rarity, character = event["grant"]["rarity_id"], event["grant"]["character_id"]
    return (event["trial_index"], event["event_index"], event["event_type"],
            event["main_draws_completed"], event["mechanism_id"], event["draw_index"],
            event["source"], event["source_index"], rarity, character,
            json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False))


def validate_event_row(row, *, history=False):
    event = validate_event(json.loads(row["event_json"]))
    expected = _columns(event)
    fields = ("trial_index", "event_index", "event_type", "main_draws_completed", "mechanism_id",
              "draw_index", "source", "source_index", "rarity_id", "character_id")
    if tuple(row[key] for key in fields) != expected[:10]:
        raise ValueError("Trace indexed columns do not match event JSON")
    return event


class TraceWriter:
    def __init__(self, path, *, limits: TraceLimits):
        self.path = Path(path)
        if self.path.exists():
            raise ValueError("Trace output already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.limits = limits
        with self.path.open("xb"):
            pass
        self.path.chmod(0o600)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.executescript(_EVENT_SCHEMA)
        except Exception:
            self.close()
            self.path.unlink(missing_ok=True)
            raise
        self._buffer, self._count = [], 0
        self._finished = self._failed = False

    def append(self, event: ProcessEvent):
        if self._connection is None or self._finished or self._failed:
            raise RuntimeError("Trace writer is closed, complete or failed")
        value = validate_event(event)
        if self.limits.max_records is not None and self._count >= self.limits.max_records:
            raise ValueError("Trace event limit exceeded")
        self._buffer.append(_columns(value))
        self._count += 1
        if len(self._buffer) >= self.limits.batch_size:
            self._flush()

    def _flush(self):
        if not self._buffer:
            return
        try:
            with self._connection:
                self._connection.executemany("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)", self._buffer)
                self._connection.execute("UPDATE metadata SET event_count=? WHERE id=1", (self._count,))
        except Exception:
            self._failed = True
            raise
        self._buffer.clear()

    def finish(self, compiled, parameters, counts, *, cancel_check=None,
               progress_callback: ProgressCallback | None = None):
        if self._connection is None or self._finished or self._failed:
            raise RuntimeError("Trace writer is closed, complete or failed")
        parameters = normalize_parameters(compiled, parameters)
        computed_counts = event_counts(compiled.rule, parameters)
        if (not parameters.trace or counts != computed_counts or self._count != counts.trace_events):
            raise ValueError("Trace parameters/counts do not match compiled experiment")
        self._flush()
        rule = compiled.rule
        trials, draws = parameters.trials, parameters.draws
        initial = parameters.initial_main_draws
        total = self._count
        check_cancelled(cancel_check)
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            raw_rows = self._connection.execute("SELECT * FROM events ORDER BY trial_index,event_index")
            source = (validate_event_row(row) for row in raw_rows)
            for _ in iter_validated_events(compiled, parameters, counts, source,
                    batch_size=self.limits.batch_size, cancel_check=cancel_check,
                    progress_callback=progress_callback):
                pass
            check_cancelled(cancel_check)
            bonus_count = counts.bonus_draws // trials
            self._connection.execute("UPDATE metadata SET complete=1,event_count=?,trials=?,main_draws=?,initial_main_draws=?,bonus_draws=? WHERE id=1",
                                     (total, trials, draws, initial, bonus_count))
        self._finished = True

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._buffer.clear()


class TraceReader:
    def __init__(self, path, *, source_kind, run_id=None):
        self.path, self._source_kind, self._run_id = Path(path), source_kind, run_id

    @classmethod
    def for_trace_store(cls, path):
        return cls(path, source_kind="store")

    @classmethod
    def for_history(cls, path, run_id):
        return cls(path, source_kind="history", run_id=UUID(str(run_id)).hex)

    def _connect(self):
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            if self._source_kind == "store":
                meta = db.execute("SELECT format_version,complete FROM metadata WHERE id=1").fetchone()
                if meta is None:
                    raise ValueError("Trace store is unavailable or incomplete")
                require_version(meta["format_version"], TRACE_STORE_FORMAT_VERSION, "临时Trace")
                if type(meta["complete"]) is not int or meta["complete"] != 1:
                    raise ValueError("Trace store is unavailable or incomplete")
            else:
                from lottery_simulator.formats import DATABASE_SCHEMA_VERSION
                if db.execute("PRAGMA user_version").fetchone()[0] != DATABASE_SCHEMA_VERSION:
                    raise ValueError("History database version is incompatible")
                row = db.execute("SELECT trace_enabled FROM simulation_runs WHERE id=?", (self._run_id,)).fetchone()
                if row is None or row[0] != 1:
                    raise ValueError("Trace history run is unavailable")
            return db
        except Exception:
            db.close()
            raise

    def _where(self, filters):
        if not isinstance(filters, TraceFilter):
            raise ValueError("filters must be TraceFilter")
        clauses, args = [], []
        if self._source_kind == "history":
            clauses.append("run_id=?"); args.append(self._run_id)
        for col, op, value in (("trial_index", ">=", filters.trial_from), ("trial_index", "<=", filters.trial_to),
                               ("source", "=", filters.source), ("source_index", ">=", filters.source_from),
                               ("source_index", "<=", filters.source_to), ("rarity_id", "=", filters.rarity_id),
                               ("character_id", "=", filters.character_id), ("event_type", "=", filters.event_type),
                               ("main_draws_completed", ">=", filters.main_from),
                               ("main_draws_completed", "<=", filters.main_to)):
            if value is not None:
                clauses.append(f"{col}{op}?"); args.append(value)
        if filters.unnamed_character:
            clauses.append("character_id IS NULL")
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), args

    def count_events(self, filters):
        where, args = self._where(filters)
        table = "events" if self._source_kind == "store" else "simulation_events"
        with closing(self._connect()) as db:
            return db.execute(f"SELECT count(*) FROM {table}{where}", args).fetchone()[0]

    def query_events(self, filters, *, limit=100, offset=0):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        _integer(offset, "offset")
        where, args = self._where(filters)
        table = "events" if self._source_kind == "store" else "simulation_events"
        with closing(self._connect()) as db:
            rows = db.execute(f"SELECT * FROM {table}{where} ORDER BY trial_index,event_index LIMIT ? OFFSET ?",
                              (*args, limit, offset)).fetchall()
            return [validate_event_row(row, history=self._source_kind == "history") for row in rows]

    def iter_events(self, filters, *, batch_size=1000):
        _integer(batch_size, "batch_size", 1)
        where, args = self._where(filters)
        table = "events" if self._source_kind == "store" else "simulation_events"
        db = self._connect()
        try:
            db.execute("BEGIN")
            cursor = db.execute(f"SELECT * FROM {table}{where} ORDER BY trial_index,event_index", args)
            while rows := cursor.fetchmany(batch_size):
                for row in rows:
                    yield validate_event_row(row, history=self._source_kind == "history")
        finally:
            db.close()

    def position_counts(self, *, source, trial_from, trial_to, source_from, source_to):
        filters = TraceFilter(trial_from=trial_from, trial_to=trial_to, source=source,
                              source_from=source_from, source_to=source_to, event_type="draw")
        if source_to - source_from + 1 > 1000:
            raise ValueError("position range cannot exceed 1000")
        where, args = self._where(filters)
        table = "events" if self._source_kind == "store" else "simulation_events"
        with closing(self._connect()) as db:
            rows = db.execute("SELECT source_index, "
                "json_extract(event_json,'$.draw_result.outcome.rarity_id') rarity_id,count(*) n "
                f"FROM {table}{where} GROUP BY source_index,rarity_id ORDER BY source_index,rarity_id", args).fetchall()
        positions = {}
        for row in rows:
            item = positions.setdefault(row["source_index"], {"source_index": row["source_index"],
                "observations": 0, "rarity_counts": {}})
            item["observations"] += row["n"]
            item["rarity_counts"][row["rarity_id"]] = row["n"]
        for item in positions.values():
            item["rarity_rates"] = {key: value / item["observations"]
                                    for key, value in item["rarity_counts"].items()}
        return list(positions.values())
