from contextlib import closing
from copy import deepcopy
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dashboard.limits import TraceLimits
from lottery_simulator.engine import SimulationCancelled, simulate
from lottery_simulator.rules.rule_1 import Rule1


class TraceStoreTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("dashboard.trace_store"),
                             "TraceWriter and shared record validator are missing")
        from dashboard.trace_store import TraceWriter, validate_record
        self.writer_class = TraceWriter
        self.validate = validate_record
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "trace.sqlite3"

    def writer(self, **limits):
        writer = self.writer_class(self.path, limits=TraceLimits(**limits))
        self.addCleanup(writer.close)
        return writer

    def records(self, draws=5, trials=1, initial=0):
        return simulate(Rule1(), draws, trials=trials, seed=42,
                        initial_pity=initial, collect_records=True).records

    def metadata(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            return dict(connection.execute("SELECT * FROM metadata").fetchone())

    def count(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute("SELECT count(*) FROM records").fetchone()[0]

    def test_batches_flush_tail_and_publish_metadata(self):
        writer = self.writer(batch_size=2)
        self.assertEqual(self.metadata()["complete"], 0)
        records = self.records()
        for index, record in enumerate(records, 1):
            writer.append(record)
            self.assertEqual(self.count(), index - index % 2)
        writer.finish(trials=1, draws=5, initial_main_draws=0, bonus_per_trial=0)
        self.assertEqual(self.count(), 5)
        metadata = self.metadata()
        self.assertEqual({key: metadata[key] for key in (
            "format_version", "complete", "record_count", "trials", "draws",
            "initial_main_draws", "bonus_per_trial")}, {
                "format_version": 1, "complete": 1, "record_count": 5,
                "trials": 1, "draws": 5, "initial_main_draws": 0,
                "bonus_per_trial": 0})
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("SELECT trial_index, draw_index, source, source_index, "
                                      "rarity, character_name, record_json FROM records "
                                      "ORDER BY trial_index, draw_index")
            for row, original in zip(rows, records, strict=True):
                self.assertEqual(json.loads(row[-1]), asdict(original))
                self.assertEqual(row[:-1], (1, original.draw_index, "main",
                    original.source_index, original.draw_result.outcome.rarity,
                    original.draw_result.outcome.character_name))

    def test_multiple_trials_and_bonus_states_are_accepted(self):
        writer = self.writer(batch_size=2)
        for record in reversed(self.records(draws=2, trials=3, initial=29)):
            writer.append(record)
        writer.finish(trials=3, draws=2, initial_main_draws=29, bonus_per_trial=10)
        self.assertEqual(self.metadata()["record_count"], 36)
        self.assertEqual(self.metadata()["complete"], 1)

    def test_limit_rejects_before_flushing_or_buffering_extra_record(self):
        writer = self.writer(batch_size=2, max_records=5)
        records = self.records(draws=6)
        for record in records[:5]:
            writer.append(record)
        with self.assertRaises(ValueError):
            writer.append(records[5])
        self.assertEqual(self.count(), 4)
        writer.finish(trials=1, draws=5, initial_main_draws=0, bonus_per_trial=0)
        self.assertEqual(self.count(), 5)

    def test_duplicate_batch_rolls_back_and_cannot_publish(self):
        writer = self.writer(batch_size=2)
        record = self.records(draws=1)[0]
        writer.append(record)
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            writer.append(record)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.metadata()["complete"], 0)
        with self.assertRaises((ValueError, RuntimeError, sqlite3.IntegrityError)):
            writer.finish(trials=1, draws=1, initial_main_draws=0, bonus_per_trial=0)
        self.assertEqual(self.metadata()["complete"], 0)

    def test_gaps_missing_trials_and_wrong_source_counts_cannot_publish(self):
        original = self.records(draws=2, trials=2)
        cases = (
            (original[:1] + original[2:], 2, 2, 0),
            (original[2:], 2, 2, 0),
            (original[:2], 2, 2, 0),
            (original[:2], 1, 2, 1),
            ((original[1],), 1, 1, 0),
            ((replace(original[0], source_index=2), original[1]), 1, 2, 0),
            ((replace(original[0], main_draws_completed=2), original[1]), 1, 2, 0),
        )
        for index, (records, trials, draws, bonus) in enumerate(cases):
            with self.subTest(case=index):
                self.path = self.path.with_name(f"invalid-{index}.sqlite3")
                writer = self.writer(batch_size=2)
                for record in records:
                    writer.append(record)
                with self.assertRaises(ValueError):
                    writer.finish(trials=trials, draws=draws,
                                  initial_main_draws=0, bonus_per_trial=bonus)
                self.assertEqual(self.metadata()["complete"], 0)

    def test_finish_rejects_main_and_bonus_state_semantic_errors(self):
        original = self.records(draws=2, initial=29)
        main, bonus = original[:2]
        cases = (
            (0, replace(main, bonus_event="invalid")),
            (0, replace(main, main_state_after=main.main_state_before)),
            (1, replace(bonus, bonus_event=None)),
            (1, replace(bonus, main_state_after=main.main_state_before)),
            (1, replace(bonus, main_state_before=main.main_state_before,
                        main_state_after=main.main_state_before)),
            (1, replace(bonus, source_index=2)),
        )
        for index, (position, replacement) in enumerate(cases):
            with self.subTest(case=index):
                self.path = self.path.with_name(f"state-{index}.sqlite3")
                writer = self.writer()
                records = list(original)
                records[position] = replacement
                for record in records:
                    writer.append(record)
                with self.assertRaises(ValueError):
                    writer.finish(trials=1, draws=2,
                                  initial_main_draws=29, bonus_per_trial=10)
                self.assertEqual(self.metadata()["complete"], 0)

    def test_shared_validator_preserves_nested_checks_and_rejects_bool_integers(self):
        record = asdict(self.records(draws=1)[0])
        self.validate(record=record)
        changes = (
            (("trial_index",), True), (("trial_index",), 0),
            (("record_format_version",), 1), (("record_format_version",), True),
            (("draw_index",), True), (("source_index",), True),
            (("main_draws_completed",), True), (("source",), "other"),
            (("bonus_event",), 1), (("main_state_before",), None),
            (("main_state_after", "misses_since_six_star"), True),
            (("draw_result", "state_before", "misses_since_five_or_higher"), -1),
            (("draw_result", "state_after", "misses_since_six_star"), True),
            (("draw_result", "probabilities", "four_star"), float("nan")),
            (("draw_result", "probabilities", "five_star"), float("inf")),
            (("draw_result", "probabilities", "six_star"), True),
            (("draw_result", "outcome", "rarity"), True),
            (("draw_result", "outcome", "character_name"), 4),
            (("draw_result", "outcome", "is_up"), 1),
            (("draw_result", "outcome", "is_limited"), None),
            (("draw_result", "outcome", "five_star_pity_triggered"), "False"),
            (("draw_result", "outcome", "six_star_hard_pity_triggered"), 0),
            (("draw_result", "outcome", "rewards"), {"x": True}),
            (("draw_result", "outcome", "rewards"), {"": 1}),
        )
        for path, value in changes:
            with self.subTest(path=path, value=value):
                changed = deepcopy(record)
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError):
                    self.validate(changed)

    def test_append_rejects_invalid_record_before_database_write(self):
        writer = self.writer(batch_size=1)
        record = self.records(draws=1)[0]
        for key in ("trial_index", "draw_index", "source_index", "main_draws_completed"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                writer.append(replace(record, **{key: True}))
        self.assertEqual(self.count(), 0)

    def test_sql_checks_reject_invalid_columns_and_json_integer_types(self):
        writer = self.writer(batch_size=1)
        writer.append(self.records(draws=1)[0])
        with closing(sqlite3.connect(self.path)) as connection:
            changes = (
                ("trial_index", 0), ("draw_index", 0), ("source_index", 0),
                ("trial_index", 2), ("draw_index", 2), ("source_index", 2),
                ("source", "bonus"), ("character_name", "wrong projection"),
                ("source", "unknown"), ("rarity", 7), ("record_json", "{}"),
                ("record_json", "not json"),
            )
            for column, value in changes:
                with self.subTest(column=column, value=value), self.assertRaises(sqlite3.Error):
                    connection.execute(f"UPDATE records SET {column}=?", (value,))
                connection.rollback()
            original = asdict(self.records(draws=1)[0])
            for key in ("trial_index", "draw_index", "source_index",
                        "main_draws_completed", "record_format_version"):
                for invalid in (True, None):
                    value = deepcopy(original)
                    if invalid is None:
                        del value[key]
                    else:
                        value[key] = invalid
                    with self.subTest(key=key, value=invalid), self.assertRaises(sqlite3.Error):
                        connection.execute("UPDATE records SET record_json=?", (json.dumps(value),))
                    connection.rollback()
            with self.assertRaises(sqlite3.Error):
                connection.execute("UPDATE metadata SET complete=2")
            connection.rollback()
            with self.assertRaises(sqlite3.Error):
                connection.execute("INSERT INTO metadata SELECT * FROM metadata")

    def test_finish_write_failure_does_not_publish(self):
        writer = self.writer(batch_size=2)
        for record in self.records(draws=3):
            writer.append(record)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript("""
                CREATE TRIGGER reject_publish BEFORE UPDATE OF complete ON metadata
                WHEN NEW.complete=1 BEGIN SELECT RAISE(ABORT, 'publish failed'); END;
            """)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "publish failed"):
            writer.finish(trials=1, draws=3, initial_main_draws=0, bonus_per_trial=0)
        self.assertEqual(self.metadata()["complete"], 0)

    def test_close_releases_connection_and_never_publishes_partial_data(self):
        writer = self.writer(batch_size=2)
        writer.append(self.records(draws=1)[0])
        writer.close()
        writer.close()
        self.assertEqual(self.metadata()["complete"], 0)
        with self.assertRaises((ValueError, RuntimeError, sqlite3.ProgrammingError)):
            writer.append(self.records(draws=1)[0])
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("BEGIN EXCLUSIVE")
            connection.rollback()

    def test_finished_store_cannot_be_appended_or_republished(self):
        writer = self.writer(batch_size=1)
        writer.append(self.records(draws=1)[0])
        writer.finish(trials=1, draws=1, initial_main_draws=0, bonus_per_trial=0)
        with self.assertRaises((ValueError, RuntimeError)):
            writer.append(self.records(draws=2)[1])
        with self.assertRaises((ValueError, RuntimeError)):
            writer.finish(trials=2, draws=1, initial_main_draws=0, bonus_per_trial=0)
        self.assertEqual(self.metadata()["record_count"], 1)

    def test_finish_validates_each_row_before_fetching_the_next(self):
        connect = sqlite3.connect
        outstanding = 0

        def observe_row(cursor, row):
            nonlocal outstanding
            if len(row) == 1 and isinstance(row[0], str) and row[0].startswith("{"):
                self.assertEqual(outstanding, 0, "records were materialized before validation")
                outstanding += 1
            return row

        def observed_connection(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connection.row_factory = observe_row
            return connection

        def validate_row(value):
            nonlocal outstanding
            self.validate(value)
            outstanding = 0

        with patch("dashboard.trace_store.sqlite3.connect", side_effect=observed_connection):
            writer = self.writer(batch_size=2)
        for record in self.records(draws=5, trials=3):
            writer.append(record)
        with patch("dashboard.trace_store.validate_record", side_effect=validate_row):
            writer.finish(trials=3, draws=5, initial_main_draws=0, bonus_per_trial=0)
        self.assertEqual(self.metadata()["complete"], 1)

    def test_finish_revalidates_nested_json_from_disk(self):
        writer = self.writer(batch_size=1)
        record = self.records(draws=1)[0]
        writer.append(record)
        value = asdict(record)
        value["draw_result"]["outcome"]["rewards"] = {"bad": True}
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE records SET record_json=?", (json.dumps(value),))
        with self.assertRaises(ValueError):
            writer.finish(trials=1, draws=1, initial_main_draws=0, bonus_per_trial=0)
        self.assertEqual(self.metadata()["complete"], 0)

    def test_finish_reports_validation_progress_including_bonus_draws(self):
        writer = self.writer(batch_size=5)
        for record in self.records(draws=2, initial=29):
            writer.append(record)
        progress = []

        writer.finish(
            trials=1, draws=2, initial_main_draws=29, bonus_per_trial=10,
            progress_callback=lambda completed, total: progress.append((completed, total)),
        )

        self.assertEqual(progress, [(0, 12), (5, 12), (10, 12), (12, 12)])
        self.assertEqual(self.metadata()["complete"], 1)

    def test_finish_cancellation_and_progress_failure_never_publish_metadata(self):
        writer = self.writer(batch_size=2)
        for record in self.records(draws=2, initial=29):
            writer.append(record)
        with self.assertRaises(SimulationCancelled):
            writer.finish(
                trials=1, draws=2, initial_main_draws=29, bonus_per_trial=10,
                cancel_check=lambda: True,
            )
        self.assertEqual(self.metadata()["complete"], 0)

        self.path = self.path.with_name("batch-cancel.sqlite3")
        writer = self.writer(batch_size=2)
        for record in self.records(draws=2, initial=29):
            writer.append(record)
        checks = 0
        validated_progress = []

        def cancel_during_validation():
            nonlocal checks
            checks += 1
            return checks == 5

        with self.assertRaises(SimulationCancelled):
            writer.finish(
                trials=1, draws=2, initial_main_draws=29, bonus_per_trial=10,
                cancel_check=cancel_during_validation,
                progress_callback=lambda completed, total: validated_progress.append(
                    (completed, total)
                ),
            )
        self.assertEqual(validated_progress, [(0, 12), (2, 12)])
        self.assertEqual(self.metadata()["complete"], 0)

        self.path = self.path.with_name("final-cancel.sqlite3")
        writer = self.writer(batch_size=2)
        for record in self.records(draws=2, initial=29):
            writer.append(record)
        cancel_requested = False

        def cancel_after_final_progress(completed, total):
            nonlocal cancel_requested
            if completed == total:
                cancel_requested = True

        with self.assertRaises(SimulationCancelled):
            writer.finish(
                trials=1, draws=2, initial_main_draws=29, bonus_per_trial=10,
                cancel_check=lambda: cancel_requested,
                progress_callback=cancel_after_final_progress,
            )
        self.assertEqual(self.metadata()["complete"], 0)

        self.path = self.path.with_name("callback-failure.sqlite3")
        writer = self.writer(batch_size=2)
        for record in self.records(draws=2, initial=29):
            writer.append(record)

        def fail_on_first_batch(completed, total):
            if completed == 2:
                raise RuntimeError("progress failed")

        with self.assertRaisesRegex(RuntimeError, "progress failed"):
            writer.finish(
                trials=1, draws=2, initial_main_draws=29, bonus_per_trial=10,
                progress_callback=fail_on_first_batch,
            )
        self.assertEqual(self.metadata()["complete"], 0)

    def test_finish_rejects_invalid_parameters_and_empty_store(self):
        writer = self.writer()
        parameters = dict(trials=1, draws=1, initial_main_draws=0, bonus_per_trial=0)
        for name in parameters:
            for value in (True, -1, 1.0):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    writer.finish(**(parameters | {name: value}))
        with self.assertRaises(ValueError):
            writer.finish(**parameters)
        self.assertEqual(self.metadata()["complete"], 0)

    def test_tail_insert_failure_keeps_previous_batches_incomplete(self):
        writer = self.writer(batch_size=2)
        for record in self.records(draws=3):
            writer.append(record)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript("""
                CREATE TRIGGER reject_tail BEFORE INSERT ON records
                WHEN NEW.draw_index=3 BEGIN SELECT RAISE(ABORT, 'tail failed'); END;
            """)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "tail failed"):
            writer.finish(trials=1, draws=3, initial_main_draws=0, bonus_per_trial=0)
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.metadata()["complete"], 0)


if __name__ == "__main__":
    unittest.main()
