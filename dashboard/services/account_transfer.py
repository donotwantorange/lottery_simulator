"""Read-only v5 account snapshot and atomic import into an empty v6 database."""

from datetime import timezone as datetime_timezone
from pathlib import Path
from urllib.parse import quote
import sqlite3

from django.db import DatabaseError, connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone
from django.utils.dateparse import parse_datetime


V5_DASHBOARD_MIGRATION = ("dashboard", "0001_initial")
V6_DASHBOARD_MIGRATION = ("dashboard", "0002_independent_rules_v6")
V6_EMPTY_TABLES = (
    "users", "login_limits", "app_meta", "rules", "pools",
    "experiment_configs", "simulation_runs", "simulation_events",
    "django_session", "auth_group", "auth_group_permissions",
    "users_groups", "users_user_permissions", "django_admin_log",
)


def _sqlite_uri(path):
    return "file:" + quote(path.as_posix(), safe="/:\\") + "?mode=ro"


def _rows(cursor, table):
    return [dict(row) for row in cursor.execute(f'SELECT * FROM "{table}"')]


def _source_snapshot(path):
    try:
        db = sqlite3.connect(_sqlite_uri(path), uri=True)
    except sqlite3.Error:
        raise ValueError("无法只读打开v5来源数据库") from None
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        if db.execute("PRAGMA user_version").fetchone()[0] != 5:
            raise ValueError("来源数据库版本不是5")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("来源数据库完整性检查失败")
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"users", "login_limits", "app_meta", "django_migrations"}
        if not required.issubset(tables):
            raise ValueError("来源数据库不是完整的v5账号库")
        applied = {(row[0], row[1]) for row in db.execute(
            "SELECT app, name FROM django_migrations")}
        history = MigrationLoader(None, ignore_no_migrations=True)
        expected = set(history.graph.nodes) - {V6_DASHBOARD_MIGRATION}
        if applied != expected:
            raise ValueError("来源数据库迁移状态不是完整的v5历史结构")

        # Compare source columns against Django's immutable 0001 historical state.
        historical = history.project_state(sorted(expected))
        for model in historical.apps.get_models(include_auto_created=True):
            if not model._meta.managed:
                continue
            table = model._meta.db_table
            if table not in tables:
                raise ValueError("来源数据库不是完整的v5迁移结构")
            expected_columns = {field.column for field in model._meta.local_concrete_fields}
            actual = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
            if actual != expected_columns:
                raise ValueError("来源数据库结构与v5迁移不一致")

        users = _rows(db, "users")
        login_limits = _rows(db, "login_limits")
        manifests = [row for row in _rows(db, "app_meta")
                     if row["key"].startswith("account_deletion:")]
        if any(user["deleting"] for user in users) or manifests:
            raise ValueError("来源数据库存在未完成的账号删除，拒绝导入")
        if not any(user["is_active"] and user["is_superuser"] and not user["deleting"]
                   for user in users):
            raise ValueError("来源数据库没有可用管理员")
        return users, login_limits
    except sqlite3.Error:
        raise ValueError("无法读取完整的v5账号数据") from None
    finally:
        db.close()


def _validate_target(connection):
    if connection.vendor != "sqlite":
        raise ValueError("账号导入目标必须为SQLite v6数据库")
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA user_version")
        if cursor.fetchone()[0] != 6:
            raise ValueError("目标数据库版本不是6")
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    applied = set(loader.applied_migrations)
    expected = set(loader.graph.nodes)
    if V6_DASHBOARD_MIGRATION not in applied:
        raise ValueError("目标数据库尚未完整应用v6迁移")
    if applied != expected:
        raise ValueError("目标数据库迁移链不完整")
    if loader.detect_conflicts():
        raise ValueError("目标数据库迁移状态存在冲突")
    tables = set(connection.introspection.table_names())
    if not set(V6_EMPTY_TABLES).issubset(tables):
        raise ValueError("目标数据库缺少v6账号或业务表")
    state = loader.project_state()
    for model in state.apps.get_models(include_auto_created=True):
        if not model._meta.managed:
            continue
        if model._meta.db_table not in tables:
            raise ValueError("目标数据库缺少迁移表")
        expected_columns = {field.column for field in model._meta.local_concrete_fields}
        with connection.cursor() as cursor:
            actual = {row[1] for row in cursor.execute(
                f'PRAGMA table_info("{model._meta.db_table}")')}
        if actual != expected_columns:
            raise ValueError("目标数据库结构与完整v6迁移不一致")
    for table in V6_EMPTY_TABLES:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT 1 FROM "{table}" LIMIT 1')
            if cursor.fetchone():
                raise ValueError("目标数据库必须为空，拒绝覆盖已有数据")


def transfer_accounts(source: Path) -> dict:
    """Copy v5 scalar account and login-limit rows; never copy sessions/business data."""
    source = Path(source).expanduser().resolve()
    target_name = connections["default"].settings_dict["NAME"]
    if target_name == ":memory:":
        raise ValueError("账号导入目标必须是已迁移的文件数据库")
    target = Path(target_name).expanduser().resolve()
    if not source.is_file():
        raise ValueError("v5来源必须是数据库文件")
    if source == target or (target.exists() and source.samefile(target)):
        raise ValueError("来源和目标数据库不能是同一文件")
    if not target.is_file():
        raise ValueError("目标v6数据库不存在，请先完整运行migrate")
    users, limits = _source_snapshot(source)
    connection = connections["default"]
    _validate_target(connection)

    from dashboard.models import LoginLimit, User

    # Django stores SQLite datetimes in UTC; naive strings must not use local TIME_ZONE.
    for row in users + limits:
        for name in ("date_joined", "last_login", "window_start", "blocked_until"):
            if name in row and row[name] is not None:
                value = parse_datetime(row[name])
                if value is None:
                    raise ValueError("来源账号时间字段格式无效")
                row[name] = (timezone.make_aware(value, datetime_timezone.utc)
                             if timezone.is_naive(value) else value)

    fields = [field for field in User._meta.concrete_fields]
    names = [field.attname for field in fields]
    user_objects = [User(**{name: (row[name] + 1 if name == "auth_version" else row[name])
                            for name in names}) for row in users]
    limit_objects = [LoginLimit(scope=row["scope"], key=row["key"],
                                id=row["id"],
                                failure_count=row["failure_count"],
                                window_start=row["window_start"],
                                blocked_until=row["blocked_until"])
                     for row in limits]
    try:
        with transaction.atomic(using=connection.alias):
            _validate_target(connection)
            User.objects.using(connection.alias).bulk_create(user_objects)
            LoginLimit.objects.using(connection.alias).bulk_create(limit_objects)
    except (DatabaseError, ValueError):
        raise ValueError("账号导入失败，目标数据未更改") from None
    return {"users": len(user_objects), "login_limits": len(limit_objects)}
