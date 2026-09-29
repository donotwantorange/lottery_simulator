"""Task 14 checks; every scenario uses a subprocess and a physical temporary v5 DB."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = """
from dashboard.models import User
from dashboard.services.accounts import create_account, AccountError
from dashboard.services.pools import save_pool
from dashboard.services.runs import *
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json
admin = create_account(None, 'admin', '123456', admin=True, must_change_password=False)
alice = create_account(admin, 'alice', '123456', must_change_password=False)
bob = create_account(admin, 'bob', '123456', must_change_password=False)
pool = save_pool(alice, read_config_json(DEFAULT_POOL_PATH))
payload = {'pool_id': str(pool.pk), 'expected_revision': 1, 'parameters': {
    'draws': 2, 'trials': 1, 'initial_pity': 0, 'initial_five_star_pity': 0,
    'seed': str(2**100+1), 'trace': False}}
"""


class OwnedJobTests(SimpleTestCase):
    def scenario(self, script):
        with TemporaryDirectory(prefix="lottery-owned-jobs-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/v5.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            for arguments, stdin in ((["migrate", "--noinput", "--verbosity", "0"], None),
                                     (["shell"], FIXTURE + script)):
                result = subprocess.run([sys.executable, str(ROOT / "manage.py"), *arguments],
                    input=stdin, text=True, cwd=ROOT, env=environment, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_frozen_owner_seed_and_private_mine(self):
        self.scenario("""
state = submit_job(alice, payload, synchronous=True)
assert state.status == 'completed' and state.history_saved
assert state.owner_id == str(alice.pk) and state.accepted_at
assert state.pool_source == {'id': str(pool.pk), 'revision': 1, 'name': pool.name,
                             'original_author': pool.original_author}
assert list_my_jobs(alice)['total'] == 1
assert list_my_jobs(bob)['items'] == [] and list_my_jobs(admin)['items'] == []
assert list_my_jobs(alice, page=2, page_size=1)['items'] == []
try: get_job_for_actor(bob, state.job_id)
except RunError as error: assert error.status == 404
else: raise AssertionError('任务越权读取')
assert job_detail(state)['parameters']['seed'] == str(2**100+1)
assert get_job_result_for_actor(alice, state.job_id)['seed'] == str(2**100+1)
assert get_job_result_for_actor(alice, state.job_id, serialize=False)['seed'] == 2**100+1
""")

    def test_revision_revocation_and_limits(self):
        self.scenario("""
from dashboard.limits import SimulationLimits
from dashboard.jobs import validate_parameters_for_active_rule
from dashboard.job_models import RunParameters
payload['expected_revision'] = 2
try: submit_job(alice, payload)
except RunError as error: assert error.code == 'revision_conflict'
else: raise AssertionError('旧池版本被接受')
payload['expected_revision'] = 1
User.objects.filter(pk=alice.pk).update(auth_version=2)
try: submit_job(alice, payload)
except AccountError: pass
else: raise AssertionError('撤销身份被接受')
parameters = RunParameters('rule1', 10000001, 1, 0, 1, False, pool_config=pool.config_json)
try: validate_parameters_for_active_rule(parameters, SimulationLimits.for_actor(bob))
except ValueError: pass
else: raise AssertionError('普通限额未执行')
validate_parameters_for_active_rule(parameters, SimulationLimits.for_actor(admin))
bonus_parameters = RunParameters('rule1', 30, 1, 0, 1, True, pool_config=pool.config_json)
try: validate_parameters_for_active_rule(bonus_parameters, SimulationLimits(max_records=39))
except ValueError: pass
else: raise AssertionError('赠送抽未计入Trace容量')
validate_parameters_for_active_rule(bonus_parameters, SimulationLimits(max_records=40))
""")

    def test_api_anonymous_and_stable_pagination(self):
        self.scenario("""
import json
from dataclasses import replace
from django.test import Client
from dashboard.job_models import write_json
from uuid import uuid4
first = submit_job(alice, payload, synchronous=True)
manager = get_manager()
second = replace(first, job_id=str(uuid4()), history_saved=False, run_id=None)
write_json(manager.root / second.job_id / 'state.json', second.to_dict())
client = Client(HTTP_HOST='localhost')
assert client.get('/api/v1/jobs/mine/').status_code == 401
assert client.post('/api/v1/auth/login/', json.dumps({'username':'alice','password':'123456'}),
                   content_type='application/json').status_code == 200
rows = client.get('/api/v1/jobs/mine/?page_size=1').json()
assert rows['total'] == 2 and rows['items'][0]['job_id'] == max(first.job_id, second.job_id)
assert rows['items'][0]['draws'] == '2' and 'result_path' not in rows['items'][0]
assert client.get('/api/v1/jobs/mine/?owner_id='+str(bob.pk)).status_code == 400
""")
