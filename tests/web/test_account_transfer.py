"""Account transfer probes use independent, file-backed v5 and v6 databases."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = r'''
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import django
django.setup()
from django.contrib.auth.hashers import check_password, make_password
from django.db import connections, IntegrityError
from django.db.migrations.executor import MigrationExecutor
from dashboard.models import AppMeta, LoginLimit, Pool, Rule, SimulationRun, User
from dashboard.services.account_transfer import transfer_accounts
from django.contrib.sessions.models import Session

mode = os.environ["TRANSFER_PROBE"]
target_connection = connections["default"]
executor = MigrationExecutor(target_connection)
executor.migrate(executor.loader.graph.leaf_nodes())
source = Path(target_connection.settings_dict["NAME"]).with_name("history_v5.sqlite3")
source_config = target_connection.settings_dict.copy()
source_config["NAME"] = str(source)
connections.databases["transfer_source"] = source_config
source_connection = connections["transfer_source"]
executor = MigrationExecutor(source_connection)
targets = [node for node in executor.loader.graph.leaf_nodes()
           if node != ("dashboard", "0002_independent_rules_v6")]
targets.append(("dashboard", "0001_initial"))
executor.migrate(targets)
old_apps = MigrationExecutor(source_connection).loader.project_state(targets).apps
OldUser = old_apps.get_model("dashboard", "User")
OldUser.objects.using("transfer_source").create(
    id="bdc397ca-7b05-450a-90d2-fc0081173456", username="admin", username_key="admin",
    password=make_password("secret-password"), is_superuser=True, is_staff=True,
    is_active=(mode != "no_admin"), must_change_password=True, auth_version=9,
    deleting=(mode == "deleting"),
    first_name="保留名", last_name="保留姓", email="fixture@example.invalid",
    date_joined=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    last_login=datetime(2025, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
)
old_limit = old_apps.get_model("dashboard", "LoginLimit").objects.using(
    "transfer_source").create(scope="account", key="admin", failure_count=3,
    window_start=datetime(2024, 3, 4, 5, 6, 7, tzinfo=timezone.utc),
    blocked_until=datetime(2024, 3, 4, 5, 7, 7, tzinfo=timezone.utc))
old_apps.get_model("dashboard", "Pool").objects.using("transfer_source").create(
    name="old", name_key="old", kind="public", owner=None, visibility="public",
    original_author="old", rule_name="legacy", config_json={},
)
old_apps.get_model("sessions", "Session").objects.using("transfer_source").create(
    session_key="old-session", session_data="opaque",
    expire_date=datetime(2030, 1, 1, tzinfo=timezone.utc),
)
if mode == "manifest":
    old_apps.get_model("dashboard", "AppMeta").objects.using("transfer_source").create(
        key="account_deletion:bdc397ca-7b05-450a-90d2-fc0081173456", value=[])
source_connection.close()
del connections.databases["transfer_source"]
if hasattr(connections._connections, "transfer_source"):
    delattr(connections._connections, "transfer_source")

def read_source_users(path):
    db = sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)
    try:
        return db.execute("SELECT id, username, password, auth_version, deleting "
                          "FROM users ORDER BY id").fetchall()
    finally:
        db.close()

def read_source_snapshot(path):
    db = sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)
    try:
        return {table: db.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                for table in ("users", "login_limits", "app_meta", "pools", "django_session")}
    finally:
        db.close()

before_users = read_source_users(source)
if mode == "source_version":
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA user_version = 6")
if mode == "target_version":
    with target_connection.cursor() as cursor:
        cursor.execute("PRAGMA user_version = 5")
if mode == "incomplete_target":
    with target_connection.cursor() as cursor:
        cursor.execute("DELETE FROM django_migrations WHERE app='sessions'")
before = read_source_snapshot(source)
if mode == "samefile":
    try:
        transfer_accounts(target_connection.settings_dict["NAME"])
    except ValueError:
        pass
    else:
        raise AssertionError("same source and target was accepted")
elif mode in {"deleting", "manifest", "no_admin", "source_version", "target_version", "incomplete_target"}:
    try:
        transfer_accounts(source)
    except ValueError:
        pass
    else:
        raise AssertionError("unfinished account deletion was accepted")
    assert not User.objects.exists()
elif mode == "nonempty":
    User.objects.create(username="existing", username_key="existing", password="!")
    try:
        transfer_accounts(source)
    except ValueError:
        pass
    else:
        raise AssertionError("nonempty target was accepted")
    assert User.objects.count() == 1
elif mode == "atomic":
    from django.db.models.query import QuerySet
    bulk_create = QuerySet.bulk_create
    def fail_login_limit(self, *args, **kwargs):
        if self.model is LoginLimit:
            raise IntegrityError("injected")
        return bulk_create(self, *args, **kwargs)
    with patch.object(QuerySet, "bulk_create", fail_login_limit):
        try:
            transfer_accounts(source)
        except ValueError:
            pass
        else:
            raise AssertionError("injected write failure was ignored")
    assert not User.objects.exists() and not LoginLimit.objects.exists()
else:
    summary = transfer_accounts(source)
    user = User.objects.get(username_key="admin")
    assert summary == {"users": 1, "login_limits": 1}
    assert str(user.pk) == "bdc397ca-7b05-450a-90d2-fc0081173456"
    assert user.auth_version == 10 and user.must_change_password
    assert user.is_active and user.is_superuser and user.is_staff
    assert check_password("secret-password", user.password)
    assert LoginLimit.objects.get().pk == old_limit.pk
    assert LoginLimit.objects.get().failure_count == 3
    assert not AppMeta.objects.exists() and not Pool.objects.exists()
    assert not Rule.objects.exists() and not SimulationRun.objects.exists()
    assert not Session.objects.exists()
    with target_connection.cursor() as cursor:
        cursor.execute("SELECT * FROM users ORDER BY id")
        imported_values = read_source_snapshot(Path(target_connection.settings_dict["NAME"]))["users"][0]
        columns = [item[0] for item in cursor.description]
        original = dict(zip(columns, before["users"][0]))
        expected = {**original, "auth_version": original["auth_version"] + 1}
        assert dict(zip(columns, imported_values)) == expected, "完整账号标量发生变化"
        cursor.execute("SELECT * FROM login_limits ORDER BY id")
        assert read_source_snapshot(Path(target_connection.settings_dict["NAME"]))["login_limits"] == before["login_limits"], "登录防护标量发生变化"
    check = sqlite3.connect("file:" + source.as_posix() + "?mode=ro", uri=True)
    try:
        assert check.execute("SELECT count(*) FROM django_session").fetchone()[0] == 1
        assert check.execute("SELECT count(*) FROM pools").fetchone()[0] == 1
    finally:
        check.close()
    assert user.password not in str(summary)
    from django.test import Client
    from django.core.management import call_command
    client = Client()
    login = client.post("/api/v1/auth/login/", {"username": "admin", "password": "secret-password"}, content_type="application/json")
    assert login.status_code == 200, login.content
    assert client.session["auth_version"] == 10
    assert client.get("/api/v1/auth/me/").status_code == 200
    call_command("init_business_defaults", verbosity=0)
    assert Rule.objects.count() == 1 and Pool.objects.count() == 1
    assert not SimulationRun.objects.exists()
    assert not Path(os.environ["LOTTERY_JOBS_DIR"]).exists()

assert read_source_users(source) == before_users
assert read_source_snapshot(source) == before
'''


class AccountTransferTests(SimpleTestCase):
    def _run_probe(self, mode):
        with TemporaryDirectory(prefix=f"lottery-account-transfer-{mode}-") as directory:
            environment = os.environ.copy()
            environment.update({
                "PYTHONDONTWRITEBYTECODE": "1",
                "DJANGO_SETTINGS_MODULE": "webapp.settings",
                "LOTTERY_DB_PATH": str(Path(directory) / "history_v6.sqlite3"),
                "LOTTERY_DATA_DIR": directory,
                "LOTTERY_JOBS_DIR": str(Path(directory) / "jobs_v6"),
                "LOTTERY_EXPORTS_DIR": str(Path(directory) / "exports_v6"),
                "LOTTERY_ENV": "development",
                "LOTTERY_ALLOWED_HOSTS": "testserver,localhost,127.0.0.1",
                "TRANSFER_PROBE": mode,
            })
            result = subprocess.run([sys.executable, "-c", PROBE], cwd=REPO_ROOT,
                                    env=environment, capture_output=True, text=True,
                                    timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_imports_only_accounts_and_login_limits(self):
        self._run_probe("success")

    def test_refuses_deleting_users_and_any_deletion_manifest(self):
        self._run_probe("deleting")
        self._run_probe("manifest")

    def test_refuses_same_file_and_nonempty_target(self):
        self._run_probe("samefile")
        self._run_probe("nonempty")

    def test_rolls_back_accounts_when_login_limit_import_fails(self):
        self._run_probe("atomic")

    def test_refuses_unavailable_admin_and_abnormal_versions_or_migrations(self):
        for mode in ("no_admin", "source_version", "target_version", "incomplete_target"):
            with self.subTest(mode=mode):
                self._run_probe(mode)
