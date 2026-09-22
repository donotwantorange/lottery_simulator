import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dashboard.jobs import JobManager
from dashboard.models import RunParameters
from dashboard.trace_export import export_trace, iter_jsonl
from dashboard.trace_store import TraceFilter


class TraceExportTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / "history.sqlite3"
        self.manager = JobManager(self.root / "jobs", self.database)
        self.state = self.manager.start(
            RunParameters("rule1", 2, 3, 29, 42, True), synchronous=True,
        )

    def test_iter_jsonl_has_complete_metadata_and_all_filtered_records(self):
        run = self.manager.get_result(self.state.job_id)
        reader = self.manager.get_trace_reader(self.state.job_id)
        lines = [json.loads(line) for line in iter_jsonl(
            run, reader, TraceFilter(source="main"),
        )]
        self.assertEqual(lines[0]["type"], "metadata")
        self.assertEqual(lines[0]["export_format_version"], 1)
        self.assertEqual(lines[0]["matched_record_count"], 6)
        self.assertNotIn("records", lines[0]["run"])
        self.assertEqual(len(lines), 7)
        self.assertTrue(all(line["type"] == "record" for line in lines[1:]))

    def test_export_is_atomic_refuses_overwrite_and_source_components(self):
        output = self.root / "trace.jsonl"
        export_trace(self.database, self.state.job_id, output)
        lines = output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 37)
        before = output.read_bytes()
        with self.assertRaises(FileExistsError):
            export_trace(self.database, self.state.job_id, output)
        self.assertEqual(output.read_bytes(), before)
        for suffix in ("", "-journal", "-wal", "-shm"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                export_trace(self.database, self.state.job_id, Path(str(self.database) + suffix))
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_export_rejects_missing_and_non_trace_runs(self):
        with self.assertRaises(ValueError):
            export_trace(self.database, "00000000-0000-0000-0000-000000000000",
                         self.root / "missing.jsonl")
        state = self.manager.start(
            RunParameters("rule1", 1, 1, 0, 7, False), synchronous=True,
        )
        with self.assertRaises(ValueError):
            export_trace(self.database, state.job_id, self.root / "nontrace.jsonl")

    def test_missing_source_is_never_created_by_export(self):
        missing = self.root / "missing.sqlite3"
        output = self.root / "missing.jsonl"
        with self.assertRaises((ValueError, sqlite3.Error)):
            export_trace(missing, self.state.job_id, output)
        self.assertFalse(missing.exists())
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
