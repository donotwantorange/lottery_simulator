"""Persistent v5 business objects. Job-file contracts remain in job_models."""

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThan

from lottery_simulator.formats import DATABASE_SCHEMA_VERSION, RECORD_FORMAT_VERSION


def nonblank(field):
    return GreaterThan(Length(Trim(F(field))), Value(0))


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=64, unique=True)
    username_key = models.CharField(max_length=64, unique=True)
    must_change_password = models.BooleanField(default=False)
    auth_version = models.PositiveIntegerField(default=1)
    deleting = models.BooleanField(default=False)

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(condition=nonblank("username"), name="users_username_nonblank"),
            models.CheckConstraint(condition=nonblank("username_key"), name="users_username_key_nonblank"),
            models.CheckConstraint(condition=Q(is_staff=F("is_superuser")), name="users_staff_matches_superuser"),
        ]


class Pool(models.Model):
    PUBLIC = "public"
    PRIVATE = "private"
    HIDDEN = "hidden"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    name_key = models.CharField(max_length=255)
    kind = models.CharField(max_length=7, choices=[(PUBLIC, PUBLIC), (PRIVATE, PRIVATE)])
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.CASCADE, related_name="owned_pools")
    visibility = models.CharField(max_length=6, choices=[(PUBLIC, PUBLIC), (HIDDEN, HIDDEN)])
    original_author = models.CharField(max_length=255)
    rule_name = models.CharField(max_length=128)
    config_json = models.JSONField()
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pools"
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind="public", owner__isnull=True, visibility="public") |
                           Q(kind="private", owner__isnull=False,
                             visibility__in=["public", "hidden"])),
                name="pools_kind_owner_visibility",
            ),
            models.CheckConstraint(condition=nonblank("name"), name="pools_name_nonblank"),
            models.CheckConstraint(condition=nonblank("name_key"), name="pools_name_key_nonblank"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="pools_revision_positive"),
            models.UniqueConstraint(fields=["name_key"], condition=Q(kind="public"),
                                    name="pools_public_name_unique"),
            models.UniqueConstraint(fields=["owner", "name_key"], condition=Q(kind="private"),
                                    name="pools_private_owner_name_unique"),
        ]


class ExperimentConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="experiment_configs")
    name = models.CharField(max_length=255)
    name_key = models.CharField(max_length=255)
    pool = models.ForeignKey(Pool, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="experiment_configs")
    pool_name_hint = models.CharField(max_length=255, blank=True)
    parameters_json = models.JSONField()
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "experiment_configs"
        constraints = [
            models.CheckConstraint(condition=nonblank("name"), name="experiment_name_nonblank"),
            models.CheckConstraint(condition=nonblank("name_key"), name="experiment_name_key_nonblank"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="experiment_revision_positive"),
            models.UniqueConstraint(fields=["owner", "name_key"],
                                    name="experiment_owner_name_unique"),
        ]


class SimulationRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="simulation_runs")
    created_at = models.DateTimeField(auto_now_add=True)
    pool_id_snapshot = models.UUIDField()
    pool_revision_snapshot = models.PositiveIntegerField()
    pool_name_snapshot = models.CharField(max_length=255)
    original_author_snapshot = models.CharField(max_length=255)
    rule_name = models.CharField(max_length=128)
    rule_version = models.CharField(max_length=32)
    main_draws = models.PositiveIntegerField()
    trials = models.PositiveIntegerField()
    initial_pity = models.PositiveIntegerField()
    initial_five_star_pity = models.PositiveIntegerField()
    seed = models.TextField()  # Decimal text preserves integers beyond SQLite int64.
    trace_enabled = models.BooleanField()
    record_count = models.PositiveIntegerField()
    pool_config_json = models.JSONField()
    result_json = models.JSONField()
    schema_version = models.PositiveSmallIntegerField(default=DATABASE_SCHEMA_VERSION)

    class Meta:
        db_table = "simulation_runs"
        indexes = [models.Index(fields=["owner", "-created_at"], name="runs_owner_created_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(schema_version=DATABASE_SCHEMA_VERSION),
                                   name="runs_schema_version_v5"),
            models.CheckConstraint(condition=Q(pool_revision_snapshot__gte=1),
                                   name="runs_pool_revision_positive"),
            models.CheckConstraint(condition=Q(main_draws__gte=1, trials__gte=1),
                                   name="runs_draw_counts_positive"),
            models.CheckConstraint(
                condition=(Q(trace_enabled=False, record_count=0) |
                           Q(trace_enabled=True, record_count__gt=0)),
                name="runs_trace_count_matches",
            ),
        ]


class DrawRecord(models.Model):
    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name="draw_records")
    trial_index = models.PositiveIntegerField()
    draw_index = models.PositiveIntegerField()
    source = models.CharField(max_length=5, choices=[("main", "main"), ("bonus", "bonus")])
    source_index = models.PositiveIntegerField()
    rarity = models.PositiveSmallIntegerField(choices=[(4, "4"), (5, "5"), (6, "6")])
    character_name = models.TextField(null=True, blank=True)
    record_json = models.JSONField()

    class Meta:
        db_table = "draw_records"
        indexes = [models.Index(fields=["run", "source", "source_index", "rarity"],
                                name="draw_run_source_position_idx")]
        constraints = [
            models.UniqueConstraint(fields=["run", "trial_index", "draw_index"],
                                    name="draw_records_run_trial_draw_unique"),
            models.CheckConstraint(condition=Q(trial_index__gt=0, draw_index__gt=0,
                                               source_index__gt=0), name="draw_records_indexes_positive"),
            models.CheckConstraint(condition=Q(source__in=["main", "bonus"]),
                                   name="draw_records_source_valid"),
            models.CheckConstraint(condition=Q(rarity__in=[4, 5, 6]),
                                   name="draw_records_rarity_valid"),
            models.CheckConstraint(
                condition=RawSQL(
                    "json_type(record_json, '$') IS 'object' "
                    "AND json_type(record_json, '$.record_format_version') IS 'integer' "
                    f"AND json_extract(record_json, '$.record_format_version') = {RECORD_FORMAT_VERSION} "
                    "AND trial_index IS json_extract(record_json, '$.trial_index') "
                    "AND draw_index IS json_extract(record_json, '$.draw_index') "
                    "AND source IS json_extract(record_json, '$.source') "
                    "AND source_index IS json_extract(record_json, '$.source_index') "
                    "AND rarity IS json_extract(record_json, '$.draw_result.outcome.rarity') "
                    "AND character_name IS json_extract(record_json, '$.draw_result.outcome.character_name')",
                    [], output_field=models.BooleanField(),
                ),
                name="draw_records_json_matches_columns",
            ),
        ]


class LoginLimit(models.Model):
    """A surrogate ORM key with a database-unique (scope, key) bucket."""

    scope = models.CharField(max_length=7, choices=[("account", "account"),
                                                    ("source", "source")])
    key = models.TextField()
    failure_count = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField(null=True, blank=True)
    blocked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "login_limits"
        constraints = [
            models.UniqueConstraint(fields=["scope", "key"], name="login_limits_scope_key_unique"),
            models.CheckConstraint(condition=Q(scope__in=["account", "source"]),
                                   name="login_limits_scope_valid"),
            models.CheckConstraint(condition=nonblank("key"), name="login_limits_key_nonblank"),
        ]


class AppMeta(models.Model):
    key = models.CharField(max_length=128, primary_key=True)
    value = models.JSONField()

    class Meta:
        db_table = "app_meta"
