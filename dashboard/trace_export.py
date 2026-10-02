"""Atomic JSONL export of read-only history events."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict
from uuid import UUID

from dashboard.trace_store import TraceFilter, TraceReader
from lottery_simulator.formats import (
    DATABASE_SCHEMA_VERSION, EVENT_FORMAT_VERSION, RESULT_FORMAT_VERSION,
    RULE_VERSION, SAMPLING_VERSION, TRACE_EXPORT_FORMAT_VERSION, require_version,
)


def iter_jsonl(metadata, reader, filters, batch_size=1000):
    if not isinstance(metadata, dict) or {"events", "records"} & metadata.keys():
        raise ValueError("metadata must be an event-free object")
    require_version(metadata.get("result_format_version"), RESULT_FORMAT_VERSION, "结果")
    require_version(metadata.get("event_format_version"), EVENT_FORMAT_VERSION, "事件")
    require_version(metadata.get("sampling_version"), SAMPLING_VERSION, "抽样")
    if metadata.get("rule_version") != RULE_VERSION:
        raise ValueError("rule version is unsupported")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    count = reader.count_events(filters)
    header = {"type": "metadata", "export_format_version": TRACE_EXPORT_FORMAT_VERSION,
              "run": metadata, "filters": asdict(filters), "matched_event_count": count}
    yield json.dumps(header, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    iterator = reader.iter_events(filters, batch_size=batch_size)
    try:
        for event in iterator:
            yield json.dumps({"type": "event", "event": event}, ensure_ascii=False,
                             sort_keys=True, allow_nan=False) + "\n"
    finally:
        iterator.close()


def export_trace(database, run_id, output, **filter_values):
    database, output = Path(database).resolve(), Path(output).resolve()
    forbidden = (database, *(Path(str(database) + suffix) for suffix in ("-journal", "-wal", "-shm")))
    if any(output == path or (output.exists() and path.exists() and os.path.samefile(output, path))
           for path in forbidden):
        raise ValueError("output cannot replace the history database")
    if not database.is_file():
        raise ValueError("history database does not exist")
    run_id = str(UUID(str(run_id)))
    reader = TraceReader.for_history(database, run_id)
    # Both reads use SQLite URI mode=ro; export never boots Django or creates a DB.
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != DATABASE_SCHEMA_VERSION:
            raise ValueError("history database version is incompatible")
        row = db.execute("SELECT result_json,trace_enabled FROM simulation_runs WHERE id=?",
                         (reader._run_id,)).fetchone()
        if row is None or not row[1]:
            raise ValueError("trace history run is unavailable")
        metadata = json.loads(row[0])
    filters = TraceFilter(**filter_values)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         suffix=".tmp", delete=False) as target:
            temporary = Path(target.name)
            for line in iter_jsonl(metadata, reader, filters):
                target.write(line)
            target.flush()
            os.fsync(target.fileno())
        # Hard-link publishes atomically and refuses to overwrite any existing path.
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
