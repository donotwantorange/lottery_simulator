from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from dashboard.downloads import DownloadStream
from dashboard.api.errors import APIError


class DownloadLifecycleTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "export.jsonl"
        self.path.touch()

    def test_close_before_iteration_cleans_file_and_slot(self):
        with patch("dashboard.downloads._slots") as slots:
            stream = DownloadStream(self.path, lambda: None)
            stream.close()
            stream.close()
            self.assertFalse(self.path.exists())
            slots.release.assert_called_once()

    def test_revocation_closes_without_appending_error(self):
        def deny():
            raise APIError("unauthenticated", "会话已失效", 401)
        with patch("dashboard.downloads._slots") as slots:
            stream = DownloadStream(self.path, deny)
            with self.assertRaises(APIError):
                next(stream)
            self.assertFalse(self.path.exists())
            slots.release.assert_called_once()

    def test_cleanup_failure_still_releases_slot(self):
        with patch("dashboard.downloads._slots") as slots:
            stream = DownloadStream(self.path, lambda: None)
            with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
                with self.assertLogs("dashboard.downloads", level="ERROR"):
                    stream.close()
            slots.release.assert_called_once()


class DownloadAPIIntegrationTests(SimpleTestCase):
    def test_owned_stream_stops_after_account_revocation(self):
        root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory(prefix="lottery-download-check-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/v5.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            migration = subprocess.run([sys.executable, str(root / "manage.py"),
                "migrate", "--noinput", "--verbosity", "0"], cwd=root, env=environment,
                capture_output=True, text=True)
            self.assertEqual(migration.returncode, 0, migration.stdout + migration.stderr)
            script = """
import json
import os
import subprocess
import sys
from pathlib import Path
from django.test import Client
from dashboard.models import User
from dashboard.services.accounts import create_account
from dashboard.services.pools import save_pool
from dashboard.services.runs import submit_job
from dashboard.api.errors import APIError
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json
admin = create_account(None, 'admin', '123456', admin=True, must_change_password=False)
alice = create_account(admin, 'alice', '123456', must_change_password=False)
bob = create_account(admin, 'bob', '123456', must_change_password=False)
pool = save_pool(alice, read_config_json(DEFAULT_POOL_PATH))
state = submit_job(alice, {'pool_id': str(pool.pk), 'expected_revision': 1,
    'parameters': {'draws': 2, 'trials': 1, 'initial_pity': 0,
    'initial_five_star_pity': 0, 'seed': '17', 'trace': True}}, synchronous=True)
maintenance_output = Path(os.environ['LOTTERY_DATA_DIR']) / 'maintenance-trace.jsonl'
maintenance = subprocess.run([sys.executable, '-m', 'lottery_simulator', 'export-trace',
    '--database', os.environ['LOTTERY_DB_PATH'], '--run-id', str(state.run_id),
    '--output', str(maintenance_output)], capture_output=True, text=True)
assert maintenance.returncode == 0, maintenance.stdout + maintenance.stderr
assert maintenance_output.read_text(encoding='utf-8').count('"type": "record"') == 2
url = f'/api/v1/runs/{state.run_id}/download-trace/'
anonymous = Client(HTTP_HOST='localhost')
assert anonymous.post(url, data=json.dumps({'filters': {}}), content_type='application/json').status_code == 401
other = Client(HTTP_HOST='localhost')
assert other.post('/api/v1/auth/login/', data=json.dumps({'username': 'bob', 'password': '123456'}),
    content_type='application/json').status_code == 200
assert other.post(url, data=json.dumps({'filters': {}}), content_type='application/json').status_code == 404
client = Client(HTTP_HOST='localhost')
assert client.post('/api/v1/auth/login/', data=json.dumps({'username': 'alice', 'password': '123456'}),
    content_type='application/json').status_code == 200
response = client.post(url, data=json.dumps({'filters': {}}), content_type='application/json')
assert response.status_code == 200 and response.streaming
iterator = iter(response.streaming_content)
first = next(iterator)
assert b'"type": "metadata"' in first
User.objects.filter(pk=alice.pk).update(is_active=False, auth_version=2)
try: next(iterator)
except APIError as error: assert error.code == 'unauthenticated'
else: raise AssertionError('撤权后继续传输')
response.close()
assert not list(Path(os.environ['LOTTERY_EXPORTS_DIR']).glob('*.jsonl'))
"""
            result = subprocess.run([sys.executable, str(root / "manage.py"), "shell"],
                input=script, cwd=root, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
