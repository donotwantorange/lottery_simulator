from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
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
