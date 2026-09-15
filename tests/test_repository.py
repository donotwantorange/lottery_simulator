from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID

from dashboard.models import result_payload
from dashboard.repository import HistoryRepository
from lottery_simulator.engine import simulate
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
        rule = Rule1()
        self.payload = result_payload(simulate(rule, 12, seed=42), rule, 0.25)

    def counts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                         for table in ("simulation_runs", "draw_records"))

    def test_initialize_empty_version_zero_and_repeat_preserves_run(self):
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(
                [row[1] for row in connection.execute("PRAGMA table_info(simulation_runs)")],
                [
                    "id", "created_at", "rule_name", "rule_version", "main_draws", "trials",
                    "initial_pity", "initial_five_star_pity", "seed", "trace_enabled",
                    "pool_config_json", "result_json", "schema_version",
                ],
            )
            self.assertEqual(
                [row[1] for row in connection.execute("PRAGMA table_info(draw_records)")],
                ["run_id", "draw_index", "record_json"],
            )
        run_id = self.repository.save_run(self.payload, trace_enabled=True)
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

    def test_initialize_rejects_future_version_without_changes(self):
        path = self.path.with_name("future.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("PRAGMA user_version = 3")
        self.assert_initialize_rejected_without_changes(path, 3)

    def test_v2_round_trip_preserves_config_summary_and_trace(self):
        original = deepcopy(self.payload)
        run_id = self.repository.save_run(self.payload, trace_enabled=True)
        run = self.repository.get_run(run_id, include_records=True)
        self.assertEqual(run["pool_config"], original["pool_config"])
        self.assertEqual(run["records"], original["records"])
        self.assertEqual(run["initial_five_star_pity"], original["initial_five_star_pity"])
        self.assertEqual(run["schema_version"], 2)

    def test_save_and_read_trace_preserve_payload_and_metadata(self):
        original = deepcopy(self.payload)
        before = datetime.now(timezone.utc)
        run_id = self.repository.save_run(self.payload, trace_enabled=True)
        run = self.repository.get_run(run_id, include_records=True)
        self.assertEqual(str(UUID(run_id)), run_id)
        self.assertGreaterEqual(datetime.fromisoformat(run["created_at"]), before)
        self.assertEqual(run["schema_version"], 2)
        self.assertIs(run["trace_enabled"], True)
        for key, value in original.items():
            self.assertEqual(run[key], value, key)
        self.assertEqual(len(run["records"]), 12)
        self.assertIsInstance(run["records"][0]["is_six_star"], bool)
        self.assertNotIn("records", self.repository.get_run(run_id))
        self.assertEqual(self.payload, original)

    def test_bonus_trace_round_trips_nested_state(self):
        rule = Rule1()
        payload = result_payload(simulate(rule, 2, seed=42, initial_pity=29), rule, 0.1)
        run_id = self.repository.save_run(payload, trace_enabled=True)
        records = self.repository.get_run(run_id, include_records=True)["records"]
        self.assertEqual(len(records), 12)
        self.assertEqual(records, payload["records"])
        self.assertEqual(records[1]["source"], "bonus")

    def test_non_trace_saves_no_records_even_in_snapshot(self):
        run_id = self.repository.save_run(self.payload, trace_enabled=False)
        self.assertEqual(self.counts(), (1, 0))
        run = self.repository.get_run(run_id, include_records=True)
        self.assertEqual(run["records"], [])
        self.assertIs(run["trace_enabled"], False)
        with closing(sqlite3.connect(self.path)) as connection:
            snapshot, pool_config = connection.execute(
                "SELECT result_json, pool_config_json FROM simulation_runs"
            ).fetchone()
        self.assertNotIn("records", json.loads(snapshot))
        self.assertEqual(snapshot, json.dumps(json.loads(snapshot), sort_keys=True))
        self.assertEqual(pool_config, json.dumps(self.payload["pool_config"], sort_keys=True))

    def test_seed_round_trips_unsigned_64_bit_as_decimal_text(self):
        self.payload["seed"] = 18_446_744_073_709_551_615
        run_id = self.repository.save_run(self.payload, trace_enabled=False)
        self.assertEqual(self.repository.get_run(run_id)["seed"], 18_446_744_073_709_551_615)
        self.assertEqual(self.repository.list_runs({}, 20, 0)[0]["seed"], 18_446_744_073_709_551_615)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT seed, typeof(seed) FROM simulation_runs").fetchone(),
                             ("18446744073709551615", "text"))

    def test_second_trace_insert_failure_rolls_back_summary_and_records(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript("""
                CREATE TRIGGER abort_second_record BEFORE INSERT ON draw_records
                WHEN NEW.draw_index = 2
                BEGIN SELECT RAISE(ABORT, 'second record rejected'); END;
            """)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "second record rejected"):
            self.repository.save_run(self.payload, trace_enabled=True)
        self.assertEqual(self.counts(), (0, 0))
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TRIGGER abort_second_record")
        self.repository.save_run(self.payload, trace_enabled=True)
        self.assertEqual(self.counts(), (1, 12))

    def test_delete_cascades_and_missing_run_is_empty(self):
        run_id = self.repository.save_run(self.payload, trace_enabled=True)
        self.repository.delete_run(run_id)
        self.assertIsNone(self.repository.get_run(run_id))
        self.assertEqual(self.counts(), (0, 0))
        self.repository.delete_run(run_id)

    def test_delete_failure_keeps_summary_and_records(self):
        run_id = self.repository.save_run(self.payload, trace_enabled=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript("""
                CREATE TRIGGER abort_record_delete BEFORE DELETE ON draw_records
                BEGIN SELECT RAISE(ABORT, 'delete rejected'); END;
            """)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "delete rejected"):
            self.repository.delete_run(run_id)
        self.assertEqual(self.counts(), (1, 12))

    def test_filters_sort_and_pagination(self):
        first = self.repository.save_run(self.payload, trace_enabled=True)
        self.payload["rule_name"] = "archived-rule"
        second = self.repository.save_run(self.payload, trace_enabled=False)
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
        self.repository.save_run(self.payload, trace_enabled=False)
        for limit, offset in ((0, 0), (101, 0), (20, -1), (True, 0), (20, False), (1.5, 0), (20, "0")):
            with self.subTest(limit=limit, offset=offset), self.assertRaises(ValueError):
                self.repository.list_runs({}, limit, offset)
        with self.assertRaises(ValueError):
            self.repository.list_runs({"id OR 1=1 --": "x"}, 20, 0)
        self.assertEqual(self.repository.list_runs({"rule_name": "' OR 1=1 --"}, 20, 0), [])
        self.assertEqual(self.counts(), (1, 0))

    def test_backup_contains_queryable_summary_and_trace(self):
        run_id = self.repository.save_run(self.payload, trace_enabled=True)
        backup_path = self.path.with_name("backup.sqlite3")
        self.repository.backup_to(backup_path)
        backup = HistoryRepository(backup_path)
        backup.initialize()
        self.assertEqual(backup.get_run(run_id, include_records=True),
                         self.repository.get_run(run_id, include_records=True))
        self.repository.delete_run(run_id)
        self.assertEqual(len(backup.get_run(run_id, include_records=True)["records"]), 12)


if __name__ == "__main__":
    unittest.main()
