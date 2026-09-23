from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from dashboard.limits import TraceLimits
from dashboard.models import result_payload
from dashboard.repository import HistoryRepository
from dashboard.trace_store import TraceWriter
from lottery_simulator.engine import SimulationCancelled, simulate
from lottery_simulator.formats import RESULT_FORMAT_VERSION, SAMPLING_VERSION
from lottery_simulator.rules.rule_1 import Rule1


class HistoryRepositoryTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "history.sqlite3"
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA user_version = 0")
        self.repository = HistoryRepository(self.path)
        self.repository.initialize()
        self.run_id = str(uuid4())
        self.payload, self.trace_path = self.snapshot(draws=12)

    def snapshot(self, *, draws=12, trials=1, initial_pity=0, trace=True, name=None):
        rule = Rule1()
        trace_path = self.path.with_name(name or f"trace-{uuid4()}.sqlite3") if trace else None
        writer = (TraceWriter(trace_path, limits=TraceLimits(batch_size=5, max_records=10_000))
                  if trace else None)
        try:
            result = simulate(
                rule, draws, trials=trials, initial_pity=initial_pity, seed=42,
                collect_records=trace, record_sink=writer.append if writer else None,
            )
            if writer:
                writer.finish(
                    trials=trials, draws=draws, initial_main_draws=initial_pity,
                    bonus_per_trial=result.bonus_draws,
                )
            return result_payload(result, rule, 0.25), trace_path
        finally:
            if writer:
                writer.close()

    def counts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                         for table in ("simulation_runs", "draw_records"))

    def test_initialize_empty_version_zero_and_repeat_preserves_run(self):
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(
                [row[1] for row in connection.execute("PRAGMA table_info(simulation_runs)")],
                [
                    "id", "created_at", "rule_name", "rule_version", "main_draws", "trials",
                    "initial_pity", "initial_five_star_pity", "seed", "trace_enabled",
                    "record_count", "pool_config_json", "result_json", "schema_version",
                ],
            )
            self.assertEqual(
                [row[1] for row in connection.execute("PRAGMA table_info(draw_records)")],
                ["run_id", "trial_index", "draw_index", "source", "source_index",
                 "rarity", "character_name", "record_json"],
            )
            indexes = [tuple(row) for row in connection.execute(
                "PRAGMA index_info(draw_records_run_source_position_rarity)"
            )]
            self.assertEqual(indexes, [(0, 0, "run_id"), (1, 3, "source"),
                                       (2, 4, "source_index"), (3, 5, "rarity")])
        run_id = self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        self.repository.initialize()
        self.assertEqual(self.repository.get_run(run_id)["seed"], 42)

    def assert_initialize_rejected_without_changes(self, path, version):
        before = path.read_bytes()
        with closing(sqlite3.connect(path)) as connection:
            semantic_before = list(connection.iterdump())
        with self.assertRaisesRegex(ValueError, "版本不兼容"):
            HistoryRepository(path).initialize()
        self.assertEqual(path.read_bytes(), before)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], version)
            self.assertEqual(list(connection.iterdump()), semantic_before)

    def test_initialize_rejects_old_schema_without_modifying_it(self):
        path = self.path.with_name("old.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE legacy_marker(value TEXT)")
            connection.execute("INSERT INTO legacy_marker VALUES ('keep')")
            connection.execute("PRAGMA user_version = 1")
        self.assert_initialize_rejected_without_changes(path, 1)

    def test_initialize_rejects_nonempty_version_zero_without_modifying_it(self):
        path = self.path.with_name("unversioned.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE legacy_marker(value TEXT)")
            connection.execute("INSERT INTO legacy_marker VALUES ('keep')")
        self.assert_initialize_rejected_without_changes(path, 0)

    def test_initialize_rejects_v2_without_modifying_it(self):
        path = self.path.with_name("v2.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE legacy_marker(value TEXT)")
            connection.execute("INSERT INTO legacy_marker VALUES ('keep')")
            connection.execute("PRAGMA user_version = 2")
        self.assert_initialize_rejected_without_changes(path, 2)

    def test_initialize_rejects_version_zero_view_without_modifying_it(self):
        path = self.path.with_name("view-only.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE VIEW legacy_marker AS SELECT 'keep' AS value")
        before = path.read_bytes()

        error = None
        try:
            HistoryRepository(path).initialize()
        except Exception as caught:
            error = caught
        after = path.read_bytes()
        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            objects = [tuple(row) for row in connection.execute(
                "SELECT type, name FROM sqlite_master "
                "WHERE name NOT GLOB 'sqlite_*' ORDER BY type, name"
            )]
            value = connection.execute("SELECT value FROM legacy_marker").fetchone()[0]

        self.assertEqual(
            {
                "error_type": type(error).__name__ if error is not None else None,
                "chinese_error": error is not None and "版本不兼容" in str(error),
                "version": version,
                "objects": objects,
                "view_value": value,
                "bytes_unchanged": after == before,
            },
            {
                "error_type": "ValueError",
                "chinese_error": True,
                "version": 0,
                "objects": [("view", "legacy_marker")],
                "view_value": "keep",
                "bytes_unchanged": True,
            },
        )

    def test_initialize_rejects_old_wal_schema_without_checkpointing(self):
        path = self.path.with_name("old-wal.sqlite3")
        child = subprocess.run(
            [sys.executable, "-c", """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("PRAGMA wal_autocheckpoint=0")
connection.execute("CREATE TABLE legacy_marker(value TEXT)")
connection.execute("INSERT INTO legacy_marker VALUES ('keep')")
connection.execute("PRAGMA user_version=1")
connection.commit()
os._exit(17)
""", str(path)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(child.returncode, 17, child.stdout + child.stderr)
        files = {
            "database": path,
            "wal": Path(str(path) + "-wal"),
            "shm": Path(str(path) + "-shm"),
        }
        self.assertTrue(all(file.is_file() for file in files.values()))
        before = {name: file.read_bytes() for name, file in files.items()}

        error = None
        try:
            HistoryRepository(path).initialize()
        except Exception as caught:
            error = caught
        file_state = {
            name: (file.is_file(), file.is_file() and file.read_bytes() == before[name])
            for name, file in files.items()
        }
        with TemporaryDirectory() as directory:
            snapshot = Path(directory) / path.name
            for name, file in files.items():
                if file.is_file():
                    suffix = "" if name == "database" else f"-{name}"
                    shutil.copyfile(file, Path(str(snapshot) + suffix))
            uri = snapshot.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                value = connection.execute("SELECT value FROM legacy_marker").fetchone()[0]

        self.assertEqual(
            {
                "error_type": type(error).__name__ if error is not None else None,
                "chinese_error": error is not None and "版本不兼容" in str(error),
                "files": file_state,
                "version": version,
                "value": value,
            },
            {
                "error_type": "ValueError",
                "chinese_error": True,
                "files": {
                    "database": (True, True),
                    "wal": (True, True),
                    "shm": (True, True),
                },
                "version": 1,
                "value": "keep",
            },
        )

    def test_initialize_rejects_closed_wal_schema_without_creating_sidecars(self):
        path = self.path.with_name("closed-wal.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE legacy_marker(value TEXT)")
            connection.execute("INSERT INTO legacy_marker VALUES ('keep')")
            connection.execute("PRAGMA user_version=1")
        files = {
            "database": path,
            "wal": Path(str(path) + "-wal"),
            "shm": Path(str(path) + "-shm"),
        }
        before = {
            name: (file.is_file(), file.read_bytes() if file.is_file() else None)
            for name, file in files.items()
        }
        self.assertEqual(
            {name: exists for name, (exists, _) in before.items()},
            {"database": True, "wal": False, "shm": False},
        )

        error = None
        try:
            HistoryRepository(path).initialize()
        except Exception as caught:
            error = caught
        after = {
            name: (file.is_file(), file.read_bytes() if file.is_file() else None)
            for name, file in files.items()
        }
        with TemporaryDirectory() as directory:
            snapshot = Path(directory) / path.name
            shutil.copyfile(path, snapshot)
            with closing(sqlite3.connect(snapshot)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                value = connection.execute("SELECT value FROM legacy_marker").fetchone()[0]

        self.assertEqual(
            {
                "error_type": type(error).__name__ if error is not None else None,
                "chinese_error": error is not None and "版本不兼容" in str(error),
                "files_unchanged": after == before,
                "after_exists": {name: exists for name, (exists, _) in after.items()},
                "version": version,
                "value": value,
            },
            {
                "error_type": "ValueError",
                "chinese_error": True,
                "files_unchanged": True,
                "after_exists": {"database": True, "wal": False, "shm": False},
                "version": 1,
                "value": "keep",
            },
        )

    def test_initialize_rejects_wal_checkpoint_race_without_modifying_source(self):
        path = self.path.with_name("racing-wal.sqlite3")
        files = {
            "database": path,
            "wal": Path(str(path) + "-wal"),
            "shm": Path(str(path) + "-shm"),
        }
        original_copyfile = shutil.copyfile
        writer_settled = None
        with closing(sqlite3.connect(path)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE legacy_marker(value TEXT)")
            writer.execute("INSERT INTO legacy_marker VALUES ('before')")
            writer.execute("PRAGMA user_version=1")
            writer.commit()

            def copy_with_checkpoint(source, destination, *args, **kwargs):
                nonlocal writer_settled
                result = original_copyfile(source, destination, *args, **kwargs)
                if Path(source) == path and writer_settled is None:
                    checkpoint = writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    self.assertEqual(checkpoint[0], 0)
                    writer.execute("INSERT INTO legacy_marker VALUES ('after')")
                    writer.commit()
                    writer_settled = {
                        name: file.read_bytes() for name, file in files.items()
                    }
                return result

            error = None
            with patch("dashboard.repository.shutil.copyfile", side_effect=copy_with_checkpoint):
                try:
                    HistoryRepository(path).initialize()
                except Exception as caught:
                    error = caught

            after = {name: file.read_bytes() for name, file in files.items()}
            version = writer.execute("PRAGMA user_version").fetchone()[0]
            values = [row[0] for row in writer.execute(
                "SELECT value FROM legacy_marker ORDER BY rowid"
            )]

        self.assertIsNotNone(writer_settled)
        self.assertEqual(
            {
                "error_type": type(error).__name__ if error is not None else None,
                "chinese_error": error is not None and "版本不兼容" in str(error),
                "source_unchanged_after_writer_commit": after == writer_settled,
                "version": version,
                "values": values,
            },
            {
                "error_type": "ValueError",
                "chinese_error": True,
                "source_unchanged_after_writer_commit": True,
                "version": 1,
                "values": ["before", "after"],
            },
        )

    def test_initialize_rejects_hot_rollback_journal_by_recovered_schema(self):
        path = self.path.with_name("hot-journal.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("CREATE TABLE legacy_marker(value TEXT)")
            connection.execute("INSERT INTO legacy_marker VALUES ('keep')")
            connection.execute("CREATE TABLE filler(payload TEXT)")
            connection.execute("PRAGMA user_version=1")
        child = subprocess.run(
            [sys.executable, "-c", """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA journal_mode=DELETE")
connection.execute("PRAGMA synchronous=FULL")
connection.execute("PRAGMA cache_size=1")
connection.execute("BEGIN IMMEDIATE")
connection.execute("PRAGMA user_version=2")
connection.execute("UPDATE legacy_marker SET value='changed'")
for _ in range(100):
    connection.execute("INSERT INTO filler(payload) VALUES (?)", ("x" * 8000,))
os._exit(19)
""", str(path)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(child.returncode, 19, child.stdout + child.stderr)
        journal = Path(str(path) + "-journal")
        self.assertGreater(journal.stat().st_size, 512)
        # Model an interrupted page-one write while retaining SQLite's real hot journal.
        with path.open("r+b") as database:
            database.seek(60)
            database.write(struct.pack(">I", 2))
            database.flush()
            os.fsync(database.fileno())
        self.assertEqual(struct.unpack(">I", path.read_bytes()[60:64])[0], 2)

        files = {
            "database": path,
            "journal": journal,
            "wal": Path(str(path) + "-wal"),
            "shm": Path(str(path) + "-shm"),
        }
        before = {
            name: (file.is_file(), file.read_bytes() if file.is_file() else None)
            for name, file in files.items()
        }
        self.assertEqual(
            {name: exists for name, (exists, _) in before.items()},
            {"database": True, "journal": True, "wal": False, "shm": False},
        )

        def recovered_semantics():
            with TemporaryDirectory() as directory:
                snapshot = Path(directory) / path.name
                shutil.copyfile(path, snapshot)
                shutil.copyfile(journal, Path(str(snapshot) + "-journal"))
                with closing(sqlite3.connect(snapshot)) as connection:
                    return (
                        connection.execute("PRAGMA user_version").fetchone()[0],
                        connection.execute("SELECT value FROM legacy_marker").fetchone()[0],
                        connection.execute("PRAGMA integrity_check").fetchone()[0],
                    )

        self.assertEqual(recovered_semantics(), (1, "keep", "ok"))
        error = None
        try:
            HistoryRepository(path).initialize()
        except Exception as caught:
            error = caught
        after = {
            name: (file.is_file(), file.read_bytes() if file.is_file() else None)
            for name, file in files.items()
        }

        self.assertEqual(
            {
                "error_type": type(error).__name__ if error is not None else None,
                "chinese_error": error is not None and "版本不兼容" in str(error),
                "rejects_recovered_version": error is not None and "当前版本 1" in str(error),
                "files_unchanged": after == before,
                "recovered_semantics": recovered_semantics(),
            },
            {
                "error_type": "ValueError",
                "chinese_error": True,
                "rejects_recovered_version": True,
                "files_unchanged": True,
                "recovered_semantics": (1, "keep", "ok"),
            },
        )

    def test_initialize_does_not_recover_stale_journal_from_rejected_snapshot(self):
        path = self.path.with_name("reused-snapshot.sqlite3")
        journal = Path(str(path) + "-journal")
        repository = HistoryRepository(path)
        original_copyfile = shutil.copyfile
        original_inspect_schema = repository._inspect_schema
        writer_committed = False
        private_inspections = []
        with closing(sqlite3.connect(path)) as writer:
            writer.execute("PRAGMA journal_mode=DELETE")
            writer.execute("PRAGMA synchronous=FULL")
            writer.execute("PRAGMA cache_size=1")
            writer.execute("PRAGMA secure_delete=ON")
            writer.execute("CREATE TABLE retired(payload TEXT)")
            writer.executemany(
                "INSERT INTO retired VALUES (?)", (("x" * 8000,) for _ in range(100))
            )
            writer.execute("PRAGMA user_version=2")
            writer.commit()
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("DROP TABLE retired")
            writer.execute("PRAGMA user_version=0")
            # Cache spills make SQLite's rollback journal recoverable in a private copy.
            self.assertEqual(journal.read_bytes()[:8], bytes.fromhex("d9d505f920a163d7"))

            def copy_then_commit(source, destination, *args, **kwargs):
                nonlocal writer_committed
                result = original_copyfile(source, destination, *args, **kwargs)
                if Path(source) == journal and not writer_committed:
                    # This candidate keeps the journal after commit removes the source copy.
                    writer.commit()
                    writer_committed = True
                    self.assertFalse(journal.exists())
                    self.assertEqual(writer.execute("PRAGMA user_version").fetchone()[0], 0)
                    self.assertEqual(writer.execute("SELECT name FROM sqlite_master").fetchall(), [])
                return result

            def inspect_snapshot(snapshot):
                self.assertNotEqual(Path(snapshot), path)
                raw_version = struct.unpack(">I", Path(snapshot).read_bytes()[60:64])[0]
                files_present = tuple(
                    Path(str(snapshot) + suffix).is_file()
                    for suffix in ("", "-journal", "-wal", "-shm")
                )
                result = original_inspect_schema(snapshot)
                private_inspections.append((raw_version, files_present, result))
                return result

            error = None
            with patch("dashboard.repository.shutil.copyfile", side_effect=copy_then_commit), \
                    patch.object(repository, "_inspect_schema", side_effect=inspect_snapshot):
                try:
                    repository.initialize()
                except Exception as caught:
                    error = caught

        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

        self.assertTrue(writer_committed)
        self.assertEqual(
            {
                "error_type": type(error).__name__ if error is not None else None,
                "private_inspections": private_inspections,
                "source_version": version,
                "source_tables": tables,
                "source_integrity": integrity,
            },
            {
                "error_type": None,
                "private_inspections": [
                    (0, (True, False, False, False), (0, False)),
                    (0, (True, False, False, False), (0, False)),
                ],
                "source_version": 4,
                "source_tables": ["draw_records", "simulation_runs"],
                "source_integrity": "ok",
            },
        )

    def test_initialize_rejects_future_version_without_changes(self):
        path = self.path.with_name("future.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("PRAGMA user_version = 5")
        self.assert_initialize_rejected_without_changes(path, 5)

    def test_v4_imports_three_trials_and_get_run_is_summary_only(self):
        payload, trace_path = self.snapshot(draws=2, trials=3, initial_pity=29)
        original = deepcopy(payload)
        before = datetime.now(timezone.utc)

        run_id = self.repository.save_run(self.run_id, payload, trace_path=trace_path)
        run = self.repository.get_run(run_id)

        self.assertEqual(str(UUID(run_id)), run_id)
        self.assertGreaterEqual(datetime.fromisoformat(run["created_at"]), before)
        self.assertEqual(run["schema_version"], 4)
        self.assertEqual(run["record_count"], 36)
        self.assertNotIn("records", run)
        self.assertEqual(payload, original)
        with self.assertRaises(TypeError):
            self.repository.get_run(run_id, include_records=True)
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT trial_index, draw_index, source, source_index, record_json "
                "FROM draw_records WHERE run_id=? ORDER BY trial_index, draw_index", (run_id,)
            ).fetchall()
        self.assertEqual(len(rows), 36)
        self.assertEqual(rows[0][:4], (1, 1, "main", 1))
        self.assertEqual(rows[12][:4], (2, 1, "main", 1))
        self.assertEqual(rows[24][:4], (3, 1, "main", 1))
        bonus = json.loads(rows[1][4])
        self.assertEqual(bonus["source"], "bonus")
        self.assertEqual(bonus["main_state_before"], bonus["main_state_after"])

    def test_save_rejects_missing_bool_and_unsupported_versions_without_inserts(self):
        for key, supported in (("result_format_version", RESULT_FORMAT_VERSION),
                               ("sampling_version", SAMPLING_VERSION)):
            for value in (None, True, "1", supported + 1):
                with self.subTest(key=key, value=value):
                    payload = deepcopy(self.payload)
                    if value is None:
                        payload.pop(key, None)
                    else:
                        payload[key] = value
                    with self.assertRaises(ValueError):
                        self.repository.save_run(str(uuid4()), payload)
                    self.assertEqual(self.counts(), (0, 0))
        for value in (None, True, "1", 2):
            payload = deepcopy(self.payload)
            if value is None:
                payload["pool_config"].pop("format_version")
            else:
                payload["pool_config"]["format_version"] = value
            with self.subTest(config_version=value), self.assertRaises(ValueError):
                self.repository.save_run(str(uuid4()), payload)
            self.assertEqual(self.counts(), (0, 0))

    def test_reject_invalid_sampling_version_before_insert(self):
        payload = deepcopy(self.payload)
        payload["sampling_version"] = True
        with self.assertRaises(ValueError):
            self.repository.save_run(str(uuid4()), payload)
        self.assertEqual(self.counts(), (0, 0))

    def test_save_rejects_invalid_rule_version_without_inserts(self):
        for value in (None, True, 2.0, "1.0", ""):
            payload = deepcopy(self.payload)
            payload["rule_version"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.repository.save_run(str(uuid4()), payload)
            self.assertEqual(self.counts(), (0, 0))

    def test_get_run_rejects_invalid_snapshot_and_config_versions(self):
        payload, _ = self.snapshot(trace=False)
        run_id = self.repository.save_run(str(uuid4()), payload)
        for key in ("result_format_version", "sampling_version", "rule_version"):
            payload = deepcopy(self.payload)
            payload.pop(key)
            with closing(sqlite3.connect(self.path)) as connection, connection:
                connection.execute("UPDATE simulation_runs SET result_json=? WHERE id=?",
                                   (json.dumps(payload), run_id))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.repository.get_run(run_id)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            config = deepcopy(self.payload["pool_config"])
            config["format_version"] = True
            connection.execute("UPDATE simulation_runs SET result_json=?, pool_config_json=? WHERE id=?",
                               (json.dumps(self.payload), json.dumps(config), run_id))
        with self.assertRaises(ValueError):
            self.repository.get_run(run_id)

    def test_non_trace_requires_zero_count_and_no_trace_path(self):
        payload, _ = self.snapshot(trace=False)
        run_id = self.repository.save_run(self.run_id, payload)
        self.assertEqual(self.counts(), (1, 0))
        run = self.repository.get_run(run_id)
        self.assertIs(run["trace_enabled"], False)
        self.assertEqual(run["record_count"], 0)
        with closing(sqlite3.connect(self.path)) as connection:
            snapshot, pool_config = connection.execute(
                "SELECT result_json, pool_config_json FROM simulation_runs"
            ).fetchone()
        self.assertNotIn("records", json.loads(snapshot))
        self.assertEqual(snapshot, json.dumps(json.loads(snapshot), sort_keys=True))
        self.assertEqual(pool_config, json.dumps(self.payload["pool_config"], sort_keys=True))
        with self.assertRaises(ValueError):
            self.repository.save_run(str(uuid4()), payload, trace_path=self.trace_path)
        changed = deepcopy(payload)
        changed["record_count"] = 1
        with self.assertRaises(ValueError):
            self.repository.save_run(str(uuid4()), changed)

    def test_seed_round_trips_unsigned_64_bit_as_decimal_text(self):
        payload, _ = self.snapshot(trace=False)
        payload["seed"] = 18_446_744_073_709_551_615
        run_id = self.repository.save_run(self.run_id, payload)
        self.assertEqual(self.repository.get_run(run_id)["seed"], 18_446_744_073_709_551_615)
        self.assertEqual(self.repository.list_runs({}, 20, 0)[0]["seed"], 18_446_744_073_709_551_615)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT seed, typeof(seed) FROM simulation_runs").fetchone(),
                             ("18446744073709551615", "text"))

    def test_trace_requires_uuid_complete_matching_metadata_and_count(self):
        for invalid in (None, True, 1, "not-a-uuid", self.run_id.upper()):
            with self.subTest(run_id=invalid), self.assertRaises(ValueError):
                self.repository.save_run(invalid, self.payload, trace_path=self.trace_path)
        with self.assertRaises(ValueError):
            self.repository.save_run(str(uuid4()), self.payload)
        with closing(sqlite3.connect(self.trace_path)) as connection, connection:
            connection.execute("UPDATE metadata SET complete=0")
        with self.assertRaises(ValueError):
            self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        self.assertEqual(self.counts(), (0, 0))

        payload, trace_path = self.snapshot(draws=2, trials=3, initial_pity=29,
                                            name="metadata.sqlite3")
        for column, value in (("trials", 2), ("draws", 3), ("initial_main_draws", 28),
                              ("bonus_per_trial", 9), ("record_count", 35)):
            with self.subTest(column=column):
                copy = trace_path.with_name(f"metadata-{column}.sqlite3")
                shutil.copyfile(trace_path, copy)
                with closing(sqlite3.connect(copy)) as connection, connection:
                    connection.execute("PRAGMA ignore_check_constraints=ON")
                    connection.execute(f"UPDATE metadata SET {column}=?", (value,))
                with self.assertRaises(ValueError):
                    self.repository.save_run(str(uuid4()), payload, trace_path=copy)
                self.assertEqual(self.counts(), (0, 0))

    def test_import_revalidates_projection_and_nested_json(self):
        cases = (("source", "bonus"), ("record_json", "{}"))
        for column, value in cases:
            with self.subTest(column=column):
                payload, trace_path = self.snapshot(name=f"invalid-{column}.sqlite3")
                with closing(sqlite3.connect(trace_path)) as connection, connection:
                    connection.execute("PRAGMA ignore_check_constraints=ON")
                    connection.execute(f"UPDATE records SET {column}=? WHERE draw_index=1", (value,))
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    self.repository.save_run(str(uuid4()), payload, trace_path=trace_path)
                self.assertEqual(self.counts(), (0, 0))

    def test_second_import_batch_failure_rolls_back_summary_and_records(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript("""
                CREATE TRIGGER abort_second_record BEFORE INSERT ON draw_records
                WHEN NEW.draw_index = 3
                BEGIN SELECT RAISE(ABORT, 'second record rejected'); END;
            """)
        with patch("dashboard.repository._IMPORT_BATCH_SIZE", 2), \
                self.assertRaisesRegex(sqlite3.IntegrityError, "second record rejected"):
            self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        self.assertEqual(self.counts(), (0, 0))

    def test_cancel_and_commit_guard_failures_roll_back_everything(self):
        calls = []

        def cancel_on_second_batch():
            calls.append("cancel")
            return len(calls) == 2

        with patch("dashboard.repository._IMPORT_BATCH_SIZE", 2), \
                self.assertRaises(SimulationCancelled):
            self.repository.save_run(
                self.run_id, self.payload, trace_path=self.trace_path,
                cancel_check=cancel_on_second_batch,
            )
        self.assertEqual(self.counts(), (0, 0))

        final_checks = 0

        def cancel_before_commit():
            nonlocal final_checks
            final_checks += 1
            return final_checks == 2

        with self.assertRaises(SimulationCancelled):
            self.repository.save_run(
                self.run_id, self.payload, trace_path=self.trace_path,
                cancel_check=cancel_before_commit,
            )
        self.assertEqual(final_checks, 2)
        self.assertEqual(self.counts(), (0, 0))

        @contextmanager
        def failing_guard():
            calls.append("guard")
            raise RuntimeError("guard failed")
            yield

        with self.assertRaisesRegex(RuntimeError, "guard failed"):
            self.repository.save_run(
                self.run_id, self.payload, trace_path=self.trace_path,
                cancel_check=lambda: False, commit_guard=failing_guard,
            )
        self.assertEqual(calls[-1], "guard")
        self.assertEqual(self.counts(), (0, 0))

    def test_import_progress_includes_bonus_and_never_means_committed(self):
        payload, trace_path = self.snapshot(draws=2, initial_pity=29)
        progress = []

        def report_progress(completed, total):
            if completed == total:
                with closing(sqlite3.connect(self.path)) as observer:
                    self.assertEqual(observer.execute(
                        "SELECT count(*) FROM simulation_runs"
                    ).fetchone()[0], 0)
            progress.append((completed, total))

        with patch("dashboard.repository._IMPORT_BATCH_SIZE", 5):
            self.repository.save_run(
                self.run_id, payload, trace_path=trace_path,
                progress_callback=report_progress,
            )
        self.assertEqual(progress, [(0, 12), (5, 12), (10, 12), (12, 12)])
        self.assertEqual(self.counts(), (1, 12))

    def test_import_cancellation_and_progress_failure_roll_back_everything(self):
        payload, trace_path = self.snapshot(draws=2, initial_pity=29)

        calls = 0

        def cancel_during_import():
            nonlocal calls
            calls += 1
            return calls == 2

        with patch("dashboard.repository._IMPORT_BATCH_SIZE", 5), \
                self.assertRaises(SimulationCancelled):
            self.repository.save_run(
                self.run_id, payload, trace_path=trace_path,
                cancel_check=cancel_during_import,
            )
        self.assertEqual(self.counts(), (0, 0))

        cancel_requested = False

        def cancel_before_commit(completed, total):
            nonlocal cancel_requested
            if completed == total:
                cancel_requested = True

        with patch("dashboard.repository._IMPORT_BATCH_SIZE", 5), \
                self.assertRaises(SimulationCancelled):
            self.repository.save_run(
                str(uuid4()), payload, trace_path=trace_path,
                cancel_check=lambda: cancel_requested,
                progress_callback=cancel_before_commit,
            )
        self.assertEqual(self.counts(), (0, 0))

        def fail_on_first_batch(completed, total):
            if completed == 5:
                raise RuntimeError("progress failed")

        with patch("dashboard.repository._IMPORT_BATCH_SIZE", 5), \
                self.assertRaisesRegex(RuntimeError, "progress failed"):
            self.repository.save_run(
                str(uuid4()), payload, trace_path=trace_path,
                progress_callback=fail_on_first_batch,
            )
        self.assertEqual(self.counts(), (0, 0))

    def test_commit_guard_contains_final_cancel_check_and_commit(self):
        events = []

        def not_cancelled():
            events.append("cancel")
            return False

        @contextmanager
        def guard():
            events.append("guard-enter")
            yield
            with closing(sqlite3.connect(self.path)) as observer:
                events.append(("visible-before-guard-exit", observer.execute(
                    "SELECT count(*) FROM simulation_runs"
                ).fetchone()[0]))
            events.append("guard-exit")

        self.repository.save_run(
            self.run_id, self.payload, trace_path=self.trace_path,
            cancel_check=not_cancelled, commit_guard=guard,
        )
        self.assertEqual(events[-4:], ["guard-enter", "cancel",
                                      ("visible-before-guard-exit", 1), "guard-exit"])

    def test_same_id_is_idempotent_and_conflicting_snapshot_is_rejected(self):
        first = self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        second = self.repository.save_run(self.run_id, deepcopy(self.payload),
                                          trace_path=self.trace_path)
        self.assertEqual((first, second), (self.run_id, self.run_id))
        self.assertEqual(self.counts(), (1, 12))

        changed = deepcopy(self.payload)
        changed["duration_seconds"] += 1
        with self.assertRaises(ValueError):
            self.repository.save_run(self.run_id, changed, trace_path=self.trace_path)
        self.assertEqual(self.counts(), (1, 12))

        other = str(uuid4())
        self.assertEqual(self.repository.save_run(other, self.payload, trace_path=self.trace_path),
                         other)
        self.assertEqual(self.counts(), (2, 24))

    def test_operations_reject_old_schema_independent_of_filename(self):
        self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("PRAGMA user_version=3")
        before = self.path.read_bytes()
        for operation in (
            lambda: self.repository.get_run(self.run_id),
            lambda: self.repository.list_runs({}, 20, 0),
            lambda: self.repository.save_run(str(uuid4()), self.payload,
                                             trace_path=self.trace_path),
            lambda: self.repository.delete_run(self.run_id),
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "版本不兼容"):
                operation()
        self.assertEqual(self.path.read_bytes(), before)

    def test_delete_cascades_and_missing_run_is_empty(self):
        run_id = self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        self.repository.delete_run(run_id)
        self.assertIsNone(self.repository.get_run(run_id))
        self.assertEqual(self.counts(), (0, 0))
        self.repository.delete_run(run_id)

    def test_delete_failure_keeps_summary_and_records(self):
        run_id = self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript("""
                CREATE TRIGGER abort_record_delete BEFORE DELETE ON draw_records
                BEGIN SELECT RAISE(ABORT, 'delete rejected'); END;
            """)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "delete rejected"):
            self.repository.delete_run(run_id)
        self.assertEqual(self.counts(), (1, 12))

    def test_filters_sort_and_pagination(self):
        first = self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        archived, _ = self.snapshot(trace=False)
        archived["rule_name"] = "archived-rule"
        second = self.repository.save_run(str(uuid4()), archived)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE simulation_runs SET created_at=? WHERE id=?",
                               ("2026-01-01T00:00:00+00:00", first))
            connection.execute("UPDATE simulation_runs SET created_at=? WHERE id=?",
                               ("2026-02-01T00:00:00+00:00", second))
        self.assertEqual([run["id"] for run in self.repository.list_runs({}, 20, 0)], [second, first])
        self.assertEqual(self.repository.list_runs({}, 1, 1)[0]["id"], first)
        self.assertEqual(self.repository.list_runs({}, 1, 2), [])
        for filters, expected in (
            ({"trace_enabled": True}, first),
            ({"trace_enabled": False}, second),
            ({"rule_name": "archived-rule"}, second),
            ({"created_from": "2026-02-01T00:00:00+00:00"}, second),
            ({"created_to": "2026-01-01T00:00:00+00:00"}, first),
            ({"rule_name": "archived-rule", "trace_enabled": False}, second),
        ):
            with self.subTest(filters=filters):
                rows = self.repository.list_runs(filters, 20, 0)
                self.assertEqual([row["id"] for row in rows], [expected])
                self.assertNotIn("records", rows[0])

    def test_filters_and_pagination_reject_untrusted_inputs(self):
        payload, _ = self.snapshot(trace=False)
        self.repository.save_run(self.run_id, payload)
        for limit, offset in ((0, 0), (101, 0), (20, -1), (True, 0), (20, False), (1.5, 0), (20, "0")):
            with self.subTest(limit=limit, offset=offset), self.assertRaises(ValueError):
                self.repository.list_runs({}, limit, offset)
        with self.assertRaises(ValueError):
            self.repository.list_runs({"id OR 1=1 --": "x"}, 20, 0)
        self.assertEqual(self.repository.list_runs({"rule_name": "' OR 1=1 --"}, 20, 0), [])
        self.assertEqual(self.counts(), (1, 0))

    def test_backup_contains_queryable_summary_and_trace(self):
        run_id = self.repository.save_run(self.run_id, self.payload, trace_path=self.trace_path)
        backup_path = self.path.with_name("backup.sqlite3")
        self.repository.backup_to(backup_path)
        backup = HistoryRepository(backup_path)
        backup.initialize()
        self.assertEqual(backup.get_run(run_id), self.repository.get_run(run_id))
        self.repository.delete_run(run_id)
        with closing(sqlite3.connect(backup_path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM draw_records WHERE run_id=?", (run_id,)
            ).fetchone()[0], 12)


if __name__ == "__main__":
    unittest.main()
