import django.db.models.deletion
import django.db.models.expressions
import django.db.models.functions.text
import django.db.models.lookups
import uuid
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
from django.db.models.expressions import RawSQL


def refuse_nonempty_v5(apps, schema_editor):
    """Only an empty target may cross the incompatible v5/v6 boundary."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        guarded = {
            "users", "pools", "experiment_configs", "simulation_runs",
            "draw_records", "login_limits", "app_meta", "django_session",
            "users_groups", "users_user_permissions", "auth_group_permissions",
            "django_admin_log",
        }
        for table in sorted(tables & guarded):
            cursor.execute(f'SELECT 1 FROM "{table}" LIMIT 1')
            if cursor.fetchone():
                raise RuntimeError("检测到非空v5账号、业务或防护数据；拒绝就地升级，请使用独立空v6目标库")
        cursor.execute("PRAGMA user_version")
        version = cursor.fetchone()[0]
        if version not in (0, 5):
            raise RuntimeError("数据库版本标记不是空库或v5，拒绝升级")


def set_version(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("PRAGMA user_version = 6")


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0001_initial")]

    operations = [
        # This must stay ahead of every schema edit, including trigger removal.
        migrations.RunPython(refuse_nonempty_v5),
        migrations.RunSQL(
            "DROP TRIGGER IF EXISTS runs_draw_records_cascade",
            migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DROP TRIGGER IF EXISTS pools_config_set_null",
            migrations.RunSQL.noop,
        ),
        migrations.CreateModel(
            name="Rule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("name_key", models.CharField(max_length=255)),
                ("kind", models.CharField(choices=[("public", "public"), ("private", "private")], max_length=7)),
                ("visibility", models.CharField(choices=[("public", "public"), ("hidden", "hidden")], max_length=6)),
                ("original_author", models.CharField(max_length=255)),
                ("algorithm", models.CharField(default="dynamic_probability", max_length=64)),
                ("config_json", models.JSONField()),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="owned_rules", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "rules"},
        ),
        migrations.AddConstraint("rule", models.CheckConstraint(condition=models.Q(models.Q(("kind", "public"), ("owner__isnull", True), ("visibility", "public")), models.Q(("kind", "private"), ("owner__isnull", False), ("visibility__in", ["public", "hidden"])), _connector="OR"), name="rules_kind_owner_visibility")),
        migrations.AddConstraint("rule", models.CheckConstraint(condition=django.db.models.lookups.GreaterThan(django.db.models.functions.text.Length(django.db.models.functions.text.Trim(models.F("name"))), models.Value(0)), name="rules_name_nonblank")),
        migrations.AddConstraint("rule", models.CheckConstraint(condition=django.db.models.lookups.GreaterThan(django.db.models.functions.text.Length(django.db.models.functions.text.Trim(models.F("name_key"))), models.Value(0)), name="rules_name_key_nonblank")),
        migrations.AddConstraint("rule", models.CheckConstraint(condition=models.Q(("revision__gte", 1)), name="rules_revision_positive")),
        migrations.AddConstraint("rule", models.UniqueConstraint(condition=models.Q(("kind", "public")), fields=("name_key",), name="rules_public_name_unique")),
        migrations.AddConstraint("rule", models.UniqueConstraint(condition=models.Q(("kind", "private")), fields=("owner", "name_key"), name="rules_private_owner_name_unique")),
        migrations.AddField(model_name="pool", name="rule", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pools", to="dashboard.rule")),
        migrations.RemoveField(model_name="pool", name="rule_name"),
        migrations.AlterField(model_name="pool", name="rule", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pools", to="dashboard.rule")),
        migrations.AddField(model_name="experimentconfig", name="initial_context_json", field=models.JSONField(default=dict)),
        migrations.RemoveConstraint(model_name="simulationrun", name="runs_schema_version_v5"),
        migrations.RemoveConstraint(model_name="simulationrun", name="runs_trace_count_matches"),
        migrations.RemoveField(model_name="simulationrun", name="initial_pity"),
        migrations.RemoveField(model_name="simulationrun", name="initial_five_star_pity"),
        migrations.RemoveField(model_name="simulationrun", name="rule_name"),
        migrations.RemoveField(model_name="simulationrun", name="record_count"),
        migrations.RenameField(model_name="simulationrun", old_name="original_author_snapshot", new_name="pool_original_author_snapshot"),
        migrations.AddField(model_name="simulationrun", name="rule_id_snapshot", field=models.UUIDField(default=uuid.uuid4, editable=False), preserve_default=False),
        migrations.AddField(model_name="simulationrun", name="rule_revision_snapshot", field=models.PositiveBigIntegerField(default=1), preserve_default=False),
        migrations.AddField(model_name="simulationrun", name="rule_name_snapshot", field=models.CharField(default="", max_length=255), preserve_default=False),
        migrations.AddField(model_name="simulationrun", name="rule_original_author_snapshot", field=models.CharField(default="", max_length=255), preserve_default=False),
        migrations.AddField(model_name="simulationrun", name="event_count", field=models.PositiveBigIntegerField(default=0), preserve_default=False),
        migrations.AddField(model_name="simulationrun", name="rule_config_json", field=models.JSONField(default=dict), preserve_default=False),
        migrations.AddField(model_name="simulationrun", name="parameters_json", field=models.JSONField(default=dict), preserve_default=False),
        migrations.AddField(model_name="simulationrun", name="initial_context_json", field=models.JSONField(default=dict), preserve_default=False),
        migrations.AlterField(model_name="simulationrun", name="pool_revision_snapshot", field=models.PositiveBigIntegerField()),
        migrations.AlterField(model_name="simulationrun", name="main_draws", field=models.PositiveBigIntegerField()),
        migrations.AlterField(model_name="simulationrun", name="trials", field=models.PositiveBigIntegerField()),
        migrations.AlterField(model_name="simulationrun", name="schema_version", field=models.PositiveSmallIntegerField(default=6)),
        migrations.AddConstraint("simulationrun", models.CheckConstraint(condition=models.Q(("schema_version", 6)), name="runs_schema_version_v6")),
        migrations.AddConstraint("simulationrun", models.CheckConstraint(condition=models.Q(("rule_revision_snapshot__gte", 1)), name="runs_rule_revision_positive")),
        migrations.AddConstraint("simulationrun", models.CheckConstraint(condition=models.Q(models.Q(("event_count", 0), ("trace_enabled", False)), models.Q(("event_count__gt", 0), ("trace_enabled", True)), _connector="OR"), name="runs_trace_count_matches")),
        migrations.CreateModel(
            name="SimulationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("trial_index", models.PositiveBigIntegerField()),
                ("event_index", models.PositiveBigIntegerField()),
                ("event_type", models.CharField(choices=[("draw", "draw"), ("character_grant", "character_grant")], max_length=16)),
                ("main_draws_completed", models.PositiveBigIntegerField()),
                ("mechanism_id", models.CharField(blank=True, max_length=64, null=True)),
                ("draw_index", models.PositiveBigIntegerField(blank=True, null=True)),
                ("source", models.CharField(blank=True, choices=[("main", "main"), ("bonus", "bonus")], max_length=5, null=True)),
                ("source_index", models.PositiveBigIntegerField(blank=True, null=True)),
                ("rarity_id", models.CharField(blank=True, max_length=36, null=True)),
                ("character_id", models.CharField(blank=True, max_length=36, null=True)),
                ("event_json", models.JSONField()),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="dashboard.simulationrun")),
            ],
            options={"db_table": "simulation_events"},
        ),
        migrations.AddIndex("simulationevent", models.Index(fields=["run", "event_type"], name="events_run_type_idx")),
        migrations.AddIndex("simulationevent", models.Index(fields=["run", "source", "source_index"], name="events_run_source_idx")),
        migrations.AddIndex("simulationevent", models.Index(fields=["run", "rarity_id"], name="events_run_rarity_idx")),
        migrations.AddIndex("simulationevent", models.Index(fields=["run", "character_id"], name="events_run_character_idx")),
        migrations.AddConstraint("simulationevent", models.UniqueConstraint(fields=("run", "trial_index", "event_index"), name="events_run_trial_event_unique")),
        migrations.AddConstraint("simulationevent", models.CheckConstraint(condition=models.Q(("event_index__gt", 0), ("main_draws_completed__gte", 0), ("trial_index__gt", 0)), name="events_indexes_positive")),
        migrations.AddConstraint("simulationevent", models.CheckConstraint(
                condition=(Q(event_type="draw", draw_index__gt=0, source__in=["main", "bonus"],
                             source_index__gt=0, rarity_id__isnull=False) |
                           Q(event_type="character_grant", draw_index__isnull=True,
                             source__isnull=True, source_index__isnull=True,
                             rarity_id__isnull=False, character_id__isnull=False)),
                name="events_type_fields_valid",
            )),
        migrations.AddConstraint("simulationevent", models.CheckConstraint(
                condition=RawSQL(
                    "json_type(event_json, '$') IS 'object' "
                    "AND json_type(event_json, '$.event_format_version') IS 'integer' "
                    "AND json_extract(event_json, '$.event_format_version') = 3 "
                    "AND trial_index IS json_extract(event_json, '$.trial_index') "
                    "AND event_index IS json_extract(event_json, '$.event_index') "
                    "AND event_type IS json_extract(event_json, '$.event_type') "
                    "AND json_type(event_json, '$.trial_index') IS 'integer' "
                    "AND json_type(event_json, '$.event_index') IS 'integer' "
                    "AND json_type(event_json, '$.main_draws_completed') IS 'integer' "
                    "AND json_type(event_json, '$.event_type') IS 'text' "
                    "AND main_draws_completed IS json_extract(event_json, '$.main_draws_completed') "
                    "AND mechanism_id IS json_extract(event_json, '$.mechanism_id') "
                    "AND draw_index IS json_extract(event_json, '$.draw_index') "
                    "AND source IS json_extract(event_json, '$.source') "
                    "AND source_index IS json_extract(event_json, '$.source_index') "
                    "AND ((event_type = 'draw' AND json_type(event_json, '$.draw_index') IS 'integer' "
                    "AND json_type(event_json, '$.source') IS 'text' "
                    "AND json_type(event_json, '$.source_index') IS 'integer' "
                    "AND json_type(event_json, '$.main_draws_completed') IS 'integer' "
                    "AND (json_type(event_json, '$.mechanism_id') IS 'text' "
                    "OR json_type(event_json, '$.mechanism_id') IS 'null') "
                    "AND json_type(event_json, '$.draw_result') IS 'object' "
                    "AND json_type(event_json, '$.grant') IS NULL "
                    "AND json_type(event_json, '$.draw_result.outcome.rarity_id') IS 'text' "
                    "AND (json_type(event_json, '$.draw_result.outcome.character_id') IS 'text' "
                    "OR json_type(event_json, '$.draw_result.outcome.character_id') IS 'null') "
                    "AND rarity_id IS json_extract(event_json, '$.draw_result.outcome.rarity_id') "
                    "AND character_id IS json_extract(event_json, '$.draw_result.outcome.character_id') "
                    "AND mechanism_id IS json_extract(event_json, '$.mechanism_id')) "
                    "OR (event_type = 'character_grant' AND json_type(event_json, '$.draw_index') IS 'null' "
                    "AND json_type(event_json, '$.source') IS 'null' "
                    "AND json_type(event_json, '$.source_index') IS 'null' "
                    "AND json_type(event_json, '$.main_draws_completed') IS 'integer' "
                    "AND (json_type(event_json, '$.mechanism_id') IS 'text' "
                    "OR json_type(event_json, '$.mechanism_id') IS 'null') "
                    "AND json_type(event_json, '$.draw_result') IS NULL "
                    "AND json_type(event_json, '$.grant') IS 'object' "
                    "AND json_type(event_json, '$.grant.rarity_id') IS 'text' "
                    "AND json_type(event_json, '$.grant.character_id') IS 'text' "
                    "AND json_type(event_json, '$.grant.character_name') IS 'text' "
                    "AND (json_type(event_json, '$.grant.is_up') IS 'true' "
                    "OR json_type(event_json, '$.grant.is_up') IS 'false') "
                    "AND (json_type(event_json, '$.grant.is_limited') IS 'true' "
                    "OR json_type(event_json, '$.grant.is_limited') IS 'false') "
                    "AND json_type(event_json, '$.grant.quantity') IS 'integer' "
                    "AND json_extract(event_json, '$.grant.quantity') > 0 "
                    "AND json_type(event_json, '$.grant.trigger_main_draw') IS 'integer' "
                    "AND json_extract(event_json, '$.grant.trigger_main_draw') = main_draws_completed "
                    "AND rarity_id IS json_extract(event_json, '$.grant.rarity_id') "
                    "AND character_id IS json_extract(event_json, '$.grant.character_id'))) ",
                    [], output_field=models.BooleanField(),
                ),
                name="events_json_matches_columns",
            )),
        migrations.DeleteModel(name="DrawRecord"),
        # Keep raw-SQL delete behavior used by repository paths as well as ORM collection.
        migrations.RunSQL(
            "CREATE TRIGGER pools_config_set_null AFTER DELETE ON pools "
            "BEGIN UPDATE experiment_configs SET pool_id = NULL WHERE pool_id = OLD.id; END",
            "DROP TRIGGER IF EXISTS pools_config_set_null",
        ),
        migrations.RunSQL(
            "CREATE TRIGGER runs_simulation_events_cascade AFTER DELETE ON simulation_runs "
            "BEGIN DELETE FROM simulation_events WHERE run_id = OLD.id; END",
            "DROP TRIGGER IF EXISTS runs_simulation_events_cascade",
        ),
        migrations.RunPython(set_version),
    ]
