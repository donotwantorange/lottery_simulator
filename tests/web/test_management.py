from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4
import json

from django.test import Client, TestCase, override_settings

from dashboard.job_models import JobState, write_json
from dashboard.models import Pool, Rule
from dashboard.services.accounts import create_account
from dashboard.services.pools import save_pool
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, DEFAULT_RULE_PATH, read_config_json
from tests.test_job_models import valid_state


class ManagementAPITests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        settings = override_settings(JOBS_DIR=root / "jobs", EXPORTS_DIR=root / "exports")
        settings.enable()
        self.addCleanup(settings.disable)
        self.admin = create_account(None, "admin", "123456", admin=True, must_change_password=False)
        self.user = create_account(self.admin, "user", "123456", must_change_password=False)
        definition = read_config_json(DEFAULT_RULE_PATH)
        self.rule = Rule.objects.create(
            id=definition["id"], name=definition["name"], name_key=definition["name"],
            kind=Rule.PUBLIC, visibility=Rule.PUBLIC, original_author="原作者",
            algorithm=definition["algorithm"], config_json=definition,
        )

    def login_as(self, username):
        return self.client.post("/api/v1/auth/login/", data=json.dumps({
            "username": username, "password": "123456",
        }), content_type="application/json")

    def test_regular_user_cannot_list_all_tasks(self):
        self.assertEqual(self.login_as("user").status_code, 200)
        response = self.client.get("/api/v1/management/jobs/")
        self.assertEqual(response.status_code, 403)

    def test_admin_task_list_includes_owner_name_and_paginates(self):
        from dashboard.services.runs import get_manager

        manager = get_manager()
        manager.root.mkdir(parents=True, exist_ok=True)
        broken_dir = manager.root / str(uuid4())
        broken_dir.mkdir()
        (broken_dir / "state.json").write_text("{broken", encoding="utf-8")
        job_id = str(uuid4())
        job_dir = manager.root / job_id
        job_dir.mkdir()
        state = replace(valid_state(), job_id=job_id, status="completed",
            completed_units=valid_state().total_units, owner_id=str(self.user.pk),
            accepted_at="2026-09-28T12:00:00+00:00")
        write_json(job_dir / "state.json", state.to_dict())
        self.assertEqual(self.login_as("admin").status_code, 200)
        response = self.client.get("/api/v1/management/jobs/?page=1&page_size=1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["total"], body["page_size"]), (1, 1))
        self.assertEqual(body["items"][0]["owner_name"], "user")
        self.assertNotIn("path", body["items"][0])

    def test_delete_preview_counts_public_private_pools_but_not_system_pool(self):
        public = read_config_json(DEFAULT_POOL_PATH)
        public.update(name="系统公共", kind=Pool.PUBLIC, original_author="原作者")
        system_pool = save_pool(self.admin, public, expected_rule_revision=self.rule.revision)
        private = read_config_json(DEFAULT_POOL_PATH)
        private.update(name="公开的私有池", visibility=Pool.PUBLIC)
        save_pool(self.user, private, expected_rule_revision=self.rule.revision)

        self.assertEqual(self.login_as("admin").status_code, 200)
        response = self.client.get(f"/api/v1/management/users/{self.user.pk}/")
        self.assertEqual(response.status_code, 200)
        impact = response.json()["delete_impact"]
        self.assertEqual(impact["private_pools"], "1")
        self.assertEqual(impact["public_pools_preserved"], "1")
        self.assertEqual(impact["other_users_pool_references"], "0")
        self.assertEqual(impact["private_rules"], "0")
        self.assertEqual(impact["other_users_rule_references"], "0")
        self.assertEqual(impact["public_rules_preserved"], "1")
        system_pool.refresh_from_db()
        self.assertEqual(system_pool.original_author, "原作者")
