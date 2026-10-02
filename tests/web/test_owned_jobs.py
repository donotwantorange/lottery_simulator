"""Owned task behavior using isolated subprocesses and a temporary v6 database."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = """
from dashboard.models import Pool, User
from dashboard.services.accounts import create_account, AccountError
from dashboard.services.runs import *
from dashboard.management.commands.init_business_defaults import initialize_business_defaults
admin = create_account(None, 'admin', '123456', admin=True, must_change_password=False)
alice = create_account(admin, 'alice', '123456', must_change_password=False)
bob = create_account(admin, 'bob', '123456', must_change_password=False)
initialize_business_defaults()
pool = Pool.objects.get(kind=Pool.PUBLIC)
def make_payload(pool, *, draws='2', seed=str(2**100+1), trace=False):
    return {'pool_id': str(pool.pk), 'expected_pool_revision': pool.revision,
        'expected_rule_revision': pool.rule.revision, 'parameters': {
            'draws': draws, 'trials': '1', 'initial_main_draws': '0',
            'initial_small_pity': {},
            'initial_big_pity': {'target_obtained': False, 'misses': '0'},
            'seed': seed, 'trace': trace}, 'initial_context': None}
payload = make_payload(pool)
"""


class OwnedJobTests(SimpleTestCase):
    def scenario(self, script):
        script = FIXTURE + script
        with TemporaryDirectory(prefix="lottery-owned-jobs-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_ALLOWED_HOSTS": "testserver,localhost,127.0.0.1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/history_v6.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            for arguments, stdin in ((["migrate", "--noinput", "--verbosity", "0"], None),
                                     (["shell"], script)):
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
assert state.rule_source['id'] == str(pool.rule_id) and state.rule_source['revision'] == pool.rule.revision
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

    def test_preview_is_read_only_preserves_unset_seed_and_counts_exactly(self):
        self.scenario("""
from dashboard.services.runs import preview_submission, get_manager
import json
preview = preview_submission(alice, payload)
assert preview['parameters']['seed'] == str(2**100+1)
assert preview['counts']['per_trial']['main_draws'] == '2'
assert preview['counts']['total']['main_draws'] == '2'
assert preview['counts']['total']['trace_events'] == '0'
assert get_manager().get_active() is None
assert list_my_jobs(alice)['total'] == 0
unset = {**payload, 'parameters': {**payload['parameters'], 'seed': None}}
assert preview_submission(alice, unset)['parameters']['seed'] is None
assert get_manager().get_active() is None and list_my_jobs(alice)['total'] == 0
from django.test import Client
from django.utils import timezone
client = Client(); client.force_login(alice)
session = client.session; now = timezone.now().isoformat()
session['created_at'] = now; session['last_activity_at'] = now; session['auth_version'] = alice.auth_version; session.save()
response = client.post('/api/v1/jobs/preview/', data=json.dumps(payload), content_type='application/json')
assert response.status_code == 200, response.content
assert response.json()['counts']['total']['main_draws'] == '2'
assert get_manager().get_active() is None and list_my_jobs(alice)['total'] == 0
""")

    def test_preview_rechecks_context_revisions_and_next_periodic_trigger(self):
        self.scenario("""
from dashboard.services.pools import load_rule_definition, pool_document
from lottery_simulator.config_documents import load_pool_document
from lottery_simulator.rules.runtime import compile_pool, initial_context
from dashboard.services.runs import preview_submission, RunError, get_manager
compiled = compile_pool(load_rule_definition(pool.rule), load_pool_document(pool_document(pool)))
context = initial_context(compiled).to_dict()
long_history = {**payload, 'initial_context': context,
    'parameters': {**payload['parameters'], 'initial_main_draws': '250',
                   'initial_big_pity': {'target_obtained': True, 'misses': '0'}}}
result = preview_submission(alice, long_history)
assert result['next_triggers']['periodic_grant_main_draw'] == '480'
assert result['counts']['per_trial']['main_draws'] == '2'
obtained_at_zero = {**payload, 'initial_context': context,
    'parameters': {**payload['parameters'], 'initial_big_pity': {'target_obtained': True, 'misses': '0'}}}
try: preview_submission(alice, obtained_at_zero)
except RunError: pass
else: raise AssertionError('H=0已获得目标应拒绝')
stale = {**payload, 'expected_rule_revision': payload['expected_rule_revision'] + 1}
try: preview_submission(alice, stale)
except RunError as error: assert error.status == 409
else: raise AssertionError('规则修订变化应拒绝')
from dashboard.services.rules import save_rule
rule_raw = pool.rule.config_json.copy()
rule_raw['rarities'] = [dict(item) for item in rule_raw['rarities']]
top = max(rule_raw['rarities'], key=lambda item: item['rank'])
top['soft_enabled'] = False
top['hard_pity'] = 120
raised_rule = save_rule(admin, rule_raw, rule_id=pool.rule_id, expected_revision=pool.rule.revision)
pool.refresh_from_db(); raised_rule.refresh_from_db()
compiled_raised = compile_pool(load_rule_definition(raised_rule), load_pool_document(pool_document(pool)))
lowered = {'pool_id': str(pool.pk), 'expected_pool_revision': pool.revision,
    'expected_rule_revision': raised_rule.revision, 'initial_context': initial_context(compiled_raised).to_dict(),
    'parameters': {**payload['parameters'], 'initial_main_draws': '110',
        'initial_small_pity': {top['id']: '110'},
        'initial_big_pity': {'target_obtained': False, 'misses': '0'}}}
assert preview_submission(alice, lowered)['parameters']['initial_small_pity'][top['id']] == '110'
top['hard_pity'] = 100
updated_rule = save_rule(admin, rule_raw, rule_id=pool.rule_id, expected_revision=raised_rule.revision)
pool.refresh_from_db(); updated_rule.refresh_from_db()
compiled_new = compile_pool(load_rule_definition(updated_rule), load_pool_document(pool_document(pool)))
lowered['expected_rule_revision'] = updated_rule.revision
lowered['initial_context'] = initial_context(compiled_new).to_dict()
try: preview_submission(alice, lowered)
except RunError: pass
else: raise AssertionError('H=110不可携带已下降至100的最高档硬保底阈值')
assert get_manager().get_active() is None and list_my_jobs(alice)['total'] == 0
""")

    def test_revision_revocation_and_limits(self):
        self.scenario("""
from dashboard.limits import SimulationLimits
from dashboard.services.pools import load_rule_definition, pool_document
from lottery_simulator.config_documents import load_pool_document
from lottery_simulator.rules.definitions import BigInitial, ExperimentParameters
from lottery_simulator.rules.runtime import compile_pool
payload['expected_pool_revision'] = 2
try: submit_job(alice, payload)
except RunError as error: assert error.code == 'revision_conflict'
else: raise AssertionError('旧池版本被接受')
payload['expected_pool_revision'] = 1
User.objects.filter(pk=alice.pk).update(auth_version=2)
try: submit_job(alice, payload)
except AccountError: pass
else: raise AssertionError('撤销身份被接受')
compiled = compile_pool(load_rule_definition(pool.rule),
                        load_pool_document(pool_document(pool)))
parameters = ExperimentParameters(10000001, 1, 1, False, 0, {}, BigInitial(False, 0))
try: SimulationLimits.for_actor(bob).validate(compiled, parameters)
except ValueError: pass
else: raise AssertionError('普通限额未执行')
SimulationLimits.for_actor(admin).validate(compiled, parameters)
bonus_parameters = ExperimentParameters(30, 1, 1, True, 0, {}, BigInitial(False, 0))
try: SimulationLimits(max_records=39).validate(compiled, bonus_parameters)
except ValueError: pass
else: raise AssertionError('赠送抽未计入Trace容量')
SimulationLimits(max_records=40).validate(compiled, bonus_parameters)
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

    def test_accepted_rule_snapshot_stays_frozen_and_next_job_uses_new_revision(self):
        self.scenario("""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dashboard.models import SimulationRun
from dashboard.services.rules import rule_document, save_rule
from dashboard.worker import run
payload = make_payload(pool, draws='30', trace=True)
with patch('dashboard.jobs.subprocess.Popen', return_value=SimpleNamespace(pid=12345)), \
     patch('dashboard.jobs.JobManager._reap'), patch('dashboard.jobs.JobManager._is_worker', return_value=True):
    accepted = submit_job(alice, payload)
    assert list_my_jobs(alice)['items'][0]['job_id'] == accepted.job_id
definition = rule_document(pool.rule)
definition['bonus']['draws'] = 2
current_rule = save_rule(admin, definition, rule_id=pool.rule_id,
                         expected_revision=pool.rule.revision)
run(get_manager().root / accepted.job_id, get_manager().database_path)
finished = get_job_for_actor(alice, accepted.job_id)
assert finished.status == 'completed' and finished.history_saved, finished.to_dict()
old = SimulationRun.objects.get(pk=finished.run_id)
assert old.rule_revision_snapshot == 1 and old.event_count == 40
try: submit_job(alice, payload, synchronous=True)
except RunError as error: assert error.code == 'revision_conflict'
else: raise AssertionError('过期规则修订被接受')
payload['expected_rule_revision'] = current_rule.revision
next_job = submit_job(alice, payload, synchronous=True)
assert next_job.status == 'completed' and next_job.history_saved
new = SimulationRun.objects.get(pk=next_job.run_id)
assert new.rule_revision_snapshot == current_rule.revision and new.event_count == 32
old.refresh_from_db()
assert old.event_count == 40 and old.rule_config_json['bonus']['draws'] == 10
""")

    def test_cancelled_worker_leaves_no_partial_history_or_trace(self):
        self.scenario("""
from unittest.mock import patch
from dashboard.models import SimulationEvent, SimulationRun
from lottery_simulator.control import SimulationCancelled
payload = make_payload(pool, trace=True)
with patch('dashboard.worker.simulate', side_effect=SimulationCancelled):
    cancelled = submit_job(alice, payload, synchronous=True)
assert cancelled.status == 'cancelled' and not cancelled.history_saved
assert not SimulationRun.objects.filter(pk=cancelled.job_id).exists()
assert not SimulationEvent.objects.exists()
directory = get_manager().root / cancelled.job_id
assert not (directory / 'trace.sqlite3').exists() and not (directory / 'result.json').exists()
""")

    def test_computation_cancel_polling_detects_request_after_100ms(self):
        self.scenario("""
from unittest.mock import patch
from lottery_simulator.control import SimulationCancelled
def calculation(*args, cancel_check, **kwargs):
    directory = next(path for path in get_manager().root.iterdir() if path.is_dir())
    with patch('dashboard.worker.time.monotonic', return_value=1000) as clock:
        assert not cancel_check()
        (directory / 'cancel.request').touch()
        for _ in range(1000): assert not cancel_check()
        clock.return_value = 1000.11
        assert cancel_check()
        clock.return_value = 1000.12
        assert cancel_check()
    raise SimulationCancelled()
with patch('dashboard.worker.simulate', side_effect=calculation):
    cancelled = submit_job(alice, payload, synchronous=True)
assert cancelled.status == 'cancelled' and not cancelled.history_saved
""")
