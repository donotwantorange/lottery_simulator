"""Task 14 history acceptance; all database and job paths are isolated in /tmp."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = """
from dashboard.models import User, SimulationRun, DrawRecord
from dashboard.services.accounts import create_account
from dashboard.services.pools import save_pool
from dashboard.services.runs import *
from dashboard.trace_store import TraceFilter
from dashboard.repository import HistoryRepository
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json
admin = create_account(None, 'admin', '123456', admin=True, must_change_password=False)
alice = create_account(admin, 'alice', '123456', must_change_password=False)
bob = create_account(admin, 'bob', '123456', must_change_password=False)
pool = save_pool(alice, read_config_json(DEFAULT_POOL_PATH))
payload = {'pool_id': str(pool.pk), 'expected_revision': 1, 'parameters': {
    'draws': 2, 'trials': 1, 'initial_pity': 0, 'initial_five_star_pity': 0,
    'seed': str(2**100+1), 'trace': True}}
state = submit_job(alice, payload, synchronous=True)
assert state.status == 'completed' and state.history_saved
"""


class OwnedRunTests(SimpleTestCase):
    def scenario(self, script):
        with TemporaryDirectory(prefix="lottery-owned-runs-") as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                "LOTTERY_DATA_DIR": directory, "LOTTERY_DB_PATH": directory + "/v5.sqlite3",
                "LOTTERY_JOBS_DIR": directory + "/jobs", "LOTTERY_EXPORTS_DIR": directory + "/exports"}
            for arguments, stdin in ((["migrate", "--noinput", "--verbosity", "0"], None),
                                     (["shell"], FIXTURE + script)):
                result = subprocess.run([sys.executable, str(ROOT / "manage.py"), *arguments],
                    input=stdin, text=True, cwd=ROOT, env=environment, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_transaction_trace_and_owner_isolation(self):
        self.scenario("""
run = get_run_for_actor(alice, state.run_id)
assert run.seed == str(2**100+1) and run.pool_revision_snapshot == 1
assert DrawRecord.objects.filter(run=run).count() == 2
rows = query_trace_for_actor(alice, run.pk, TraceFilter())
assert rows['total'] == 2 and len(rows['items']) == 2
for access in (lambda: get_run_for_actor(bob, run.pk),
               lambda: get_trace_reader_for_actor(bob, run.pk),
               lambda: resave_job_for_actor(bob, state.job_id)):
    try: access()
    except RunError as error: assert error.status == 404
    else: raise AssertionError('历史或重存越权')
assert list_runs_for_actor(bob)['items'] == []
assert get_run_for_actor(admin, run.pk).pk == run.pk
""")

    def test_accepted_owner_disable_allowed_but_deleting_refused(self):
        self.scenario("""
from uuid import uuid4
summary = dict(get_run_for_actor(alice, state.run_id).result_json)
summary['trace_enabled'] = False
summary['record_count'] = 0
User.objects.filter(pk=alice.pk).update(is_active=False, auth_version=2)
repository = HistoryRepository()
new_id = str(uuid4())
repository.save_run(new_id, summary)
assert SimulationRun.objects.filter(pk=new_id, owner_id=alice.pk).exists()
User.objects.filter(pk=alice.pk).update(deleting=True)
rejected = str(uuid4())
try: repository.save_run(rejected, summary)
except ValueError: pass
else: raise AssertionError('删除中账号被重新导入')
assert not SimulationRun.objects.filter(pk=rejected).exists()
""")

    def test_trace_failure_rolls_back_history(self):
        self.scenario("""
from uuid import uuid4
from unittest.mock import patch
from lottery_simulator.engine import SimulationCancelled
summary = get_run_for_actor(alice, state.run_id).result_json
reader = get_trace_reader_for_actor(alice, state.run_id)
from dashboard.trace_store import TraceWriter
from dashboard.limits import TraceLimits
from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1
from lottery_simulator.rules.pool_config import PoolConfig
trace_path = get_manager().root / 'failed.sqlite3'
writer = TraceWriter(trace_path, limits=TraceLimits())
rule = Rule1(config=PoolConfig.from_dict(pool.config_json))
simulate(rule, 2, 1, int(summary['seed']), 0, collect_records=True, record_sink=writer.append)
writer.finish(trials=1, draws=2, initial_main_draws=0, bonus_per_trial=0)
writer.close()
rejected = str(uuid4())
try: HistoryRepository().save_run(rejected, summary, trace_path=trace_path,
                                  cancel_check=lambda: True)
except SimulationCancelled: pass
else: raise AssertionError('取消导入被保存')
assert not SimulationRun.objects.filter(pk=rejected).exists()
""")

    def test_resave_authorizer_runs_inside_write_transaction(self):
        self.scenario("""
from uuid import uuid4
from dashboard.services.accounts import AccountError
summary = dict(get_run_for_actor(alice, state.run_id).result_json)
summary['trace_enabled'] = False
summary['record_count'] = 0
rejected = str(uuid4())
def revoked():
    raise AccountError('请重新登录')
try: HistoryRepository().save_run(rejected, summary, authorize=revoked)
except AccountError: pass
else: raise AssertionError('重存未在写事务内重验授权')
assert not SimulationRun.objects.filter(pk=rejected).exists()
""")
