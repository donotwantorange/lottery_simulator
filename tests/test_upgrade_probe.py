"""Real SQLite/file checks in temporary directories; never use deployed data."""

from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from dashboard.job_models import write_json
from scripts.upgrade_probe import check
from tests.test_job_models import valid_state


class UpgradeProbeTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.processes = self.root / 'proc'
        self.processes.mkdir()
        for version in (5, 6):
            with sqlite3.connect(self.root / f'history_v{version}.sqlite3') as db:
                db.executescript(f'PRAGMA user_version={version}; CREATE TABLE users (is_superuser, is_active, deleting); INSERT INTO users VALUES (1,1,0); CREATE TABLE app_meta (key);')
            (self.root / f'jobs_v{version}').mkdir()

    def test_quiet_v6_and_terminal_valid_state_pass(self):
        check(6, self.root, self.processes)
        state = replace(valid_state(), status='cancelled', phase=None)
        write_json(self.root / 'jobs_v6' / state.job_id / 'state.json', state.to_dict())
        check(6, self.root, self.processes)

    def test_active_corrupt_missing_and_unsafe_tasks_block(self):
        directory = self.root / 'jobs_v6' / str(uuid4())
        directory.mkdir()
        with self.assertRaises(OSError):
            check(6, self.root, self.processes)
        (directory / 'state.json').write_text('{bad')
        with self.assertRaises(ValueError):
            check(6, self.root, self.processes)
        state = replace(valid_state(), job_id=directory.name)
        write_json(directory / 'state.json', state.to_dict())
        with self.assertRaisesRegex(ValueError, '活动任务'):
            check(6, self.root, self.processes)
        write_json(directory / 'state.json', replace(state, status='cancelled', phase=None).to_dict())
        link = self.root / 'jobs_v6' / str(uuid4())
        link.symlink_to(directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            check(6, self.root, self.processes)

    def test_live_worker_and_unknown_root_entry_block(self):
        proc = self.processes / '123'
        proc.mkdir()
        (proc / 'cmdline').write_bytes(b'python\0manage.py\0run_job\0--job-dir\0/app/data/jobs_v6/x\0')
        with self.assertRaisesRegex(ValueError, 'worker'):
            check(6, self.root, self.processes)
        (proc / 'cmdline').write_bytes(b'gunicorn\0webapp.wsgi\0')
        (self.root / 'jobs_v6' / 'unknown').write_text('unknown')
        with self.assertRaises(ValueError):
            check(6, self.root, self.processes)

    def test_bad_schema_version_and_account_deletion_block(self):
        database = self.root / 'history_v6.sqlite3'
        with sqlite3.connect(database) as db:
            db.execute('PRAGMA user_version=5')
        with self.assertRaisesRegex(ValueError, '版本'):
            check(6, self.root, self.processes)
        with sqlite3.connect(database) as db:
            db.executescript("PRAGMA user_version=6; INSERT INTO app_meta VALUES ('account_deletion:x');")
        with self.assertRaisesRegex(ValueError, '删除清单'):
            check(6, self.root, self.processes)
        with sqlite3.connect(database) as db:
            db.executescript('DELETE FROM app_meta; UPDATE users SET deleting=1;')
        with self.assertRaisesRegex(ValueError, '删除中的账号'):
            check(6, self.root, self.processes)

    def test_v5_never_overwrites_existing_v6_material(self):
        with self.assertRaisesRegex(ValueError, '已有v6目标库'):
            check(5, self.root, self.processes)
        (self.root / 'history_v6.sqlite3').unlink()
        check(5, self.root, self.processes)
        (self.root / 'jobs_v6' / 'partial').write_text('partial')
        with self.assertRaisesRegex(ValueError, '目标任务'):
            check(5, self.root, self.processes)
