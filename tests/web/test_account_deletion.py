from pathlib import Path
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from dashboard.models import AppMeta, ExperimentConfig, User
from dashboard.services.accounts import AccountError, DeleteIncomplete, create_account, delete_account
from dashboard.services.pools import save_pool
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, read_config_json


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        settings = override_settings(JOBS_DIR=root / "jobs", EXPORTS_DIR=root / "exports")
        settings.enable()
        self.addCleanup(settings.disable)
        self.admin = create_account(None, "admin", "123456", admin=True, must_change_password=False)
        self.target = create_account(self.admin, "target", "123456", must_change_password=False)

    def test_delete_keeps_public_authorship_and_other_users_hint(self):
        public = read_config_json(DEFAULT_POOL_PATH)
        public.update(name="公共资源", kind="public", original_author="target")
        public = save_pool(self.admin, public)
        private = read_config_json(DEFAULT_POOL_PATH)
        private["name"] = "私有资源"
        private = save_pool(self.target, private)
        config = ExperimentConfig.objects.create(owner=self.admin, name="别人的配置",
            name_key="别人的配置", pool=private, pool_name_hint=private.name, parameters_json={})
        delete_account(self.admin, self.target.pk)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())
        public.refresh_from_db()
        self.assertEqual(public.original_author, "target")
        config.refresh_from_db()
        self.assertIsNone(config.pool_id)
        self.assertEqual(config.pool_name_hint, "私有资源")

    def test_self_delete_rejected(self):
        with self.assertRaises(AccountError):
            delete_account(self.admin, self.admin.pk)

    def test_cleanup_failure_keeps_deleting_and_retry_finishes(self):
        with patch("dashboard.downloads.cleanup_account_exports", side_effect=OSError("disk")):
            with self.assertRaises(DeleteIncomplete):
                delete_account(self.admin, self.target.pk)
        self.target.refresh_from_db()
        self.assertTrue(self.target.deleting)
        self.assertEqual(self.target.auth_version, 2)
        delete_account(self.admin, self.target.pk)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())

    def test_durable_manifest_survives_missing_state_on_retry(self):
        from uuid import uuid4
        from dashboard.services.runs import get_manager
        manager = get_manager()
        job_id = str(uuid4())
        directory = manager.root / job_id
        directory.mkdir()
        (directory / "result.json").touch()
        AppMeta.objects.create(key=f"account_deletion:{self.target.pk}", value=[job_id])
        with patch("shutil.rmtree", side_effect=OSError("partial cleanup")):
            with self.assertRaises(DeleteIncomplete):
                delete_account(self.admin, self.target.pk)
        delete_account(self.admin, self.target.pk)
        self.assertFalse(directory.exists())
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())

    def test_management_preview_confirmation_and_csrf(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        login = client.post("/api/v1/auth/login/", data=json.dumps({
            "username": "admin", "password": "123456"}), content_type="application/json",
            HTTP_X_CSRFTOKEN=token)
        self.assertEqual(login.status_code, 200)
        url = f"/api/v1/management/users/{self.target.pk}/"
        preview = client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["delete_impact"]["job_directories"], "0")
        self.assertEqual(client.delete(url, data=json.dumps({"confirm": True}),
            content_type="application/json").status_code, 403)
        token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.assertEqual(client.delete(url, data=json.dumps({"confirm": False}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 400)
        self.assertEqual(client.delete(url, data=json.dumps({"confirm": True}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())

    def test_worker_not_confirmed_stopped_keeps_deleting_for_retry(self):
        from uuid import uuid4
        from django.utils import timezone
        from dashboard.job_models import JobState, RunParameters, write_json
        from dashboard.limits import SimulationLimits
        from dashboard.services.runs import get_manager

        manager = get_manager()
        job_id = str(uuid4())
        directory = manager.root / job_id
        directory.mkdir()
        state = JobState(job_id, "running", RunParameters("rule1", 2, 1, 0, 17, False).to_dict(),
            0, 2, pid=12345, owner_id=str(self.target.pk),
            accepted_at=timezone.now().isoformat(),
            pool_source={"id": str(uuid4()), "revision": 1, "name": "池", "original_author": "作者"},
            limit_policy=SimulationLimits.for_actor(self.target).to_dict())
        write_json(directory / "state.json", state.to_dict())
        with patch("dashboard.jobs.JobManager._is_worker", return_value=True), \
             patch("dashboard.jobs.JobManager._stop_worker", return_value=False), \
             patch("time.monotonic", side_effect=[0, 4]):
            with self.assertRaises(DeleteIncomplete):
                delete_account(self.admin, self.target.pk)
        self.target.refresh_from_db()
        self.assertTrue(self.target.deleting)
        self.assertTrue((directory / "cancel.request").exists())
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())
        with patch("dashboard.jobs.JobManager._is_worker", return_value=False):
            delete_account(self.admin, self.target.pk)
        self.assertFalse(directory.exists())
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())
