import errno
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from dashboard.job_models import write_json
from dashboard.jobs import JobManager, JobStateUnavailable
from tests.test_job_models import valid_state


class JobStateReadingTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.manager = JobManager(root / 'jobs', root / 'history.sqlite3')
        self.state = replace(valid_state(), job_id=str(uuid4()))
        self.path = self.manager.root / self.state.job_id
        write_json(self.path / 'state.json', self.state.to_dict())

    def test_transient_read_recovers_with_bounded_backoff(self):
        for error in (FileNotFoundError(errno.ENOENT, 'missing'), FileNotFoundError('missing'),
                      OSError(errno.ENODATA, 'no data')):
            with self.subTest(error=type(error)), patch('dashboard.jobs.read_json',
                    side_effect=[error, error, self.state.to_dict()]) as read, \
                    patch('dashboard.jobs.time.sleep') as sleep:
                self.assertEqual(self.manager.get(self.state.job_id), self.state)
                self.assertEqual(read.call_count, 3)
                self.assertEqual([call.args[0] for call in sleep.call_args_list], [.01, .02])

    def test_persistent_errors_and_bad_metadata_fail_closed(self):
        for error, attempts in ((OSError(errno.ENODATA, 'no data'), 3),
                                (PermissionError(errno.EACCES, 'permission'), 1),
                                (ValueError('bad JSON'), 1)):
            with self.subTest(error=type(error)), patch('dashboard.jobs.read_json', side_effect=error) as read, \
                    patch('dashboard.jobs.time.sleep'):
                with self.assertRaises(JobStateUnavailable):
                    self.manager.get(self.state.job_id)
                self.assertEqual(read.call_count, attempts)
        with patch('pathlib.Path.lstat', side_effect=PermissionError(errno.EACCES, 'private')):
            with self.assertRaises(JobStateUnavailable):
                self.manager.get(self.state.job_id)

    def test_missing_directory_is_absent_but_missing_state_is_unavailable(self):
        with patch('dashboard.jobs.time.sleep'):
            self.assertIsNone(self.manager.get(str(uuid4())))
            self.assertIsNone(self.manager.get('../escape'))
            (self.path / 'state.json').unlink()
            with self.assertRaises(JobStateUnavailable):
                self.manager.states()
            with self.assertRaises(JobStateUnavailable):
                self.manager.get_active()

    def test_corrupt_wrong_id_and_unsafe_paths_are_not_skipped(self):
        (self.path / 'state.json').write_text('{broken', encoding='utf-8')
        with self.assertRaises(JobStateUnavailable):
            self.manager.states()
        write_json(self.path / 'state.json', replace(self.state, job_id=str(uuid4())).to_dict())
        with self.assertRaises(JobStateUnavailable):
            self.manager.get(self.state.job_id)
        write_json(self.path / 'state.json', self.state.to_dict())
        link = self.manager.root / str(uuid4())
        link.symlink_to(self.path, target_is_directory=True)
        with self.assertRaises(JobStateUnavailable):
            self.manager.states()
        link.unlink()
        state_path = self.path / 'state.json'
        state_path.unlink()
        state_path.symlink_to(self.manager.root / 'outside.json')
        with self.assertRaises(JobStateUnavailable):
            self.manager.get(self.state.job_id)

    def test_enumerated_state_transient_read_recovers(self):
        (self.manager.root / 'not-a-job').mkdir()
        with patch('dashboard.jobs.read_json', side_effect=[
                OSError(errno.ENODATA, 'no data'), self.state.to_dict()]), \
                patch('dashboard.jobs.time.sleep'):
            self.assertEqual(self.manager.states(), [self.state])

    def test_absence_confirmation_metadata_error_is_unavailable(self):
        metadata = self.path.stat()
        with patch('pathlib.Path.lstat', side_effect=[metadata,
                FileNotFoundError(2, 'missing'), FileNotFoundError(2, 'missing'),
                FileNotFoundError(2, 'missing'), PermissionError(13, 'unknown')]), \
                patch('dashboard.jobs.time.sleep'):
            with self.assertRaises(JobStateUnavailable):
                self.manager.get(self.state.job_id)
