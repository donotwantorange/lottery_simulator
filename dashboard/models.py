"""Persistent v6 business objects. Job-file contracts remain in job_models."""

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThan

from lottery_simulator.formats import DATABASE_SCHEMA_VERSION, EVENT_FORMAT_VERSION


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


class Rule(models.Model):
    PUBLIC = "public"
    PRIVATE = "private"
    HIDDEN = "hidden"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    name_key = models.CharField(max_length=255)
    kind = models.CharField(max_length=7, choices=[(PUBLIC, PUBLIC), (PRIVATE, PRIVATE)])
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.CASCADE, related_name="owned_rules")
    visibility = models.CharField(max_length=6, choices=[(PUBLIC, PUBLIC), (HIDDEN, HIDDEN)])
    original_author = models.CharField(max_length=255)
    algorithm = models.CharField(max_length=64, default="dynamic_probability")
    config_json = models.JSONField()
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rules"
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind="public", owner__isnull=True, visibility="public") |
                           Q(kind="private", owner__isnull=False,
                             visibility__in=["public", "hidden"])),
                name="rules_kind_owner_visibility",
            ),
            models.CheckConstraint(condition=nonblank("name"), name="rules_name_nonblank"),
            models.CheckConstraint(condition=nonblank("name_key"), name="rules_name_key_nonblank"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="rules_revision_positive"),
            models.UniqueConstraint(fields=["name_key"], condition=Q(kind="public"),
                                    name="rules_public_name_unique"),
            models.UniqueConstraint(fields=["owner", "name_key"], condition=Q(kind="private"),
                                    name="rules_private_owner_name_unique"),
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
    rule = models.ForeignKey(Rule, on_delete=models.PROTECT, related_name="pools")
    visibility = models.CharField(max_length=6, choices=[(PUBLIC, PUBLIC), (HIDDEN, HIDDEN)])
    original_author = models.CharField(max_length=255)
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
    initial_context_json = models.JSONField(default=dict)
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
    pool_revision_snapshot = models.PositiveBigIntegerField()
    pool_name_snapshot = models.CharField(max_length=255)
    pool_original_author_snapshot = models.CharField(max_length=255)
    rule_id_snapshot = models.UUIDField(editable=False)
    rule_revision_snapshot = models.PositiveBigIntegerField()
    rule_name_snapshot = models.CharField(max_length=255)
    rule_original_author_snapshot = models.CharField(max_length=255)
    rule_version = models.CharField(max_length=32)
    main_draws = models.PositiveBigIntegerField()
    trials = models.PositiveBigIntegerField()
    seed = models.TextField()  # Decimal text preserves integers beyond SQLite int64.
    trace_enabled = models.BooleanField()
    event_count = models.PositiveBigIntegerField()
    pool_config_json = models.JSONField()
    rule_config_json = models.JSONField()
    parameters_json = models.JSONField()
    initial_context_json = models.JSONField()
    result_json = models.JSONField()
    schema_version = models.PositiveSmallIntegerField(default=DATABASE_SCHEMA_VERSION)

    class Meta:
        db_table = "simulation_runs"
        indexes = [models.Index(fields=["owner", "-created_at"], name="runs_owner_created_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(schema_version=DATABASE_SCHEMA_VERSION),
                                   name="runs_schema_version_v6"),
            models.CheckConstraint(condition=Q(pool_revision_snapshot__gte=1),
                                   name="runs_pool_revision_positive"),
            models.CheckConstraint(condition=Q(rule_revision_snapshot__gte=1),
                                   name="runs_rule_revision_positive"),
            models.CheckConstraint(condition=Q(main_draws__gte=1, trials__gte=1),
                                   name="runs_draw_counts_positive"),
            models.CheckConstraint(
                condition=(Q(trace_enabled=False, event_count=0) |
                           Q(trace_enabled=True, event_count__gt=0)),
                name="runs_trace_count_matches",
            ),
        ]


class SimulationEvent(models.Model):
    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name="events")
    trial_index = models.PositiveBigIntegerField()
    event_index = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=16, choices=[("draw", "draw"), ("character_grant", "character_grant")])
    main_draws_completed = models.PositiveBigIntegerField()
    mechanism_id = models.CharField(max_length=64, null=True, blank=True)
    draw_index = models.PositiveBigIntegerField(null=True, blank=True)
    source = models.CharField(max_length=5, choices=[("main", "main"), ("bonus", "bonus")], null=True, blank=True)
    source_index = models.PositiveBigIntegerField(null=True, blank=True)
    rarity_id = models.CharField(max_length=36, null=True, blank=True)
    character_id = models.CharField(max_length=36, null=True, blank=True)
    event_json = models.JSONField()

    class Meta:
        db_table = "simulation_events"
        indexes = [
            models.Index(fields=["run", "event_type"], name="events_run_type_idx"),
            models.Index(fields=["run", "source", "source_index"], name="events_run_source_idx"),
            models.Index(fields=["run", "rarity_id"], name="events_run_rarity_idx"),
            models.Index(fields=["run", "character_id"], name="events_run_character_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["run", "trial_index", "event_index"],
                                    name="events_run_trial_event_unique"),
            models.CheckConstraint(condition=Q(trial_index__gt=0, event_index__gt=0,
                                               main_draws_completed__gte=0), name="events_indexes_positive"),
            models.CheckConstraint(
                condition=(Q(event_type="draw", draw_index__gt=0, source__in=["main", "bonus"],
                             source_index__gt=0, rarity_id__isnull=False) |
                           Q(event_type="character_grant", draw_index__isnull=True,
                             source__isnull=True, source_index__isnull=True,
                             rarity_id__isnull=False, character_id__isnull=False)),
                name="events_type_fields_valid",
            ),
            models.CheckConstraint(
                condition=RawSQL(
                    "json_type(event_json, '$') IS 'object' "
                    "AND json_type(event_json, '$.event_format_version') IS 'integer' "
                    f"AND json_extract(event_json, '$.event_format_version') = {EVENT_FORMAT_VERSION} "
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
