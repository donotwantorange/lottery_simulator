import json
from uuid import uuid4

from django.test import Client, TestCase
from django.utils import timezone

from dashboard.models import Pool, Rule, User
from dashboard.services.accounts import create_account
from dashboard.services.experiments import (
    ExperimentError, confirm_experiment_import, delete_experiment, experiment_validation,
    export_experiment, import_preview, save_experiment, visible_experiments,
)
from dashboard.services.pools import pool_document, save_pool
from dashboard.services.rules import save_rule
from lottery_simulator.config_documents import (
    DEFAULT_POOL_PATH, DEFAULT_RULE_PATH, load_pool_document, read_config_json,
)
from lottery_simulator.rules.runtime import compile_pool
from dashboard.services.pools import load_rule_definition
from dashboard.services.initial_conditions import build_initial_context


class ExperimentServiceTests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True,
                                    must_change_password=False)
        self.user = create_account(self.admin, "alice", "123456", must_change_password=False)
        raw_rule = read_config_json(DEFAULT_RULE_PATH)
        self.rule = save_rule(self.admin, {"config": raw_rule, "kind": Rule.PUBLIC})
        raw_pool = read_config_json(DEFAULT_POOL_PATH)
        raw_pool["rule_ref"] = {"id": str(self.rule.pk), "name": self.rule.name}
        self.pool = save_pool(self.user, raw_pool, expected_rule_revision=self.rule.revision)
        compiled = compile_pool(load_rule_definition(self.rule),
                                load_pool_document(pool_document(self.pool)))
        self.context = build_initial_context(compiled)

    def payload(self, *, name="实验", history=0, context=None):
        return {
            "name": name,
            "pool_ref": {"id": str(self.pool.pk), "name": self.pool.name},
            "parameters": {
                "draws": 10, "trials": 2, "seed": 17, "trace": False,
                "initial_main_draws": history,
                "initial_small_pity": {},
                "initial_big_pity": {"target_obtained": False, "misses": 0},
            },
            "initial_context": context,
        }

    def test_nonzero_context_is_required_and_all_values_are_normalized(self):
        with self.assertRaises(ExperimentError):
            save_experiment(self.user, self.payload(history=20))
        config = save_experiment(self.user, self.payload(history=20, context=self.context))
        self.assertEqual(config.parameters_json["initial_main_draws"], 20)
        self.assertEqual(config.initial_context_json, self.context)

    def test_owner_scope_revision_export_and_delete(self):
        config = save_experiment(self.user, self.payload())
        self.assertEqual(list(visible_experiments(self.admin)), [config])
        other = create_account(self.admin, "bob", "123456", must_change_password=False)
        self.assertEqual(list(visible_experiments(other)), [])
        saved = save_experiment(self.user, self.payload(name="改名"), config_id=config.pk,
                                expected_revision=config.revision)
        self.assertEqual(saved.revision, config.revision + 1)
        with self.assertRaises(ExperimentError):
            save_experiment(self.user, self.payload(name="冲突"), config_id=saved.pk,
                            expected_revision=config.revision)
        self.assertEqual(export_experiment(self.user, saved.pk,
                                           expected_revision=saved.revision)["initial_context"],
                         self.context)
        delete_experiment(self.user, saved.pk, expected_revision=saved.revision)

    def test_admin_manages_disabled_owner_without_borrowing_admin_pool_access(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        config = save_experiment(self.admin, self.payload(), owner_id=self.user.pk)
        self.assertEqual(config.owner_id, self.user.pk)
        raw_pool = read_config_json(DEFAULT_POOL_PATH)
        raw_pool["rule_ref"] = {"id": str(self.rule.pk), "name": self.rule.name}
        admin_pool = save_pool(self.admin, raw_pool,
                               expected_rule_revision=self.rule.revision)
        denied = self.payload(name="越权")
        denied["pool_ref"] = {"id": str(admin_pool.pk), "name": admin_pool.name}
        with self.assertRaises(ExperimentError):
            save_experiment(self.admin, denied, owner_id=self.user.pk)

    def test_normalization_rejects_impossible_history_even_with_matching_context(self):
        payload = self.payload(history=0, context=self.context)
        payload["parameters"]["initial_big_pity"]["target_obtained"] = True
        with self.assertRaises(ExperimentError):
            save_experiment(self.user, payload)

    def test_large_seed_round_trips_as_exact_integer(self):
        seed = 10**100 + 123
        payload = self.payload()
        payload["parameters"]["seed"] = seed
        config = save_experiment(self.user, payload)
        self.assertEqual(config.parameters_json["seed"], seed)

    def test_import_requires_current_pool_and_rule_revisions(self):
        raw = {"format_version": 2, "name": "导入实验",
               "pool_ref": {"id": "c19f9700-94c1-44ea-9b2b-1d50f2231000",
                            "name": self.pool.name},
               "parameters": self.payload()["parameters"], "initial_context": None}
        preview = import_preview(self.user, raw)
        self.assertEqual(preview["resolution"]["status"], "confirm")
        with self.assertRaises(ExperimentError):
            confirm_experiment_import(self.user, preview["document"],
                                      pool_id=self.pool.pk, pool_revision=self.pool.revision,
                                      rule_revision=self.rule.revision + 1)
        imported = confirm_experiment_import(
            self.user, preview["document"], pool_id=self.pool.pk,
            pool_revision=self.pool.revision, rule_revision=self.rule.revision)
        self.assertEqual(str(imported.pool_id), str(self.pool.pk))

    def test_stale_saved_configuration_is_read_with_validation_errors(self):
        payload = self.payload(history=50, context=self.context)
        highest_id = self.context["rarity_ids"][-1]
        payload["parameters"]["initial_small_pity"] = {highest_id: 50}
        config = save_experiment(self.user, payload)
        raw = self.rule.config_json.copy()
        raw["rarities"] = [dict(item) for item in raw["rarities"]]
        next(item for item in raw["rarities"] if item["id"] == highest_id)["hard_pity"] = 40
        from dashboard.services.rules import save_rule
        save_rule(self.admin, {"config": raw}, rule_id=self.rule.pk,
                  expected_revision=self.rule.revision)
        status = experiment_validation(config)
        self.assertTrue(status["validation_errors"])
        self.assertTrue(status["needs_confirmation"])


class ExperimentAPITests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True,
                                    must_change_password=False)
        self.user = create_account(self.admin, "user", "123456", must_change_password=False)
        self.rule = save_rule(self.admin, {"config": read_config_json(DEFAULT_RULE_PATH),
                                           "kind": Rule.PUBLIC})
        raw_pool = read_config_json(DEFAULT_POOL_PATH)
        raw_pool.update(name="公共池", rule_ref={"id": str(self.rule.pk), "name": self.rule.name})
        self.pool = save_pool(self.admin, {**raw_pool, "kind": Pool.PUBLIC},
                              expected_rule_revision=self.rule.revision)
        self.context = build_initial_context(compile_pool(
            load_rule_definition(self.rule), load_pool_document(pool_document(self.pool))))
        self.client = Client()

    def login_as(self, user):
        self.client.force_login(user)
        session = self.client.session
        now = timezone.now().isoformat()
        session["created_at"] = now
        session["last_activity_at"] = now
        session["auth_version"] = user.auth_version
        session.save()

    def payload(self, name="API实验", *, seed="17", pool=None):
        pool = pool or self.pool
        return {
            "name": name,
            "pool_ref": {"id": str(pool.pk), "name": pool.name},
            "parameters": {
                "draws": "10", "trials": "2", "seed": seed, "trace": False,
                "initial_main_draws": "0", "initial_small_pity": {},
                "initial_big_pity": {"target_obtained": False, "misses": "0"},
            },
            "initial_context": None,
            "expected_pool_revision": pool.revision,
            "expected_rule_revision": pool.rule.revision,
        }

    def test_crud_is_authenticated_and_keeps_large_seed_decimal(self):
        payload = self.payload(seed="9" * 100)
        self.assertEqual(self.client.get("/api/v1/experiment-configs/").status_code, 401)
        self.login_as(self.user)
        created = self.client.post("/api/v1/experiment-configs/", data=json.dumps(payload),
                                   content_type="application/json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["parameters"]["seed"], "9" * 100)
        self.assertEqual(created.json()["initial_context"], self.context)
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
        too_long = self.client.post("/api/v1/experiment-configs/",
                                    data=json.dumps(self.payload(seed="9" * 5000)),
                                    content_type="application/json")
        self.assertEqual(too_long.status_code, 400)

        self.login_as(self.admin)
        admin_config = self.client.post("/api/v1/experiment-configs/",
                                        data=json.dumps(self.payload("管理员配置")),
                                        content_type="application/json")
        self.assertEqual(admin_config.status_code, 201)
        self.assertTrue(admin_config.json()["owner_is_admin"])

    def test_query_integer_limits_apply_to_experiment_pagination_and_export(self):
        self.login_as(self.user)
        created = self.client.post("/api/v1/experiment-configs/",
                                   data=json.dumps(self.payload()), content_type="application/json")
        self.assertEqual(created.status_code, 201, created.content)
        config_id = created.json()["id"]
        for value in ("9" * 5000, "0" * 1024 + "1"):
            self.assertEqual(self.client.get(f"/api/v1/experiment-configs/?page={value}").status_code, 400)
            self.assertEqual(self.client.get(
                f"/api/v1/experiment-configs/{config_id}/export/?expected_revision={value}").status_code, 400)
        accepted = "0" * 1023 + "1"
        self.assertEqual(self.client.get(f"/api/v1/experiment-configs/?page={accepted}").status_code, 200)
        self.assertEqual(self.client.get(
            f"/api/v1/experiment-configs/{config_id}/export/?expected_revision={accepted}").status_code, 200)
        self.assertEqual(self.client.get(
            f"/api/v1/experiment-configs/{config_id}/export/?expected_revision=2").status_code, 409)
        self.assertEqual(self.client.get(
            f"/api/v1/experiment-configs/?page=1&page_size=201").status_code, 400)
        self.assertEqual(self.client.get(
            "/api/v1/experiment-configs/00000000-0000-0000-0000-000000000000/export/?expected_revision=1").status_code, 404)
        other = create_account(self.admin, "other-user", "123456", must_change_password=False)
        self.login_as(other)
        self.assertEqual(self.client.get(
            f"/api/v1/experiment-configs/{config_id}/export/?expected_revision=1").status_code, 404)

    def test_unavailable_pool_keeps_saved_hint_without_leaking_hidden_name(self):
        visible_private = save_pool(self.admin, {
            **read_config_json(DEFAULT_POOL_PATH), "name": "原公开名称",
            "rule_ref": {"id": str(self.rule.pk), "name": self.rule.name},
            "visibility": Pool.PUBLIC,
        }, expected_rule_revision=self.rule.revision)
        self.login_as(self.user)
        created = self.client.post("/api/v1/experiment-configs/",
                                   data=json.dumps(self.payload("引用实验", pool=visible_private)),
                                   content_type="application/json")
        self.assertEqual(created.status_code, 201, created.content)
        Pool.objects.filter(pk=visible_private.pk).update(name="隐藏后的秘密名称",
                                                          name_key="隐藏后的秘密名称",
                                                          visibility=Pool.HIDDEN, revision=2)
        response = self.client.get(f"/api/v1/experiment-configs/{created.json()['id']}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["pool_ref"]["available"])
        self.assertEqual(response.json()["pool_ref"]["name"], "原公开名称")
        self.assertNotIn("隐藏后的秘密名称", response.content.decode())

    def test_import_preview_and_confirm_recheck_both_revisions(self):
        raw = {
            "format_version": 2, "name": "导入API",
            "pool_ref": {"id": str(uuid4()), "name": self.pool.name},
            "parameters": {"draws": 10, "trials": 2, "seed": 10**100,
                           "trace": False, "initial_main_draws": 0,
                           "initial_small_pity": {},
                           "initial_big_pity": {"target_obtained": False, "misses": 0}},
            "initial_context": None,
        }
        self.login_as(self.user)
        preview = self.client.post("/api/v1/experiment-configs/import/preview/",
                                   data=json.dumps({"document": raw}),
                                   content_type="application/json")
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["resolution"]["status"], "confirm")
        for field in ("draws", "trials", "initial_main_draws", "seed"):
            self.assertIsInstance(preview.json()["document"]["parameters"][field], str)
        self.assertEqual(preview.json()["document"]["parameters"]["seed"], str(10**100))
        body = {"document": preview.json()["document"], "pool_id": str(self.pool.pk),
                "pool_revision": self.pool.revision, "rule_revision": self.rule.revision + 1}
        stale = self.client.post("/api/v1/experiment-configs/import/confirm/",
                                 data=json.dumps(body), content_type="application/json")
        self.assertEqual(stale.status_code, 409)
        body["rule_revision"] = self.rule.revision
        confirmed = self.client.post("/api/v1/experiment-configs/import/confirm/",
                                     data=json.dumps(body), content_type="application/json")
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        self.assertEqual(confirmed.json()["pool_ref"]["id"], str(self.pool.pk))
        self.assertEqual(confirmed.json()["parameters"]["seed"], str(10**100))
