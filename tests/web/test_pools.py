from copy import deepcopy
import json
from uuid import uuid4

from django.test import Client, TestCase
from django.utils import timezone

from dashboard.models import ExperimentConfig, Pool, Rule, User
from dashboard.services.accounts import AccountError, create_account
from dashboard.services.pools import (
    PoolError, copy_pool, delete_pool, preview_pool_import, save_pool, visible_pools,
)
from dashboard.services.rules import save_rule
from lottery_simulator.config_documents import (
    DEFAULT_POOL_PATH, DEFAULT_RULE_PATH, load_pool_document, read_config_json,
)


class PoolServiceTests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True,
                                    must_change_password=False)
        self.user = create_account(self.admin, "alice", "123456", must_change_password=False)
        self.other = create_account(self.admin, "bob", "123456", must_change_password=False)
        raw_rule = read_config_json(DEFAULT_RULE_PATH)
        self.rule = save_rule(self.admin, {"config": raw_rule, "kind": Rule.PUBLIC})

    def pool_doc(self, name):
        raw = read_config_json(DEFAULT_POOL_PATH)
        raw["name"] = name
        raw["rule_ref"] = {"id": str(self.rule.pk), "name": self.rule.name}
        return load_pool_document(raw).to_dict()

    def test_pool_save_checks_current_rule_revision_and_compiles(self):
        payload = self.pool_doc("我的池")
        pool = save_pool(self.user, payload, expected_rule_revision=self.rule.revision)
        self.assertEqual(pool.rule.name, "zmd")
        self.assertEqual(pool.revision, 1)
        with self.assertRaises(PoolError) as conflict:
            save_pool(self.user, payload, pool_id=pool.pk, expected_revision=1,
                      expected_rule_revision=self.rule.revision + 1)
        self.assertEqual(conflict.exception.code, "revision_conflict")

    def test_visibility_edit_revision_and_delete_preserve_experiment_hint(self):
        hidden = save_pool(self.user, self.pool_doc("隐藏池"),
                           expected_rule_revision=self.rule.revision)
        public_copy = save_pool(self.user, {**self.pool_doc("公开私有池"),
                                            "visibility": Pool.PUBLIC},
                                expected_rule_revision=self.rule.revision)
        visible_ids = {str(pk) for pk in visible_pools(self.other).values_list("pk", flat=True)}
        self.assertNotIn(str(hidden.pk), visible_ids)
        self.assertIn(str(public_copy.pk), visible_ids)
        changed = save_pool(self.user, self.pool_doc("改名"), pool_id=hidden.pk,
                            expected_revision=hidden.revision,
                            expected_rule_revision=self.rule.revision)
        with self.assertRaises(PoolError):
            save_pool(self.user, {**self.pool_doc("改类型"), "kind": Pool.PUBLIC},
                      pool_id=changed.pk, expected_revision=changed.revision,
                      expected_rule_revision=self.rule.revision)
        config = ExperimentConfig.objects.create(owner=self.user, name="引用", name_key="引用",
                                                 pool=changed, pool_name_hint=changed.name,
                                                 parameters_json={})
        delete_pool(self.user, changed.pk, expected_revision=changed.revision)
        config.refresh_from_db()
        self.assertIsNone(config.pool_id)
        self.assertEqual(config.pool_name_hint, "改名")

    def test_revoked_actor_cannot_create_pool(self):
        User.objects.filter(pk=self.user.pk).update(auth_version=self.user.auth_version + 1)
        with self.assertRaises(AccountError):
            save_pool(self.user, self.pool_doc("撤销后不可创建"),
                      expected_rule_revision=self.rule.revision)

    def test_public_pool_rejects_private_rule_and_copy_requires_source_revision(self):
        private_rule = save_rule(self.user, {"config": read_config_json(DEFAULT_RULE_PATH)})
        public_payload = self.pool_doc("不允许的公共池")
        public_payload["rule_ref"] = {"id": str(private_rule.pk), "name": private_rule.name}
        with self.assertRaises(PoolError):
            save_pool(self.admin, {**public_payload, "kind": Pool.PUBLIC},
                      expected_rule_revision=private_rule.revision)

        source = save_pool(self.admin, {**self.pool_doc("公共池"), "kind": Pool.PUBLIC},
                           expected_rule_revision=self.rule.revision)
        with self.assertRaises(PoolError) as conflict:
            copy_pool(self.user, source.pk, name="副本", kind=Pool.PRIVATE,
                      expected_revision=source.revision + 1,
                      expected_source_rule_revision=source.rule.revision,
                      expected_rule_revision=source.rule.revision)
        self.assertEqual(conflict.exception.code, "revision_conflict")

    def test_rule_switch_requires_explicit_mapping_or_clear_confirmation(self):
        pool = save_pool(self.user, self.pool_doc("带名单"), expected_rule_revision=1)
        new_rule_raw = read_config_json(DEFAULT_RULE_PATH)
        ids = {item["id"]: str(uuid4()) for item in new_rule_raw["rarities"]}
        def replace(value):
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            return ids.get(value, value) if isinstance(value, str) else value
        new_rule_raw = replace(new_rule_raw)
        new_rule_raw["big_pity"]["enabled"] = False
        new_rule_raw["grant"]["enabled"] = False
        new_rule = save_rule(self.user, {"config": new_rule_raw})
        changed = deepcopy(self.pool_doc("带名单"))
        changed["rule_ref"] = {"id": str(new_rule.pk), "name": new_rule.name}
        with self.assertRaises(PoolError):
            save_pool(self.user, changed, pool_id=pool.pk, expected_revision=pool.revision,
                      expected_rule_revision=new_rule.revision)
        mapping = {old: ids[old] for old in ids}
        switched = save_pool(self.user, changed, pool_id=pool.pk, expected_revision=pool.revision,
                             expected_rule_revision=new_rule.revision, rarity_mapping=mapping)
        self.assertEqual(switched.rule_id, new_rule.pk)

        empty_source = save_pool(self.user, self.pool_doc("清空确认源"),
                                 expected_rule_revision=self.rule.revision)
        clear_target = deepcopy(self.pool_doc("清空确认源"))
        clear_target["rule_ref"] = {"id": str(new_rule.pk), "name": new_rule.name}
        cleared = save_pool(self.user, clear_target, pool_id=empty_source.pk,
                            expected_revision=empty_source.revision,
                            expected_rule_revision=new_rule.revision, clear_unmapped=True)
        self.assertTrue(all(not item.characters for item in
                            load_pool_document(cleared.config_json).rarity_pools))
        with self.assertRaises(PoolError):
            save_pool(self.user, clear_target, pool_id=cleared.pk,
                      expected_revision=cleared.revision,
                      expected_rule_revision=new_rule.revision, clear_unmapped="yes")

    def test_copy_preserves_author_and_checks_both_rule_revisions(self):
        source = save_pool(self.admin, {**self.pool_doc("公共池"), "kind": Pool.PUBLIC},
                           expected_rule_revision=self.rule.revision)
        copied = copy_pool(self.user, source.pk, name="副本", kind=Pool.PRIVATE,
                           expected_revision=source.revision,
                           expected_source_rule_revision=source.rule.revision,
                           expected_rule_revision=self.rule.revision)
        self.assertEqual(copied.owner_id, self.user.pk)
        self.assertEqual(copied.visibility, Pool.HIDDEN)
        self.assertEqual(copied.original_author, source.original_author)

    def test_pool_import_is_strict_json_and_does_not_upgrade_old_format(self):
        with self.assertRaises(PoolError):
            preview_pool_import(self.user, b'{"format_version":3,"format_version":2}')
        old = self.pool_doc("旧格式")
        old["format_version"] = 2
        with self.assertRaises(PoolError):
            preview_pool_import(self.user, json.dumps(old).encode())


class PoolAPITests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True,
                                    must_change_password=False)
        self.user = create_account(self.admin, "alice", "123456", must_change_password=False)
        self.other = create_account(self.admin, "bob", "123456", must_change_password=False)
        self.rule = save_rule(self.admin, {"config": read_config_json(DEFAULT_RULE_PATH),
                                           "kind": Rule.PUBLIC})
        self.client = Client()

    def login_as(self, user):
        self.client.force_login(user)
        session = self.client.session
        now = timezone.now().isoformat()
        session["created_at"] = now
        session["last_activity_at"] = now
        session["auth_version"] = user.auth_version
        session.save()

    def pool_doc(self, name):
        raw = read_config_json(DEFAULT_POOL_PATH)
        raw.update(name=name, rule_ref={"id": str(self.rule.pk), "name": self.rule.name})
        return raw

    def test_list_export_require_authentication_scope_and_revision(self):
        pool = save_pool(self.user, self.pool_doc("隐藏池"),
                         expected_rule_revision=self.rule.revision)
        self.assertEqual(self.client.get("/api/v1/pools/").status_code, 401)
        self.login_as(self.other)
        self.assertEqual(self.client.get("/api/v1/pools/").json()["items"], [])
        self.assertEqual(self.client.get(
            f"/api/v1/pools/{pool.pk}/export/?expected_revision={pool.revision}").status_code, 404)
        self.login_as(self.user)
        conflict = self.client.get(
            f"/api/v1/pools/{pool.pk}/export/?expected_revision={pool.revision + 1}")
        self.assertEqual(conflict.status_code, 409)
        exported = self.client.get(
            f"/api/v1/pools/{pool.pk}/export/?expected_revision={pool.revision}")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["name"], "隐藏池")

    def test_import_preview_confirm_is_strict_and_preserves_private_owner(self):
        raw = self.pool_doc("导入池")
        raw["rule_ref"]["id"] = str(uuid4())
        self.login_as(self.user)
        duplicate = self.client.post("/api/v1/pools/import/preview/",
                                     data=b'{"format_version":3,"format_version":3}',
                                     content_type="application/json")
        self.assertEqual(duplicate.status_code, 400)
        permission_intent = {**raw, "kind": "public", "owner_id": str(self.admin.pk)}
        rejected = self.client.post("/api/v1/pools/import/preview/",
                                    data=json.dumps(permission_intent),
                                    content_type="application/json")
        self.assertEqual(rejected.status_code, 400)
        preview = self.client.post("/api/v1/pools/import/preview/", data=json.dumps(raw),
                                   content_type="application/json")
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["resolution"]["status"], "confirm")
        confirm = self.client.post("/api/v1/pools/import/confirm/", data=json.dumps({
            "document": preview.json()["document"], "rule_id": str(self.rule.pk),
            "rule_revision": self.rule.revision,
        }), content_type="application/json")
        self.assertEqual(confirm.status_code, 201, confirm.content)
        imported = Pool.objects.get(pk=confirm.json()["id"])
        self.assertEqual(imported.kind, Pool.PRIVATE)
        self.assertEqual(imported.visibility, Pool.HIDDEN)
        self.assertEqual(imported.owner_id, self.user.pk)
        self.assertEqual(imported.rule_id, self.rule.pk)

    def test_pagination_and_copy_confirm_both_pool_and_rule_revisions(self):
        source = save_pool(self.admin, {**self.pool_doc("公共池"), "kind": Pool.PUBLIC},
                           expected_rule_revision=self.rule.revision)
        self.login_as(self.user)
        listed = self.client.get("/api/v1/pools/?page_size=1")
        self.assertEqual(listed.json()["page_size"], 1)
        body = {
            "name": "私有副本", "kind": Pool.PRIVATE,
            "expected_revision": source.revision,
            "expected_source_rule_revision": source.rule.revision,
            "rule_ref": {"id": str(self.rule.pk), "name": self.rule.name},
            "expected_rule_revision": self.rule.revision,
        }
        copied = self.client.post(f"/api/v1/pools/{source.pk}/copy/", data=json.dumps(body),
                                  content_type="application/json")
        self.assertEqual(copied.status_code, 201, copied.content)
        self.assertEqual(copied.json()["visibility"], Pool.HIDDEN)
        stale = {**body, "name": "过期副本", "expected_source_rule_revision": 2}
        conflict = self.client.post(f"/api/v1/pools/{source.pk}/copy/", data=json.dumps(stale),
                                    content_type="application/json")
        self.assertEqual(conflict.status_code, 409)
