"""Minimal checks for the isolated Django bootstrap."""

import os
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from django.test import TestCase
from django.core.management import call_command
from django.core.management.base import CommandError
from unittest.mock import patch

from dashboard.management.commands.init_business_defaults import initialize_business_defaults
from dashboard.models import AppMeta, Pool, Rule, User


REPO_ROOT = Path(__file__).resolve().parents[2]


class BootstrapTests(unittest.TestCase):
    def test_production_debug_is_off_with_secret_and_explicit_paths(self):
        with TemporaryDirectory(prefix="lottery-production-settings-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "DJANGO_SETTINGS_MODULE": "webapp.settings", "LOTTERY_ENV": "production",
                "SECRET_KEY": "isolated-settings-test-key", "LOTTERY_DEBUG": "1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/history_v6.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            result = subprocess.run([sys.executable, "-c",
                "from django.conf import settings; assert settings.DEBUG is False; "
                "assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE"],
                cwd=REPO_ROOT, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(Path(environment["LOTTERY_DB_PATH"]).exists())

    def test_settings_resolve_explicit_database_path_without_creating_it(self):
        with TemporaryDirectory(prefix="lottery-bootstrap-") as data_dir:
            database = Path(data_dir) / "history_v6.sqlite3"
            environment = os.environ.copy()
            environment.update(
                DJANGO_SETTINGS_MODULE="webapp.settings",
                LOTTERY_DATA_DIR=data_dir,
                LOTTERY_DB_PATH=str(database),
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from django.conf import settings; "
                    "print(settings.DATABASES['default']['NAME'])",
                ],
                cwd=REPO_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(Path(result.stdout.strip()), database)
            self.assertFalse(database.exists())

    def test_default_paths_are_v6_without_creating_the_database(self):
        with TemporaryDirectory(prefix="lottery-v6-defaults-") as directory:
            environment = os.environ.copy()
            for key in ("LOTTERY_DB_PATH", "LOTTERY_JOBS_DIR", "LOTTERY_EXPORTS_DIR"):
                environment.pop(key, None)
            environment.update(DJANGO_SETTINGS_MODULE="webapp.settings", LOTTERY_DATA_DIR=directory)
            result = subprocess.run([sys.executable, "-c",
                "from django.conf import settings; "
                "assert settings.DATABASE_PATH.name == 'history_v6.sqlite3'; "
                "assert settings.JOBS_DIR.name == 'jobs_v6'; "
                "assert settings.EXPORTS_DIR.name == 'exports_v6'; "
                "print(settings.DATABASE_PATH)"], cwd=REPO_ROOT, env=environment,
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(Path(result.stdout.strip()).exists())


class BusinessDefaultsTests(TestCase):
    def test_init_admin_resources_are_shared_fixed_defaults_and_never_overwritten(self):
        User.objects.create_user(username="admin", username_key="admin", password="!",
                                 is_staff=True, is_superuser=True)
        initialize_business_defaults()
        rule = Rule.objects.get(name="zmd")
        pool = Pool.objects.get(name="默认角色池")
        self.assertEqual(pool.rule_id, rule.pk)
        before = rule.config_json
        rule.config_json = {"edited": True}
        rule.save(update_fields=["config_json"])
        initialize_business_defaults()
        rule.refresh_from_db()
        self.assertEqual(rule.config_json, {"edited": True})
        self.assertEqual(AppMeta.objects.get(key="initialized").value, {"version": 6})
        self.assertEqual(before["id"], str(rule.pk))

        other_rule = Rule.objects.create(name="其他", name_key="其他", kind="public", owner=None,
            visibility="public", original_author="原作者", config_json={})
        pool.rule = other_rule
        pool.save(update_fields=["rule"])
        initialize_business_defaults()
        pool.refresh_from_db()
        self.assertEqual(pool.rule_id, other_rule.pk)

    def test_init_business_defaults_requires_admin_and_rolls_back_name_conflict(self):
        with self.assertRaises(CommandError):
            initialize_business_defaults()
        self.assertFalse(Rule.objects.exists())
        User.objects.create_user(username="admin", username_key="admin", password="!",
                                 is_staff=True, is_superuser=True)
        Rule.objects.create(name="zmd", name_key="zmd", kind="public", owner=None,
            visibility="public", original_author="someone", config_json={})
        with self.assertRaises(CommandError):
            call_command("init_business_defaults")
        self.assertFalse(Pool.objects.exists())
        self.assertFalse(AppMeta.objects.filter(key="initialized").exists())

    def test_init_admin_rolls_back_failed_defaults_and_rejects_repeat(self):
        with patch("dashboard.management.commands.init_admin.getpass",
                   side_effect=["abcdef", "abcdef"]), patch(
                "dashboard.management.commands.init_admin.initialize_business_defaults",
                side_effect=CommandError("测试失败")):
            with self.assertRaises(CommandError):
                call_command("init_admin", username="admin")
        self.assertFalse(User.objects.exists())
        self.assertFalse(Rule.objects.exists())
        self.assertFalse(Pool.objects.exists())
        self.assertFalse(AppMeta.objects.exists())
        with patch("dashboard.management.commands.init_admin.getpass",
                   side_effect=["abcdef", "abcdef"]):
            call_command("init_admin", username="admin")
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
        with self.assertRaises(CommandError):
            call_command("init_admin", username="admin")


if __name__ == "__main__":
    unittest.main()
