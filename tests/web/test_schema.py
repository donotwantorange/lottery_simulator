"""Task 6 schema checks; migration probes use their own temporary SQLite files."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from dashboard.models import ExperimentConfig, Pool, Rule, SimulationEvent, SimulationRun, User


REPO_ROOT = Path(__file__).resolve().parents[2]


class SchemaTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(username="owner", username_key="owner")
        self.rule = Rule.objects.create(
            name="zmd", name_key="zmd", kind="public", owner=None, visibility="public",
            original_author="原作者", algorithm="dynamic_probability", config_json={},
        )

    def pool(self, name="池"):
        return Pool.objects.create(name=name, name_key=name, kind="public", owner=None,
                                   visibility="public", original_author="原作者", rule=self.rule,
                                   config_json={})

    def make_run(self, pool, *, trace=False, event_count=0):
        return SimulationRun.objects.create(
            owner=self.owner, pool_id_snapshot=pool.id, pool_revision_snapshot=1,
            pool_name_snapshot=pool.name, pool_original_author_snapshot="原作者",
            rule_id_snapshot=self.rule.id, rule_revision_snapshot=1,
            rule_name_snapshot=self.rule.name, rule_original_author_snapshot="原作者",
            rule_version="3.0", main_draws=1, trials=1, seed=str(2**100 + 1),
            trace_enabled=trace, event_count=event_count, pool_config_json={},
            rule_config_json={}, parameters_json={}, initial_context_json={}, result_json={},
        )

    def test_rule_protects_bound_pool_and_pool_delete_keeps_config_hint(self):
        pool = self.pool()
        config = ExperimentConfig.objects.create(owner=self.owner, name="实验", name_key="实验",
            pool=pool, pool_name_hint=pool.name, parameters_json={}, initial_context_json={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.rule.delete()
        pool.delete()
        config.refresh_from_db()
        self.assertIsNone(config.pool_id)
        self.assertEqual(config.pool_name_hint, "池")

    def test_rule_and_pool_uniqueness_and_ownership_constraints(self):
        alice = self.owner
        bob = User.objects.create(username="bob", username_key="bob")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Rule.objects.create(name="zmd", name_key="zmd", kind="public", owner=None,
                visibility="public", original_author="原作者", config_json={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            Rule.objects.create(name="坏公共规则", name_key="坏公共规则", kind="public", owner=alice,
                visibility="public", original_author="原作者", config_json={})
        Rule.objects.create(name="私有", name_key="私有", kind="private", owner=alice,
            visibility="hidden", original_author="原作者", config_json={})
        Rule.objects.create(name="私有", name_key="私有", kind="private", owner=bob,
            visibility="hidden", original_author="原作者", config_json={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            Pool.objects.create(name="池", name_key="池", kind="public", owner=None,
                visibility="hidden", original_author="原作者", rule=self.rule, config_json={})
        Pool.objects.create(name="池", name_key="池", kind="public", owner=None,
            visibility="public", original_author="原作者", rule=self.rule, config_json={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            Pool.objects.create(name="池", name_key="池", kind="public", owner=None,
                visibility="public", original_author="原作者", rule=self.rule, config_json={})
        ExperimentConfig.objects.create(owner=alice, name="实验", name_key="实验",
            parameters_json={}, initial_context_json={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExperimentConfig.objects.create(owner=alice, name="实验", name_key="实验",
                parameters_json={}, initial_context_json={})

    def test_event_json_indexes_and_type_constraints_reject_inconsistent_rows(self):
        run = self.make_run(self.pool(), trace=True, event_count=1)
        grant = {
            "event_format_version": 3, "trial_index": 1, "event_index": 1,
            "event_type": "character_grant", "main_draws_completed": 1,
            "mechanism_id": "periodic_grant", "draw_index": None, "source": None,
            "source_index": None,
            "grant": {"rarity_id": "rarity-id", "character_id": "character-id",
                      "character_name": "角色", "is_up": True, "is_limited": True,
                      "quantity": 0, "trigger_main_draw": 1},
        }
        with self.assertRaises(IntegrityError), transaction.atomic():
            SimulationEvent.objects.create(run=run, trial_index=1, event_index=1,
                event_type="character_grant", main_draws_completed=1,
                mechanism_id="periodic_grant", rarity_id="rarity-id", character_id="character-id",
                event_json=grant)

    def test_draw_and_grant_events_are_indexed_by_shared_columns_and_cascade(self):
        run = self.make_run(self.pool(), trace=True, event_count=2)
        draw = {
            "event_format_version": 3, "trial_index": 1, "event_index": 1,
            "event_type": "draw", "main_draws_completed": 1, "mechanism_id": None,
            "draw_index": 1, "source": "main", "source_index": 1,
            "draw_result": {"outcome": {"rarity_id": "rarity-id", "character_id": "character-id"}},
        }
        grant = {
            "event_format_version": 3, "trial_index": 1, "event_index": 2,
            "event_type": "character_grant", "main_draws_completed": 1,
            "mechanism_id": "periodic_grant", "draw_index": None, "source": None,
            "source_index": None,
            "grant": {"rarity_id": "rarity-id", "character_id": "character-id",
                      "character_name": "角色", "is_up": True, "is_limited": True,
                      "quantity": 1, "trigger_main_draw": 1},
        }
        SimulationEvent.objects.create(run=run, trial_index=1, event_index=1,
            event_type="draw", main_draws_completed=1, rarity_id="rarity-id",
            character_id="character-id", draw_index=1, source="main", source_index=1,
            event_json=draw)
        SimulationEvent.objects.create(run=run, trial_index=1, event_index=2,
            event_type="character_grant", main_draws_completed=1,
            mechanism_id="periodic_grant", rarity_id="rarity-id", character_id="character-id",
            event_json=grant)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM simulation_runs WHERE id = %s", [run.pk.hex])
        self.assertFalse(SimulationEvent.objects.exists())

    def test_raw_sql_pool_delete_keeps_experiment_reference_as_set_null(self):
        pool = self.pool()
        config = ExperimentConfig.objects.create(owner=self.owner, name="实验", name_key="实验",
            pool=pool, pool_name_hint=pool.name, parameters_json={}, initial_context_json={})
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM pools WHERE id = %s", [pool.pk.hex])
        config.refresh_from_db()
        self.assertIsNone(config.pool_id)
        self.assertEqual(config.pool_name_hint, "池")

    def test_empty_chain_and_nonempty_v5_refusal_in_isolated_databases(self):
        probe = r'''
import os
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor = MigrationExecutor(connection)
executor.migrate([("dashboard", "0001_initial")] + [
    node for node in executor.loader.graph.leaf_nodes() if node[0] != "dashboard"])
if os.environ["MIGRATION_PROBE"] == "reject":
    apps = executor.loader.project_state([("dashboard", "0001_initial")]).apps
    apps.get_model("dashboard", "User").objects.create(
        username="kept", username_key="kept", password="!", is_staff=False,
        is_superuser=False)
    try:
        MigrationExecutor(connection).migrate([("dashboard", "0002_independent_rules_v6")])
    except RuntimeError as error:
        assert "非空v5" in str(error)
    else:
        raise AssertionError("non-empty v5 database was not rejected")
    with connection.cursor() as cursor:
        cursor.execute("SELECT username FROM users")
        assert cursor.fetchone()[0] == "kept"
        cursor.execute("PRAGMA user_version")
        assert cursor.fetchone()[0] == 5
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='draw_records'")
        assert cursor.fetchone()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name='runs_draw_records_cascade'")
        assert cursor.fetchone()
else:
    MigrationExecutor(connection).migrate([("dashboard", "0002_independent_rules_v6")])
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA user_version")
        assert cursor.fetchone()[0] == 6
        cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND sql LIKE '%draw_records%'")
        assert cursor.fetchone() is None
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='django_session'")
        assert cursor.fetchone()
'''
        for mode in ("empty", "reject"):
            with TemporaryDirectory(prefix=f"lottery-v6-{mode}-") as directory:
                environment = os.environ.copy()
                environment.update({"PYTHONDONTWRITEBYTECODE": "1",
                    "DJANGO_SETTINGS_MODULE": "webapp.settings",
                    "LOTTERY_DB_PATH": str(Path(directory) / "target.sqlite3"),
                    "MIGRATION_PROBE": mode})
                result = subprocess.run([sys.executable, "-c", probe], cwd=REPO_ROOT,
                    env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_schema_marker_and_session_table(self):
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA user_version")
            self.assertEqual(cursor.fetchone()[0], 6)
            cursor.execute("SELECT name FROM sqlite_master WHERE name = 'django_session'")
            self.assertEqual(cursor.fetchone()[0], "django_session")
