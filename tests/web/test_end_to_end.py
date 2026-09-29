"""Task 14 browser-facing backend flow on a physical, isolated v5 database."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class EndToEndTests(SimpleTestCase):
    def scenario(self, script):
        with TemporaryDirectory(prefix="lottery-acceptance-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/history_v5.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            for arguments, stdin in ((["migrate", "--noinput", "--verbosity", "0"], None),
                                     (["shell"], script)):
                result = subprocess.run([sys.executable, str(ROOT / "manage.py"), *arguments],
                    input=stdin, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_account_deletion_at_worker_commit_barrier(self):
        self.scenario('''
import time
from copy import deepcopy
from threading import Event, Thread
from unittest.mock import patch
from django.db import close_old_connections
from dashboard.models import DrawRecord, Pool, SimulationRun, User
from dashboard.repository import HistoryRepository
from dashboard.services.accounts import create_account, delete_account
from dashboard.services.pools import save_pool
from dashboard.services.runs import get_manager, submit_job
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json

admin = create_account(None, "admin", "123456", admin=True, must_change_password=False)
bob = create_account(admin, "bob", "123456", must_change_password=False)
system_pool = save_pool(admin, {**read_config_json(DEFAULT_POOL_PATH), "kind": "public"})
parameters = {"draws": 2, "trials": 1, "initial_pity": 0,
              "initial_five_star_pity": 0, "seed": "41", "trace": True}
bob_state = submit_job(bob, {"pool_id": str(system_pool.pk), "expected_revision": 1,
                           "parameters": parameters}, synchronous=True)
original_save = HistoryRepository.save_run
for committed_first in (False, True):
    target = create_account(admin, "target" + str(committed_first), "123456",
                            must_change_password=False)
    private_pool = save_pool(target, {**read_config_json(DEFAULT_POOL_PATH),
                                    "name": "私有池" + str(committed_first)})
    arrived, release = Event(), Event()
    errors, submitted = [], []
    payloads = []
    def save_at_barrier(repository, run_id, payload, **kwargs):
        payloads.append((run_id, deepcopy(payload)))
        if committed_first:
            result = original_save(repository, run_id, payload, **kwargs)
            assert SimulationRun.objects.filter(pk=run_id).exists()
        arrived.set()
        assert release.wait(10), "未释放worker提交屏障"
        return result if committed_first else original_save(repository, run_id, payload, **kwargs)
    def worker_run():
        close_old_connections()
        try:
            actor = User.objects.get(pk=target.pk)
            submitted.append(submit_job(actor, {"pool_id": str(private_pool.pk),
                "expected_revision": 1, "parameters": parameters}, synchronous=True))
        except BaseException as error:
            errors.append(error)
        finally:
            close_old_connections()
    def delete_run():
        close_old_connections()
        try:
            delete_account(User.objects.get(pk=admin.pk), target.pk)
        except BaseException as error:
            errors.append(error)
        finally:
            close_old_connections()
    worker = Thread(target=worker_run)
    deletion = Thread(target=delete_run)
    # The real worker runs in a thread so the barrier can intercept save_run;
    # only OS liveness detection is adapted to that thread's actual lifetime.
    with patch.object(HistoryRepository, "save_run", save_at_barrier), \
         patch("dashboard.jobs.JobManager._is_worker", side_effect=lambda pid, directory: worker.is_alive()):
        worker.start()
        assert arrived.wait(10), "worker未到达提交点"
        deletion.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if User.objects.filter(pk=target.pk, deleting=True).exists():
                break
            time.sleep(0.01)
        else:
            raise AssertionError("删除未提交deleting标记")
        release.set()
        worker.join(10)
        deletion.join(10)
    assert not worker.is_alive() and not deletion.is_alive()
    assert not errors, errors
    assert not User.objects.filter(pk=target.pk).exists()
    assert not Pool.objects.filter(pk=private_pool.pk).exists()
    assert not SimulationRun.objects.filter(owner_id=target.pk).exists()
    assert not DrawRecord.objects.filter(run_id=payloads[0][0]).exists()
    assert not (get_manager().root / payloads[0][0]).exists()
    assert SimulationRun.objects.filter(pk=bob_state.run_id, owner=bob).exists()
    assert Pool.objects.filter(pk=system_pool.pk, owner=None).exists()
    summary = dict(payloads[0][1], trace_enabled=False, record_count=0)
    from uuid import uuid4
    try:
        original_save(HistoryRepository(), str(uuid4()), summary)
    except ValueError:
        pass
    else:
        raise AssertionError("已删除账号结果重新导入")
''')

    def test_accepted_worker_survives_logout_disable_and_demotion(self):
        self.scenario('''
import json
from threading import Event, Thread
from unittest.mock import patch
from django.db import close_old_connections
from django.test import Client
from dashboard.models import SimulationRun, User
from dashboard.repository import HistoryRepository
from dashboard.services.accounts import create_account, update_account
from dashboard.services.pools import save_pool
from dashboard.services.runs import submit_job
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json

admin = create_account(None, "admin", "123456", admin=True, must_change_password=False)
pool = save_pool(admin, {**read_config_json(DEFAULT_POOL_PATH), "kind": "public"})
original_save = HistoryRepository.save_run
for operation in ("logout", "disable", "demote"):
    target = create_account(admin, operation, "123456", admin=True, must_change_password=False)
    client = Client(HTTP_HOST="localhost")
    assert client.post("/api/v1/auth/login/", data=json.dumps({"username": operation,
        "password": "123456"}), content_type="application/json").status_code == 200
    arrived, release = Event(), Event()
    errors, states = [], []
    def save_at_barrier(repository, run_id, payload, **kwargs):
        assert payload["limit_policy"]["max_draws"] is None
        arrived.set()
        assert release.wait(10)
        return original_save(repository, run_id, payload, **kwargs)
    def worker_run():
        close_old_connections()
        try:
            states.append(submit_job(User.objects.get(pk=target.pk), {
                "pool_id": str(pool.pk), "expected_revision": 1, "parameters": {
                    "draws": 2, "trials": 1, "initial_pity": 0,
                    "initial_five_star_pity": 0, "seed": "43", "trace": True}}, synchronous=True))
        except BaseException as error:
            errors.append(error)
        finally:
            close_old_connections()
    worker = Thread(target=worker_run)
    with patch.object(HistoryRepository, "save_run", save_at_barrier):
        worker.start()
        assert arrived.wait(10)
        if operation == "logout":
            assert client.post("/api/v1/auth/logout/").status_code == 200
        else:
            update_account(admin, target.pk, {"enabled": False} if operation == "disable" else {"role": "user"})
        assert client.get("/api/v1/auth/me/").status_code == 401
        release.set()
        worker.join(10)
    assert not worker.is_alive() and not errors, errors
    assert states[0].status == "completed" and states[0].history_saved
    assert states[0].limit_policy["max_draws"] is None
    assert SimulationRun.objects.filter(pk=states[0].run_id, owner_id=target.pk).exists()
''')

    def test_download_boundaries_disk_failure_active_cleanup_and_revocation(self):
        self.scenario('''
import errno
import json
import os
from pathlib import Path
from unittest.mock import patch
from django.contrib.sessions.models import Session
from django.test import Client
from dashboard.api.errors import APIError
from dashboard.downloads import cleanup_stale_exports
from dashboard.models import DrawRecord, SimulationRun, User
from dashboard.services.accounts import create_account
from dashboard.services.pools import save_pool
from dashboard.services.runs import submit_job
from dashboard.trace_store import TraceReader
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json

admin = create_account(None, "admin", "123456", admin=True, must_change_password=False)
alice = create_account(admin, "alice", "123456", must_change_password=False)
pool = save_pool(alice, read_config_json(DEFAULT_POOL_PATH))
state = submit_job(alice, {"pool_id": str(pool.pk), "expected_revision": 1, "parameters": {
    "draws": 1, "trials": 10001, "initial_pity": 0, "initial_five_star_pity": 0,
    "seed": "37", "trace": True}}, synchronous=True)
assert state.status == "completed" and state.history_saved
url = f"/api/v1/runs/{state.run_id}/download-trace/"
def login(username):
    client = Client(HTTP_HOST="localhost")
    assert client.post("/api/v1/auth/login/", data=json.dumps({"username": username,
        "password": "123456"}), content_type="application/json").status_code == 200
    return client
client = login("alice")
def download(actor, filters=None):
    return actor.post(url, data=json.dumps({"filters": filters or {}}),
                      content_type="application/json")
assert download(client).status_code == 400
response = download(client, {"trial_to": 10000})
assert response.status_code == 200
assert b"".join(response.streaming_content).count(b'"type": "record"') == 10000
response.close()
administrator = login("admin")
response = download(administrator)
assert response.status_code == 200
assert b"".join(response.streaming_content).count(b'"type": "record"') == 10001
response.close()
assert DrawRecord.objects.filter(run_id=state.run_id).count() == 10001

original_iterator = TraceReader.iter_records
def revoke_between_batches(reader, filters, *, batch_size):
    assert batch_size == 1000
    for index, record in enumerate(original_iterator(reader, filters, batch_size=batch_size)):
        if index == 1000:
            User.objects.filter(pk=alice.pk).update(is_active=False, auth_version=2)
        yield record
with patch.object(TraceReader, "iter_records", revoke_between_batches):
    assert download(client, {"trial_to": 10000}).status_code == 401
exports = Path(os.environ["LOTTERY_EXPORTS_DIR"])
assert not list(exports.glob("*.jsonl"))
User.objects.filter(pk=alice.pk).update(is_active=True)
client = login("alice")

with patch("dashboard.downloads.tempfile.NamedTemporaryFile", side_effect=OSError(errno.ENOSPC, "full")):
    assert download(client, {"trial_to": 1}).status_code == 503
assert SimulationRun.objects.filter(pk=state.run_id).exists()
assert DrawRecord.objects.filter(run_id=state.run_id).count() == 10001
response = download(client, {"trial_to": 10000})
assert response.status_code == 200
assert client.get("/api/v1/auth/me/").status_code == 200
assert download(administrator).status_code == 409
active = list(exports.glob("*.jsonl"))
assert len(active) == 1
os.utime(active[0], (1, 1))
cleanup_stale_exports(older_than_seconds=1)
assert active[0].exists()
response.close()
assert not list(exports.glob("*.jsonl"))

response = download(client, {"trial_to": 10000})
iterator = iter(response.streaming_content)
assert len(next(iterator)) == 64 * 1024
Session.objects.filter(session_key=client.session.session_key).delete()
try:
    next(iterator)
except APIError as error:
    assert error.code == "unauthenticated"
else:
    raise AssertionError("会话删除后继续传输")
response.close()
assert not list(exports.glob("*.jsonl"))
client = login("alice")
response = download(client, {"trial_to": 10000})
iterator = iter(response.streaming_content)
assert next(iterator)
assert client.post("/api/v1/auth/logout/").status_code == 200
try:
    next(iterator)
except APIError as error:
    assert error.code == "unauthenticated"
else:
    raise AssertionError("下载中退出后继续传输")
response.close()
client = login("alice")
response = download(client, {"trial_to": 10000})
iterator = iter(response.streaming_content)
assert next(iterator)
SimulationRun.objects.filter(pk=state.run_id).delete()
try:
    next(iterator)
except ValueError as error:
    assert getattr(error, "code", None) == "not_found"
else:
    raise AssertionError("历史删除后继续传输")
response.close()
assert not list(exports.glob("*.jsonl"))
''')

    def test_two_connections_admin_demotions_and_job_submissions(self):
        with TemporaryDirectory(prefix="lottery-admin-race-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/history_v5.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            migration = subprocess.run(
                [sys.executable, str(ROOT / "manage.py"), "migrate", "--noinput", "--verbosity", "0"],
                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(migration.returncode, 0, migration.stdout + migration.stderr)
            script = '''
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from dashboard.models import User
from dashboard.services.accounts import AccountError, create_account, update_account

first = create_account(None, "first", "123456", admin=True, must_change_password=False)
second = create_account(first, "second", "123456", admin=True, must_change_password=False)
barrier = Barrier(2)
def demote(user_id):
    close_old_connections()
    try:
        actor = User.objects.get(pk=user_id)
        barrier.wait(timeout=5)
        update_account(actor, user_id, {"role": "user"})
        return "demoted"
    except AccountError:
        return "rejected"
    finally:
        close_old_connections()
with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(demote, (first.pk, second.pk)))
assert sorted(results) == ["demoted", "rejected"], results
assert User.objects.filter(is_superuser=True, is_active=True, deleting=False).count() == 1
remaining = User.objects.get(is_superuser=True)
update_account(remaining, User.objects.get(is_superuser=False).pk, {"role": "admin"})
barrier = Barrier(2)
def disable(user_id):
    close_old_connections()
    try:
        actor = User.objects.get(pk=user_id)
        barrier.wait(timeout=5)
        update_account(actor, user_id, {"enabled": False})
        return "disabled"
    except AccountError:
        return "rejected"
    finally:
        close_old_connections()
with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(disable, (first.pk, second.pk)))
assert sorted(results) == ["disabled", "rejected"], results
assert User.objects.filter(is_superuser=True, is_active=True, deleting=False).count() == 1

from types import SimpleNamespace
from unittest.mock import patch
from dashboard.services.pools import save_pool
from dashboard.services.runs import RunError, list_my_jobs, submit_job
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json
admin = User.objects.get(is_superuser=True, is_active=True)
alice = create_account(admin, "alice", "123456", must_change_password=False)
bob = create_account(admin, "bob", "123456", must_change_password=False)
pool = save_pool(admin, {**read_config_json(DEFAULT_POOL_PATH), "kind": "public"})
payload = {"pool_id": str(pool.pk), "expected_revision": 1, "parameters": {
    "draws": 2, "trials": 1, "initial_pity": 0, "initial_five_star_pity": 0,
    "seed": "31", "trace": False}}
barrier = Barrier(2)
def submit(user_id):
    close_old_connections()
    try:
        actor = User.objects.get(pk=user_id)
        barrier.wait(timeout=5)
        return ("accepted", user_id, submit_job(actor, payload).job_id)
    except RunError as error:
        return (error.code, user_id, None)
    finally:
        close_old_connections()
with patch("dashboard.jobs.subprocess.Popen", return_value=SimpleNamespace(pid=12345)), \
     patch("dashboard.jobs.JobManager._is_worker", return_value=True), \
     patch("dashboard.jobs.JobManager._reap"):
    with ThreadPoolExecutor(max_workers=2) as executor:
        submissions = list(executor.map(submit, (alice.pk, bob.pk)))
    assert sorted(row[0] for row in submissions) == ["accepted", "system_busy"], submissions
    winner = next(row for row in submissions if row[0] == "accepted")
    assert list_my_jobs(User.objects.get(pk=winner[1]))["items"][0]["job_id"] == winner[2]
    loser = next(row for row in submissions if row[0] == "system_busy")
    assert list_my_jobs(User.objects.get(pk=loser[1]))["items"] == []
'''
            result = subprocess.run(
                [sys.executable, str(ROOT / "manage.py"), "shell"], input=script,
                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_init_login_config_job_history_trace_download_and_isolation(self):
        with TemporaryDirectory(prefix="lottery-e2e-") as directory:
            environment = {**os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_DATA_DIR": directory,
                "LOTTERY_DB_PATH": directory + "/history_v5.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs",
                "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            migration = subprocess.run(
                [sys.executable, str(ROOT / "manage.py"), "migrate", "--noinput", "--verbosity", "0"],
                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(migration.returncode, 0, migration.stdout + migration.stderr)
            script = '''
import json
import os
import time
from pathlib import Path
from unittest.mock import patch
from django.core.management import call_command
from django.test import Client
from dashboard.models import Pool, SimulationRun, User
from dashboard.services.accounts import create_account
from dashboard.services.pools import save_pool
from dashboard.services.runs import submit_job
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json

with patch("dashboard.management.commands.init_admin.getpass", side_effect=["123456", "123456"]):
    call_command("init_admin", username="admin")
admin = User.objects.get(username="admin")
alice = create_account(admin, "alice", "123456", must_change_password=False)
bob = create_account(admin, "bob", "123456", must_change_password=False)
pool = Pool.objects.get(kind="public")
assert pool.owner_id is None

client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
login_url = "/api/v1/auth/login/"
token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
def post(url, body):
    return client.post(url, data=json.dumps(body), content_type="application/json",
                       HTTP_X_CSRFTOKEN=token)
assert post(login_url, {"username": "alice", "password": "123456"}).status_code == 200
token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
assert client.get("/api/v1/pools/").status_code == 200
parameters = {"draws": "2", "trials": "1", "initial_pity": 0,
              "initial_five_star_pity": 0, "seed": "900719925474099312345", "trace": True}
config = post("/api/v1/experiment-configs/", {"name": "端到端实验",
    "pool_ref": {"id": str(pool.pk), "name": pool.name}, "parameters": parameters})
assert config.status_code == 201, config.content
assert config.json()["owner_id"] == str(alice.pk)
accepted = post("/api/v1/jobs/", {"pool_id": str(pool.pk), "expected_revision": pool.revision,
    "parameters": parameters})
assert accepted.status_code == 202, accepted.content
job_id = accepted.json()["job_id"]
assert any(row["job_id"] == job_id for row in client.get("/api/v1/jobs/mine/").json()["items"])
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    detail = client.get(f"/api/v1/jobs/{job_id}/")
    assert detail.status_code == 200, detail.content
    if detail.json()["status"] in {"completed", "failed", "cancelled"}:
        break
    time.sleep(0.05)
else:
    raise AssertionError("任务未在期限内完成")
assert detail.json()["status"] == "completed", detail.content
assert detail.json()["history_saved"], detail.content
run_id = detail.json()["run_id"]
job_result = client.get(f"/api/v1/jobs/{job_id}/result/")
assert job_result.status_code == 200 and job_result.json()["pool_name_snapshot"] == pool.name
history = client.get("/api/v1/runs/")
assert history.status_code == 200 and history.json()["total"] == 1, history.content
run = client.get(f"/api/v1/runs/{run_id}/")
assert run.status_code == 200 and run.json()["seed"] == parameters["seed"], run.content
assert run.json()["pool_name_snapshot"] == pool.name
trace = client.get(f"/api/v1/runs/{run_id}/trace/")
assert trace.status_code == 200 and trace.json()["total"] == 2, trace.content
assert client.post(f"/api/v1/runs/{run_id}/download-trace/",
                   data=json.dumps({"filters": {}}), content_type="application/json").status_code == 403
download = post(f"/api/v1/runs/{run_id}/download-trace/", {"filters": {}})
assert download.status_code == 200 and download.streaming, download.content
body = b"".join(download.streaming_content)
download.close()
assert body.count(b'"type": "record"') == 2
assert not list(Path(os.environ["LOTTERY_EXPORTS_DIR"]).glob("*.jsonl"))

other = Client(HTTP_HOST="localhost")
assert other.post(login_url, data=json.dumps({"username": "bob", "password": "123456"}),
                  content_type="application/json").status_code == 200
assert other.get("/api/v1/runs/").json()["total"] == 0
assert other.get(f"/api/v1/runs/{run_id}/").status_code == 404
assert other.post(f"/api/v1/runs/{run_id}/download-trace/", data=json.dumps({"filters": {}}),
                  content_type="application/json").status_code == 404
assert SimulationRun.objects.filter(pk=run_id, owner=alice).exists()

pool_document = read_config_json(DEFAULT_POOL_PATH)
pool_document.update(name="稍后隐藏的池", visibility="public")
shared_pool = save_pool(alice, pool_document)
assert other.get(f"/api/v1/pools/{shared_pool.pk}/").status_code == 200
bob_state = submit_job(bob, {"pool_id": str(shared_pool.pk), "expected_revision": 1,
    "parameters": {"draws": 2, "trials": 1, "initial_pity": 0,
                   "initial_five_star_pity": 0, "seed": "23", "trace": True}}, synchronous=True)
assert bob_state.history_saved
save_pool(alice, {**pool_document, "visibility": "hidden"}, pool_id=shared_pool.pk,
          expected_revision=shared_pool.revision)
assert other.get(f"/api/v1/pools/{shared_pool.pk}/").status_code == 404
assert other.post("/api/v1/jobs/", data=json.dumps({"pool_id": str(shared_pool.pk),
    "expected_revision": 2, "parameters": parameters}), content_type="application/json").status_code == 404
assert other.get(f"/api/v1/runs/{bob_state.run_id}/").status_code == 200
snapshot = other.post(f"/api/v1/runs/{bob_state.run_id}/download-trace/",
    data=json.dumps({"filters": {}}), content_type="application/json")
assert snapshot.status_code == 200 and snapshot.streaming
assert b'"type": "record"' in b"".join(snapshot.streaming_content)
snapshot.close()
'''
            result = subprocess.run(
                [sys.executable, str(ROOT / "manage.py"), "shell"], input=script,
                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=45,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
