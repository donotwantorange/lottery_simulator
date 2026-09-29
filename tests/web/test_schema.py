"""Task 14 schema acceptance checks; run with ``manage.py test tests.web.test_schema``."""

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from dashboard.models import DrawRecord, ExperimentConfig, Pool, SimulationRun, User


class SchemaTests(TestCase):
    def user(self, name):
        return User.objects.create(username=name, username_key=name)

    def pool(self, name, *, owner=None, kind="public", visibility="public"):
        return Pool.objects.create(
            name=name, name_key=name, kind=kind, owner=owner,
            visibility=visibility, original_author="原作者",
            rule_name="rule1", config_json={},
        )

    def make_run(self, owner, pool):
        return SimulationRun.objects.create(
            owner=owner, pool_id_snapshot=pool.id, pool_revision_snapshot=pool.revision,
            pool_name_snapshot=pool.name, original_author_snapshot=pool.original_author,
            rule_name="rule1", rule_version="2.0", main_draws=1, trials=1,
            initial_pity=0, initial_five_star_pity=0,
            seed=str(2**100 + 1), trace_enabled=False, record_count=0,
            pool_config_json={}, result_json={},
        )

    def test_pool_ownership_and_names_are_constrained(self):
        alice = self.user("alice")
        bob = self.user("bob")
        self.pool("共享")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.pool("共享")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.pool("坏公共池", owner=alice)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.pool("无主私有池", kind="private", visibility="hidden")
        self.pool("同名私有池", owner=alice, kind="private", visibility="hidden")
        self.pool("同名私有池", owner=bob, kind="private", visibility="hidden")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.pool("同名私有池", owner=alice, kind="private", visibility="hidden")

    def test_pool_deletion_keeps_config_hint_and_run_snapshot(self):
        owner = self.user("owner")
        pool = self.pool("原池")
        config = ExperimentConfig.objects.create(
            owner=owner, name="实验", name_key="实验", pool=pool,
            pool_name_hint=pool.name, parameters_json={},
        )
        run = self.make_run(owner, pool)
        old_pool_id = pool.id
        pool.delete()
        config.refresh_from_db()
        run.refresh_from_db()
        self.assertIsNone(config.pool_id)
        self.assertEqual(config.pool_name_hint, "原池")
        self.assertEqual(run.pool_id_snapshot, old_pool_id)

    def test_experiment_name_is_unique_only_within_owner(self):
        alice, bob = self.user("alice"), self.user("bob")
        for owner in (alice, bob):
            ExperimentConfig.objects.create(owner=owner, name="同名", name_key="同名",
                                            parameters_json={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExperimentConfig.objects.create(owner=alice, name="同名", name_key="同名",
                                            parameters_json={})

    def test_trace_columns_match_json_and_seed_stays_text(self):
        owner = self.user("traceuser")
        run = self.make_run(owner, self.pool("Trace池"))
        run.refresh_from_db()
        self.assertEqual(run.seed, str(2**100 + 1))
        record = {
            "record_format_version": 2, "trial_index": 1, "draw_index": 1,
            "source": "main", "source_index": 1,
            "draw_result": {"outcome": {"rarity": 4, "character_name": "角色"}},
        }
        with self.assertRaises(IntegrityError), transaction.atomic():
            DrawRecord.objects.create(
                run=run, trial_index=1, draw_index=1, source="main",
                source_index=1, rarity=5, character_name="角色", record_json=record,
            )
        run.trace_enabled = True
        run.record_count = 1
        run.save(update_fields=["trace_enabled", "record_count"])
        DrawRecord.objects.create(
            run=run, trial_index=1, draw_index=1, source="main",
            source_index=1, rarity=4, character_name="角色", record_json=record,
        )

    def test_format_marker_and_session_table(self):
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA user_version")
            self.assertEqual(cursor.fetchone()[0], 5)
            cursor.execute("SELECT name FROM sqlite_master WHERE name = 'django_session'")
            self.assertEqual(cursor.fetchone()[0], "django_session")
