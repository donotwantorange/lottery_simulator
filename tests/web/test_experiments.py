import json
from uuid import uuid4

from django.test import Client, TestCase
from django.utils import timezone

from dashboard.models import ExperimentConfig, Pool, User
from dashboard.services.accounts import AccountError, create_account
from dashboard.services.experiments import (
    ExperimentError, confirm_experiment_import, delete_experiment, export_experiment,
    import_preview, resolve_pool_reference, save_experiment, visible_experiments,
)
from dashboard.services.pools import save_pool
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, load_pool_document, read_config_json


PARAMETERS = {
    "draws": 10,
    "trials": 2,
    "initial_pity": 0,
    "initial_five_star_pity": 0,
    "seed": 17,
    "trace": False,
}


def pool_document(name):
    raw = read_config_json(DEFAULT_POOL_PATH)
    raw["name"] = name
    return load_pool_document(raw).to_dict()


def experiment_payload(name, pool):
    return {"name": name, "pool_ref": {"id": str(pool.pk), "name": pool.name},
            "parameters": dict(PARAMETERS)}


class ExperimentServiceTests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True,
                                    must_change_password=False)
        self.alice = create_account(self.admin, "alice", "123456", must_change_password=False)
        self.bob = create_account(self.admin, "bob", "123456", must_change_password=False)
        self.alice_pool = save_pool(self.alice, pool_document("Alice池"))
        self.admin_pool = save_pool(self.admin, pool_document("管理员隐藏池"))

    def test_user_scope_revision_and_export(self):
        config = save_experiment(self.alice, experiment_payload("我的实验", self.alice_pool))
        self.assertEqual(list(visible_experiments(self.bob)), [])
        self.assertEqual(list(visible_experiments(self.admin)), [config])
        saved = save_experiment(self.alice, experiment_payload("改名实验", self.alice_pool),
                                config_id=config.pk, expected_revision=1)
        self.assertEqual(saved.revision, 2)
        with self.assertRaises(ExperimentError) as conflict:
            save_experiment(self.alice, experiment_payload("冲突", self.alice_pool),
                            config_id=config.pk, expected_revision=1)
        self.assertEqual(conflict.exception.code, "revision_conflict")
        with self.assertRaises(ExperimentError) as forbidden_pool:
            save_experiment(self.admin, experiment_payload("代管越权", self.admin_pool),
                            config_id=config.pk, expected_revision=2)
        self.assertIn("配置所有者不可使用", str(forbidden_pool.exception))
        self.assertEqual(export_experiment(self.alice, config.pk,
                                           expected_revision=2)["pool_ref"]["id"],
                         str(self.alice_pool.pk))
        delete_experiment(self.alice, config.pk, expected_revision=2)
        self.assertFalse(ExperimentConfig.objects.filter(pk=config.pk).exists())

    def test_reference_states_and_two_phase_confirmation_rechecks_revision(self):
        missing_id = str(uuid4())
        self.assertEqual(resolve_pool_reference(
            self.bob, {"id": missing_id, "name": "Alice池"})["status"], "unavailable")
        shared = save_pool(self.alice, {**pool_document("同名"), "visibility": Pool.PUBLIC})
        another = save_pool(self.admin, {**pool_document("同名"), "kind": Pool.PUBLIC})
        matched = resolve_pool_reference(self.bob, {"id": str(shared.pk), "name": "旧名称"})
        self.assertEqual(matched["status"], "matched")
        blocked = resolve_pool_reference(self.bob, {"id": str(self.alice_pool.pk), "name": "同名"})
        self.assertEqual(blocked["status"], "unavailable")
        self.assertNotIn("Alice池", str(blocked))
        self.assertEqual(resolve_pool_reference(
            self.bob, {"id": missing_id, "name": "同名"})["status"], "select")
        self.assertNotEqual(shared.pk, another.pk)

        raw = {"format_version": 1, "name": "导入实验",
               "pool_ref": {"id": missing_id, "name": "Alice池"},
               "parameters": PARAMETERS}
        self.assertEqual(import_preview(self.bob, raw)["resolution"]["status"], "unavailable")
        pool = save_pool(self.admin, {**pool_document("公开池"), "kind": Pool.PUBLIC})
        preview = import_preview(self.bob, {**raw, "pool_ref": {"id": missing_id, "name": pool.name}})
        self.assertEqual(preview["resolution"]["status"], "confirm")
        with self.assertRaises(ExperimentError) as changed:
            confirm_experiment_import(self.bob, raw, pool_id=pool.pk,
                                      pool_revision=pool.revision + 1)
        self.assertEqual(changed.exception.code, "revision_conflict")
        imported = confirm_experiment_import(self.bob, raw, pool_id=pool.pk,
                                             pool_revision=pool.revision)
        self.assertEqual(imported.pool_id, pool.pk)

    def test_admin_can_manage_disabled_owner_without_inheriting_admin_pool_access(self):
        User.objects.filter(pk=self.alice.pk).update(is_active=False)
        config = save_experiment(self.admin, experiment_payload("代管", self.alice_pool),
                                 owner_id=self.alice.pk)
        self.assertEqual(config.owner_id, self.alice.pk)
        with self.assertRaises(ExperimentError):
            save_experiment(self.admin, experiment_payload("越权", self.admin_pool),
                            owner_id=self.alice.pk)
        with self.assertRaises(AccountError):
            save_experiment(self.alice, experiment_payload("禁用者", self.alice_pool))


class ExperimentAPITests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True,
                                    must_change_password=False)
        self.user = create_account(self.admin, "user", "123456", must_change_password=False)
        self.pool = save_pool(self.admin, {**pool_document("公共池"), "kind": Pool.PUBLIC})
        self.client = Client()

    def login_as(self, user):
        self.client.force_login(user)
        session = self.client.session
        now = timezone.now().isoformat()
        session["created_at"] = now
        session["last_activity_at"] = now
        session["auth_version"] = user.auth_version
        session.save()

    def test_crud_is_authenticated_and_returns_decimal_seed(self):
        payload = experiment_payload("API实验", self.pool)
        payload["parameters"]["seed"] = "9" * 100
        self.assertEqual(self.client.get("/api/v1/experiment-configs/").status_code, 401)
        self.login_as(self.user)
        created = self.client.post("/api/v1/experiment-configs/", data=json.dumps(payload),
                                   content_type="application/json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["parameters"]["seed"], "9" * 100)
        self.assertFalse(created.json()["owner_is_admin"])
        config_id = created.json()["id"]
        listed = self.client.get("/api/v1/experiment-configs/")
        self.assertEqual(listed.json()["total"], 1)
        exported = self.client.get(
            f"/api/v1/experiment-configs/{config_id}/export/?expected_revision=1")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(str(json.loads(exported.content)["parameters"]["seed"]), "9" * 100)
        deleted = self.client.delete(f"/api/v1/experiment-configs/{config_id}/",
                                     data=json.dumps({"expected_revision": 1}),
                                     content_type="application/json")
        self.assertEqual(deleted.status_code, 204)

        save_experiment(self.admin, experiment_payload("管理员配置", self.pool))
        self.login_as(self.admin)
        admin_owned = self.client.get("/api/v1/experiment-configs/").json()["items"][0]
        self.assertTrue(admin_owned["owner_is_admin"])

        payload["name"] = "超长种子"
        payload["parameters"]["seed"] = "9" * 5000
        rejected = self.client.post("/api/v1/experiment-configs/", data=json.dumps(payload),
                                    content_type="application/json")
        self.assertEqual(rejected.status_code, 400)

    def test_unavailable_pool_uses_saved_hint_without_exposing_current_name(self):
        visible_private = save_pool(self.admin, {**pool_document("原公开名称"),
                                                 "visibility": Pool.PUBLIC})
        payload = experiment_payload("引用实验", visible_private)
        config = save_experiment(self.user, payload)
        Pool.objects.filter(pk=visible_private.pk).update(name="隐藏后新名称", name_key="隐藏后新名称",
                                                          visibility=Pool.HIDDEN, revision=2)
        self.login_as(self.user)
        response = self.client.get(f"/api/v1/experiment-configs/{config.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["pool_ref"]["available"])
        self.assertEqual(response.json()["pool_ref"]["name"], "原公开名称")

    def test_import_preview_then_confirm_requires_selected_current_pool(self):
        raw = {"format_version": 1, "name": "导入API", "pool_ref": {
            "id": str(uuid4()), "name": "公共池"}, "parameters": {**PARAMETERS, "seed": 10**100}}
        self.login_as(self.user)
        preview = self.client.post("/api/v1/experiment-configs/import/preview/",
                                   data=json.dumps({"document": raw}),
                                   content_type="application/json")
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["resolution"]["status"], "confirm")
        for field in ("draws", "trials", "initial_pity", "initial_five_star_pity", "seed"):
            self.assertIsInstance(preview.json()["document"]["parameters"][field], str)
        self.assertEqual(preview.json()["document"]["parameters"]["seed"], str(10**100))
        body = {"document": preview.json()["document"], "pool_id": str(self.pool.pk),
                "pool_revision": self.pool.revision}
        confirmed = self.client.post("/api/v1/experiment-configs/import/confirm/",
                                     data=json.dumps(body), content_type="application/json")
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        self.assertEqual(confirmed.json()["pool_ref"]["id"], str(self.pool.pk))
        self.assertEqual(confirmed.json()["parameters"]["seed"], str(10**100))
