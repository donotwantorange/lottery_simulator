from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase, RequestFactory, override_settings

from dashboard.downloads import DownloadStream, download_trace
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

    def test_download_event_limit_accepts_10000_and_rejects_10001(self):
        actor = SimpleNamespace(pk=uuid4(), is_superuser=False)
        run_id = str(uuid4())
        class Reader:
            total = 10000
            def count_events(self, filters):
                return self.total
        reader = Reader()
        request = RequestFactory().post("/download/", data='{"filters":{}}',
                                        content_type="application/json")
        request._dont_enforce_csrf_checks = True
        export_dir = Path(self.directory.name) / "exports_v6"
        with override_settings(EXPORTS_DIR=export_dir), \
             patch("dashboard.downloads.SessionGate") as gate, \
             patch("dashboard.downloads._run", return_value=SimpleNamespace(result_json={})), \
             patch("dashboard.services.runs.get_trace_reader_for_actor", return_value=reader), \
             patch("dashboard.downloads.iter_jsonl", return_value=iter(['{"type":"metadata"}\n'])), \
             patch.dict(os.environ, {"LOTTERY_MAX_TRACE_DOWNLOAD_RECORDS": "10000"}):
            gate.return_value.actor.return_value = actor
            response = download_trace(request, run_id)
            self.assertEqual(response.status_code, 200)
            response.close()
            reader.total = 10001
            response = download_trace(request, run_id)
            self.assertEqual(response.status_code, 400)
            self.assertFalse(list(export_dir.glob("*.jsonl")))


class DownloadAPIIntegrationTests(SimpleTestCase):
    def test_owned_stream_stops_after_account_revocation(self):
        root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory(prefix="lottery-download-check-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_ALLOWED_HOSTS": "testserver,localhost,127.0.0.1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/history_v6.sqlite3",
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
from dashboard.services.rules import save_rule
from dashboard.services.runs import submit_job
from dashboard.api.errors import APIError
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, DEFAULT_RULE_PATH, read_config_json
admin = create_account(None, 'admin', '123456', admin=True, must_change_password=False)
alice = create_account(admin, 'alice', '123456', must_change_password=False)
bob = create_account(admin, 'bob', '123456', must_change_password=False)
rule = save_rule(admin, {**read_config_json(DEFAULT_RULE_PATH), 'kind': 'public'})
pool_raw = read_config_json(DEFAULT_POOL_PATH)
pool_raw['rule_ref'] = {'id': str(rule.pk), 'name': rule.name}
pool = save_pool(alice, pool_raw, expected_rule_revision=rule.revision)
state = submit_job(alice, {'pool_id': str(pool.pk), 'expected_pool_revision': pool.revision,
    'expected_rule_revision': rule.revision, 'initial_context': None,
    'parameters': {'draws': '2', 'trials': '1', 'initial_main_draws': '0',
    'initial_small_pity': {}, 'initial_big_pity': {'target_obtained': False, 'misses': '0'},
    'seed': '1267650600228229401496703205377', 'trace': True}}, synchronous=True)
assert state.status == 'completed', state.error
maintenance_output = Path(os.environ['LOTTERY_DATA_DIR']) / 'maintenance-trace.jsonl'
maintenance = subprocess.run([sys.executable, '-m', 'lottery_simulator', 'export-trace',
    '--database', os.environ['LOTTERY_DB_PATH'], '--run-id', str(state.run_id),
    '--output', str(maintenance_output)], capture_output=True, text=True)
assert maintenance.returncode == 0, maintenance.stdout + maintenance.stderr
assert maintenance_output.read_text(encoding='utf-8').count('"type": "event"') == 2
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
summary = client.get(f'/api/v1/runs/{state.run_id}/?download=json')
assert summary.status_code == 200 and 'attachment' in summary['Content-Disposition']
assert b'"seed": 1267650600228229401496703205377' in summary.content
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
