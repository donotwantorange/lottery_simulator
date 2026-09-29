"""Minimal checks for the isolated Django bootstrap."""

import os
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class BootstrapTests(unittest.TestCase):
    def test_production_debug_is_off_with_secret_and_explicit_paths(self):
        with TemporaryDirectory(prefix="lottery-production-settings-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "DJANGO_SETTINGS_MODULE": "webapp.settings", "LOTTERY_ENV": "production",
                "SECRET_KEY": "isolated-settings-test-key", "LOTTERY_DEBUG": "1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/history_v5.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            result = subprocess.run([sys.executable, "-c",
                "from django.conf import settings; assert settings.DEBUG is False; "
                "assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE"],
                cwd=REPO_ROOT, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(Path(environment["LOTTERY_DB_PATH"]).exists())

    def test_settings_resolve_explicit_database_path_without_creating_it(self):
        with TemporaryDirectory(prefix="lottery-bootstrap-") as data_dir:
            database = Path(data_dir) / "history_v5.sqlite3"
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


if __name__ == "__main__":
    unittest.main()
