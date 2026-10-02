import json
from uuid import uuid4

from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone

from dashboard.models import Pool, Rule, User
from dashboard.services.accounts import create_account
from dashboard.services.rules import (
    RuleError, copy_rule, delete_rule, export_rule, resolve_rule_reference, rule_document,
    save_rule, validate_rule_pool_reference, visible_rules,
)
from tests.fixtures_rules import default_pool, default_rule
from lottery_simulator.rules.definitions import RuleDefinition
from lottery_simulator.config_documents import load_pool_document, load_rule_document
from lottery_simulator.rules.runtime import compile_pool
from dashboard.api.serializers import ExperimentParametersSerializer, PoolControlsSerializer


class RuleServiceTests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True, must_change_password=False)
        self.alice = create_account(self.admin, "alice", "123456", must_change_password=False)
        self.bob = create_account(self.admin, "bob", "123456", must_change_password=False)

    def make_rule(self, actor=None, *, visibility=Rule.HIDDEN, kind=Rule.PRIVATE):
        return save_rule(actor or self.alice, {
            **default_rule().to_dict(), "kind": kind, "visibility": visibility,
        })

    def make_pool(self, rule, owner, *, kind=Pool.PRIVATE, visibility=Pool.HIDDEN, name="消费池"):
        definition = default_pool().to_dict()
        definition.update(id=str(Pool._meta.pk.default()), name=name,
                          rule_ref={"id": str(rule.pk), "name": rule.name})
        return Pool.objects.create(id=definition["id"], name=name, name_key=name,
            kind=kind, owner=owner, rule=rule, visibility=visibility,
            original_author=owner.username if owner else "系统",
            config_json=definition, revision=1)

    def test_visibility_matrix_and_admin_uses_pool_owner_rights(self):
        hidden = self.make_rule()
        public = self.make_rule(self.admin, visibility=Rule.PUBLIC, kind=Rule.PUBLIC)
        self.assertEqual(visible_rules(self.bob).filter(pk=hidden.pk).count(), 0)
        self.assertTrue(visible_rules(self.bob).filter(pk=public.pk).exists())
        with self.assertRaises(RuleError):
            export_rule(self.bob, hidden.pk, expected_revision=hidden.revision)
        self.assertEqual(export_rule(self.bob, public.pk,
            expected_revision=public.revision)["id"], str(public.pk))
        self.assertEqual(validate_rule_pool_reference(self.admin, hidden, pool_owner=self.alice,
            pool_kind=Pool.PRIVATE, pool_visibility=Pool.HIDDEN).pk, hidden.pk)
        with self.assertRaises(RuleError):
            validate_rule_pool_reference(self.admin, hidden, pool_owner=self.bob,
                pool_kind=Pool.PRIVATE, pool_visibility=Pool.HIDDEN)
        with self.assertRaises(RuleError):
            validate_rule_pool_reference(self.admin, hidden, pool_owner=self.admin,
                pool_kind=Pool.PRIVATE, pool_visibility=Pool.PUBLIC)
        self.assertEqual(validate_rule_pool_reference(self.admin, public, pool_owner=None,
            pool_kind=Pool.PUBLIC, pool_visibility=Pool.PUBLIC).pk, public.pk)

    def test_copy_changes_id_preserves_author_and_leaves_source(self):
        source = self.make_rule(visibility=Rule.PUBLIC)
        source_author = source.original_author
        clone = copy_rule(self.bob, source.pk, "副本", Rule.PRIVATE)
        self.assertNotEqual(source.pk, clone.pk)
        self.assertEqual(clone.original_author, source_author)
        self.assertEqual(clone.config_json["id"], str(clone.pk))
        self.assertEqual(source.revision, 1)
        self.assertEqual(rule_document(clone)["id"], str(clone.pk))

    def test_structural_change_and_invalid_shared_update_are_atomic(self):
        rule = self.make_rule()
        pool = self.make_pool(rule, self.alice)
        before = rule.revision
        changed = rule_document(rule)
        first, second = changed["rarities"][:2]
        first["rank"], second["rank"] = second["rank"], first["rank"]
        bonus_by_id = {item["id"]: item for item in changed["bonus"]["rarities"]}
        for rarity in changed["rarities"]:
            bonus_by_id[rarity["id"]]["rank"] = rarity["rank"]
        RuleDefinition.from_dict(changed)
        with self.assertRaises(RuleError):
            save_rule(self.alice, {**changed, "visibility": Rule.HIDDEN},
                      rule_id=rule.pk, expected_revision=before)
        rule.refresh_from_db()
        self.assertEqual(rule.revision, before)
        self.assertEqual(Pool.objects.get(pk=pool.pk).rule_id, rule.pk)

        changed = rule_document(rule)
        changed["big_pity"]["hard_pity"] -= 1
        changed = save_rule(self.alice, {**changed, "visibility": Rule.HIDDEN},
                            rule_id=rule.pk, expected_revision=before)
        self.assertEqual(changed.revision, before + 1)

    def test_invalid_shared_consumer_does_not_leak_hidden_pool_name(self):
        definition = default_rule().to_dict()
        definition["big_pity"]["enabled"] = False
        definition["grant"]["enabled"] = False
        rule = save_rule(self.alice, {**definition, "visibility": Rule.PUBLIC})
        pool = self.make_pool(rule, self.bob, name="秘密池名")
        pool.config_json["rarity_pools"][-1]["characters"] = [
            {**character, "is_up": False} for character in
            pool.config_json["rarity_pools"][-1]["characters"]]
        pool.config_json["rarity_pools"][-1]["up_enabled"] = False
        pool.save(update_fields=["config_json"])
        compile_pool(load_rule_document(rule_document(rule)),
                     load_pool_document(pool.config_json))
        raw = rule_document(rule)
        raw["big_pity"]["enabled"] = True
        with self.assertRaises(RuleError) as caught:
            save_rule(self.alice, {**raw, "visibility": Rule.PUBLIC},
                      rule_id=rule.pk, expected_revision=rule.revision)
        self.assertNotIn("秘密池名", str(caught.exception))
        rule.refresh_from_db()
        self.assertEqual(rule.revision, 1)
        self.assertEqual(pool.rule_id, rule.pk)

    def test_references_are_protected_and_uuid_never_falls_back(self):
        rule = self.make_rule(visibility=Rule.PUBLIC)
        self.make_pool(rule, self.bob)
        with self.assertRaises(RuleError):
            delete_rule(self.admin, rule.pk, rule.revision)
        self.assertEqual(resolve_rule_reference(self.bob,
            {"id": str(rule.pk), "name": "renamed"})["status"], "matched")
        missing = resolve_rule_reference(self.bob,
            {"id": "00000000-0000-0000-0000-000000000000", "name": rule.name})
        self.assertEqual(missing["status"], "confirm")
        self.assertEqual(resolve_rule_reference(self.bob,
            {"id": "not-a-uuid", "name": rule.name})["status"], "unavailable")
        with self.assertRaises(RuleError):
            resolve_rule_reference(None, {"id": str(rule.pk), "name": rule.name})

    def test_revision_conflict_and_public_rule_cannot_be_hidden_with_external_users(self):
        rule = self.make_rule(visibility=Rule.PUBLIC)
        self.make_pool(rule, self.bob)
        changed = rule_document(rule)
        changed["big_pity"]["hard_pity"] -= 1
        saved = save_rule(self.alice, changed, rule_id=rule.pk, expected_revision=1)
        self.assertEqual(saved.revision, 2)
        stale = rule_document(saved)
        stale["big_pity"]["hard_pity"] -= 1
        with self.assertRaises(RuleError) as conflict:
            save_rule(self.alice, stale, rule_id=rule.pk, expected_revision=1)
        self.assertEqual(conflict.exception.code, "revision_conflict")
        with self.assertRaises(RuleError):
            save_rule(self.alice, {**rule_document(saved), "visibility": Rule.HIDDEN},
                      rule_id=rule.pk, expected_revision=2)
        saved.refresh_from_db()
        self.assertEqual(saved.revision, 2)

    def test_actor_and_owner_deleting_state_are_rechecked(self):
        rule = self.make_rule()
        self.alice.deleting = True
        self.alice.save(update_fields=["deleting"])
        with self.assertRaises(RuleError):
            validate_rule_pool_reference(self.admin, rule, pool_owner=self.alice,
                pool_kind=Pool.PRIVATE, pool_visibility=Pool.HIDDEN)

    def test_export_rechecks_visibility_revision_and_session(self):
        hidden = self.make_rule()
        with self.assertRaises(RuleError):
            export_rule(self.bob, hidden.pk, expected_revision=hidden.revision)
        with self.assertRaises(RuleError) as conflict:
            export_rule(self.alice, hidden.pk, expected_revision=hidden.revision + 1)
        self.assertEqual(conflict.exception.code, "revision_conflict")
        self.assertEqual(export_rule(self.alice, hidden.pk,
                                    expected_revision=hidden.revision), rule_document(hidden))
        User.objects.filter(pk=self.alice.pk).update(auth_version=self.alice.auth_version + 1)
        with self.assertRaises(RuleError):
            export_rule(self.alice, hidden.pk, expected_revision=hidden.revision)

    def test_disabled_author_public_resource_remains_usable_but_deleting_blocks_binding(self):
        shared = self.make_rule(visibility=Rule.PUBLIC)
        User.objects.filter(pk=self.alice.pk).update(is_active=False)
        self.assertEqual(validate_rule_pool_reference(self.bob, shared, pool_owner=self.bob,
            pool_kind=Pool.PRIVATE, pool_visibility=Pool.HIDDEN).pk, shared.pk)
        User.objects.filter(pk=self.alice.pk).update(deleting=True)
        with self.assertRaises(RuleError):
            validate_rule_pool_reference(self.bob, shared, pool_owner=self.bob,
                pool_kind=Pool.PRIVATE, pool_visibility=Pool.HIDDEN)
        with self.assertRaises(RuleError):
            copy_rule(self.bob, shared.pk, "删除期间不可复制", Rule.PRIVATE)


class RuleAPITests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin-api", "123456", admin=True,
                                    must_change_password=False)
        self.alice = create_account(self.admin, "alice-api", "123456", must_change_password=False)
        self.bob = create_account(self.admin, "bob-api", "123456", must_change_password=False)
        self.client = Client()

    def login_as(self, user):
        self.client.force_login(user)
        session = self.client.session
        now = timezone.now().isoformat()
        session.update({"created_at": now, "last_activity_at": now,
                        "auth_version": user.auth_version})
        session.save()

    def test_auth_scope_copy_export_and_strict_revision(self):
        hidden = save_rule(self.alice, default_rule().to_dict())
        self.assertEqual(self.client.get("/api/v1/rules/").status_code, 401)
        self.login_as(self.bob)
        self.assertEqual(self.client.get(f"/api/v1/rules/{hidden.pk}/").status_code, 404)
        self.login_as(self.alice)
        bad = self.client.patch(f"/api/v1/rules/{hidden.pk}/", data=json.dumps({
            "expected_revision": True,
        }), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        stale = self.client.get(f"/api/v1/rules/{hidden.pk}/export/?expected_revision=2")
        self.assertEqual(stale.status_code, 409)
        exported = self.client.get(f"/api/v1/rules/{hidden.pk}/export/?expected_revision=1")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json(), rule_document(hidden))
        copied = self.client.post(f"/api/v1/rules/{hidden.pk}/copy/", data=json.dumps({
            "name": "规则副本", "kind": Rule.PRIVATE,
        }), content_type="application/json")
        self.assertEqual(copied.status_code, 201, copied.content)
        self.assertNotEqual(copied.json()["id"], str(hidden.pk))

    def test_rule_import_is_definition_only_and_creates_private_hidden_resource(self):
        self.login_as(self.alice)
        document = default_rule().to_dict()
        invalid = self.client.post("/api/v1/rules/import/preview/", data=json.dumps({
            "document": {**document, "format_version": 0},
        }), content_type="application/json")
        self.assertEqual(invalid.status_code, 400)
        preview = self.client.post("/api/v1/rules/import/preview/", data=json.dumps({
            "document": document,
        }), content_type="application/json")
        self.assertEqual(preview.status_code, 200, preview.content)
        spoofed = self.client.post("/api/v1/rules/import/confirm/", data=json.dumps({
            "document": preview.json()["document"], "owner_id": str(self.bob.pk),
        }), content_type="application/json")
        self.assertEqual(spoofed.status_code, 400)
        confirmed = self.client.post("/api/v1/rules/import/confirm/", data=json.dumps({
            "document": preview.json()["document"],
        }), content_type="application/json")
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        self.assertEqual(confirmed.json()["kind"], Rule.PRIVATE)
        self.assertEqual(confirmed.json()["visibility"], Rule.HIDDEN)
        self.assertEqual(confirmed.json()["owner_id"], str(self.alice.pk))

    def test_hidden_pool_reference_locks_structure_without_leaking_reference(self):
        rule_data = default_rule().to_dict()
        rule = save_rule(self.alice, {**rule_data, "visibility": Rule.PUBLIC})
        pool_doc = default_pool().to_dict()
        pool_id = uuid4()
        pool_doc.update(id=str(pool_id), name="其他用户隐藏池",
                        rule_ref={"id": str(rule.pk), "name": rule.name})
        Pool.objects.create(id=pool_id, name="其他用户隐藏池", name_key="其他用户隐藏池",
            kind=Pool.PRIVATE, owner=self.bob, rule=rule, visibility=Pool.HIDDEN,
            original_author=self.bob.username, config_json=pool_doc, revision=1)
        self.login_as(self.alice)
        resource = self.client.get(f"/api/v1/rules/{rule.pk}/").json()
        self.assertTrue(resource["structure_locked"])
        self.assertEqual(resource["reference_count"], 0)
        changed = rule_document(rule)
        changed["rarities"][0]["rank"], changed["rarities"][1]["rank"] = (
            changed["rarities"][1]["rank"], changed["rarities"][0]["rank"])
        bonus = {item["id"]: item for item in changed["bonus"]["rarities"]}
        for rarity in changed["rarities"]:
            bonus[rarity["id"]]["rank"] = rarity["rank"]
        response = self.client.patch(f"/api/v1/rules/{rule.pk}/", data=json.dumps({
            "document": changed, "expected_revision": 1,
        }), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("其他用户隐藏池", response.content.decode())

    def test_mutation_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        token = csrf_client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        login = csrf_client.post("/api/v1/auth/login/", data=json.dumps({
            "username": "alice-api", "password": "123456"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(login.status_code, 200, login.content)
        response = csrf_client.post("/api/v1/rules/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_scope_filters_before_pagination_and_requires_admin_for_all_private(self):
        public = save_rule(self.admin, {**default_rule().to_dict(), "kind": Rule.PUBLIC})
        mine = save_rule(self.alice, {**default_rule().to_dict(), "name": "自己的规则"})
        shared = save_rule(self.bob, {**default_rule().to_dict(), "name": "公开规则",
                                     "visibility": Rule.PUBLIC})
        hidden = save_rule(self.bob, {**default_rule().to_dict(), "name": "隐藏规则"})
        self.login_as(self.alice)
        for scope, expected in (("public", public), ("mine", mine), ("others_public", shared)):
            response = self.client.get(f"/api/v1/rules/?scope={scope}&page_size=1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["total"], 1)
            self.assertEqual(response.json()["items"][0]["id"], str(expected.pk))
        self.assertEqual(self.client.get("/api/v1/rules/?scope=all_private").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/rules/?scope=invalid").status_code, 400)
        self.login_as(self.admin)
        items = self.client.get("/api/v1/rules/?scope=all_private").json()["items"]
        self.assertEqual({item["id"] for item in items}, {str(r.pk) for r in (mine, shared, hidden)})


class APIInputSerializerTests(SimpleTestCase):
    def test_v6_counts_and_seed_round_trip_without_javascript_precision_loss(self):
        seed = "9" * 80
        payload = {
            "draws": "30", "trials": "2", "seed": seed, "trace": True,
            "initial_main_draws": "0", "initial_small_pity": {"r": "0"},
            "initial_big_pity": {"target_obtained": False, "misses": "0"},
        }
        serializer = ExperimentParametersSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["seed"], int(seed))
        self.assertEqual(serializer.data["seed"], seed)

    def test_boolean_revision_unknown_fields_and_wrong_boolean_are_rejected(self):
        for payload in ({"expected_revision": True},
                        {"expected_revision": 1, "owner_id": "forged"}):
            serializer = PoolControlsSerializer(data=payload)
            self.assertFalse(serializer.is_valid())
        malformed = ExperimentParametersSerializer(data={
            "draws": "1", "trials": "1", "seed": None, "trace": 1,
            "initial_main_draws": "0", "initial_small_pity": {},
            "initial_big_pity": {"target_obtained": False, "misses": "0"},
        })
        self.assertFalse(malformed.is_valid())
