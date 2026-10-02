from pathlib import Path
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.test import Client, TestCase, override_settings

from dashboard.models import AppMeta, ExperimentConfig, Pool, Rule, User
from dashboard.services.accounts import AccountError, DeleteIncomplete, create_account, delete_account
from dashboard.services.pools import save_pool
from dashboard.services.rules import save_rule
from tests.fixtures_rules import default_pool, default_rule


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
        self.public_rule = save_rule(self.admin, {**default_rule().to_dict(),
            "kind": Rule.PUBLIC, "visibility": Rule.PUBLIC})

    def save_pool(self, actor, rule, name, *, kind=Pool.PRIVATE, original_author=None):
        payload = default_pool().to_dict()
        payload.update(id=str(uuid4()), name=name,
                       rule_ref={"id": str(rule.pk), "name": rule.name})
        if original_author is not None:
            payload["original_author"] = original_author
        return save_pool(actor, {**payload, "kind": kind,
            "visibility": Pool.PUBLIC if kind == Pool.PUBLIC else Pool.HIDDEN},
            expected_rule_revision=rule.revision)

    def test_delete_keeps_public_authorship_and_other_users_hint(self):
        self.public_rule.original_author = "target"
        self.public_rule.config_json["original_author"] = "target"
        self.public_rule.save(update_fields=["original_author", "config_json"])
        public = self.save_pool(self.admin, self.public_rule, "公共资源", kind=Pool.PUBLIC,
                                original_author="target")
        private_rule = save_rule(self.target, default_rule().to_dict())
        private = self.save_pool(self.target, private_rule, "私有资源")
        config = ExperimentConfig.objects.create(owner=self.admin, name="别人的配置",
            name_key="别人的配置", pool=private, pool_name_hint=private.name, parameters_json={})
        delete_account(self.admin, self.target.pk)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())
        self.public_rule.refresh_from_db()
        self.assertEqual(self.public_rule.original_author, "target")
        public.refresh_from_db()
        self.assertEqual(public.original_author, "target")
        config.refresh_from_db()
        self.assertIsNone(config.pool_id)
        self.assertEqual(config.pool_name_hint, "私有资源")

    def test_external_rule_reference_blocks_before_deleting_and_keeps_all_pools(self):
        private_rule = save_rule(self.target, {**default_rule().to_dict(),
            "visibility": Rule.PUBLIC})
        own_pool = self.save_pool(self.target, private_rule, "我的池")
        external_pool = self.save_pool(self.admin, private_rule, "别人的池")
        with self.assertRaises(AccountError):
            delete_account(self.admin, self.target.pk)
        self.target.refresh_from_db()
        self.assertFalse(self.target.deleting)
        self.assertTrue(Rule.objects.filter(pk=private_rule.pk).exists())
        self.assertTrue(Pool.objects.filter(pk__in=[own_pool.pk, external_pool.pk]).count() == 2)

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
        save_rule(self.target, default_rule().to_dict())
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
        self.assertEqual(preview.json()["delete_impact"]["private_rules"], "1")
        self.assertEqual(preview.json()["delete_impact"]["other_users_rule_references"], "0")
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
        from dataclasses import replace
        from django.utils import timezone
        from dashboard.job_models import write_json
        from dashboard.services.runs import get_manager
        from tests.test_job_models import valid_state

        manager = get_manager()
        job_id = str(uuid4())
        directory = manager.root / job_id
        directory.mkdir()
        state = replace(valid_state(), job_id=job_id, status="running", pid=12345,
                        owner_id=str(self.target.pk), accepted_at=timezone.now().isoformat())
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
