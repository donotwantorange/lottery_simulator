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

    def test_unavailable_state_has_safe_api_errors_and_no_deletion(self):
        from dashboard.services.runs import get_manager
        from dashboard.models import User, AppMeta
        manager = get_manager()
        state = replace(valid_state(), job_id=str(uuid4()), status='completed',
                        owner_id=str(self.user.pk))
        path = manager.root / state.job_id / 'state.json'
        write_json(path, state.to_dict())
        url = f'/api/v1/jobs/{state.job_id}/'
        with patch('dashboard.jobs.read_json', side_effect=OSError(61, 'private path and seed')) as read:
            self.assertEqual(self.client.get(url).status_code, 401)
            read.assert_not_called()
        self.assertEqual(self.login_as('admin').status_code, 200)
        with patch('dashboard.jobs.read_json', side_effect=OSError(61, 'private path and seed')), \
             patch('dashboard.jobs.time.sleep'), patch('shutil.rmtree') as cleanup:
            for endpoint in (url, url+'result/', url+'trace/',
                             '/api/v1/jobs/mine/', '/api/v1/jobs/busy/',
                             '/api/v1/management/jobs/', f'/api/v1/management/users/{self.user.pk}/'):
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 503, endpoint)
                self.assertEqual(response.json()['error'], {
                    'code': 'storage_busy', 'message': '任务状态暂不可用，请稍后重试', 'fields': {}})
            for action in ('cancel/', 'resave/'):
                self.assertEqual(self.client.post(url+action).status_code, 503)
            self.assertEqual(self.client.delete(f'/api/v1/management/users/{self.user.pk}/',
                data=json.dumps({'confirm': True}), content_type='application/json').status_code, 503)
            cleanup.assert_not_called()
            self.assertFalse(AppMeta.objects.filter(key=f'account_deletion:{self.user.pk}').exists())
            self.assertFalse(User.objects.get(pk=self.user.pk).deleting)
            self.assertFalse((path.parent/'cancel.request').exists())
        with patch('dashboard.jobs.read_json', side_effect=[FileNotFoundError(2, 'transient'), state.to_dict()]), \
             patch('dashboard.jobs.time.sleep'):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(f'/api/v1/jobs/{uuid4()}/').status_code, 404)
        self.assertEqual(self.login_as('user').status_code, 200)
        other = replace(state, owner_id=str(self.admin.pk))
        write_json(path, other.to_dict())
        self.assertEqual(self.client.get(url).status_code, 404)
        User.objects.filter(pk=self.user.pk).update(auth_version=2)
        with patch('dashboard.jobs.read_json') as read:
            self.assertEqual(self.client.get(url).status_code, 401)
            read.assert_not_called()

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
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'storage_busy')
        (broken_dir / 'state.json').unlink()
        broken_dir.rmdir()
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
