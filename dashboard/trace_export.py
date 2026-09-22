from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceFilter
from lottery_simulator.formats import TRACE_EXPORT_FORMAT_VERSION


def iter_jsonl(metadata, reader, filters):
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    if "records" in metadata:
        raise ValueError("metadata must not contain records")
    _, count = reader.query_records(filters, limit=50, offset=0)
    header = {
        "type": "metadata",
        "export_format_version": TRACE_EXPORT_FORMAT_VERSION,
        "run": metadata,
        "filters": asdict(filters),
        "matched_record_count": count,
    }
    yield json.dumps(header, ensure_ascii=False, sort_keys=True) + "\n"
    for record in reader.iter_records(filters):
        yield json.dumps({"type": "record", "record": record},
                         ensure_ascii=False, sort_keys=True) + "\n"


def export_trace(database, run_id, output, **filter_values):
    database = Path(database).resolve()
    output = Path(output).resolve()
    if output in {Path(str(database) + suffix) for suffix in ("", "-journal", "-wal", "-shm")}:
        raise ValueError("输出路径不能是历史数据库或其伴随文件")
    repository = HistoryRepository(database)
    run = repository.get_run(run_id)
    if run is None:
        raise ValueError("运行不存在")
    if not run.get("trace_enabled"):
        raise ValueError("运行未保存Trace")
    filters = TraceFilter(**filter_values)
    reader = repository.get_trace_reader(run_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, suffix=".tmp", delete=False,
        ) as destination:
            temporary = Path(destination.name)
            for line in iter_jsonl(run, reader, filters):
                destination.write(line)
            destination.flush()
            os.fsync(destination.fileno())
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
