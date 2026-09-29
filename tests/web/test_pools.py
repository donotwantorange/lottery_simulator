import json

from django.test import Client, TestCase
from django.utils import timezone

from dashboard.models import ExperimentConfig, Pool, User
from dashboard.services.accounts import AccountError, create_account
from dashboard.services.pools import PoolError, copy_pool, delete_pool, export_pool, save_pool, visible_pools
from lottery_simulator.config_documents import DEFAULT_POOL_PATH, load_pool_document, read_config_json


def default_document(name="测试池", *, author="最初作者"):
    raw = read_config_json(DEFAULT_POOL_PATH)
    raw["name"] = name
    raw["original_author"] = author
    return load_pool_document(raw).to_dict()


class PoolServiceTests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True,
                                    must_change_password=False)
        self.alice = create_account(self.admin, "alice", "123456", must_change_password=False)
        self.bob = create_account(self.admin, "bob", "123456", must_change_password=False)

    def test_visible_pools_are_scoped_by_visibility_and_owner(self):
        public = save_pool(self.admin, {**default_document("公共池"), "kind": Pool.PUBLIC})
        hidden = save_pool(self.alice, default_document("隐藏池"))
        open_pool = save_pool(self.alice, {**default_document("公开私有池"), "visibility": Pool.PUBLIC})
        self.assertSetEqual(set(visible_pools(self.bob).values_list("pk", flat=True)), {public.pk, open_pool.pk})
        self.assertIn(hidden.pk, visible_pools(self.admin).values_list("pk", flat=True))
        self.assertIsNone(public.owner_id)

    def test_save_requires_revision_and_refuses_type_conversion(self):
        pool = save_pool(self.alice, default_document("我的池"))
        saved = save_pool(self.alice, default_document("我的池2"), pool_id=pool.pk,
                          expected_revision=pool.revision)
        self.assertEqual(saved.revision, 2)
        with self.assertRaises(PoolError) as conflict:
            save_pool(self.alice, default_document("过期版本"), pool_id=pool.pk,
                      expected_revision=pool.revision)
        self.assertEqual(conflict.exception.code, "revision_conflict")
        with self.assertRaises(PoolError):
            save_pool(self.admin, {**default_document("我的池3"), "kind": Pool.PUBLIC},
                      pool_id=pool.pk, expected_revision=saved.revision)

    def test_revoked_actor_version_cannot_create_pool(self):
        User.objects.filter(pk=self.alice.pk).update(auth_version=self.alice.auth_version + 1)
        with self.assertRaises(AccountError):
            save_pool(self.alice, default_document("撤销后不可创建"))

    def test_copy_uses_new_id_hidden_visibility_and_original_author(self):
        source = save_pool(self.admin, {**default_document("原池"), "kind": Pool.PUBLIC})
        clone = copy_pool(self.alice, source.pk, name="副本", kind=Pool.PRIVATE)
        self.assertNotEqual(clone.pk, source.pk)
        self.assertEqual(clone.owner_id, self.alice.pk)
        self.assertEqual(clone.visibility, Pool.HIDDEN)
        self.assertEqual(clone.original_author, "最初作者")

    def test_export_revision_and_delete_clear_references(self):
        pool = save_pool(self.alice, default_document("待删除池"))
        ExperimentConfig.objects.create(owner=self.alice, name="实验", name_key="实验",
                                        pool=pool, pool_name_hint=pool.name, parameters_json={})
        with self.assertRaises(PoolError) as conflict:
            export_pool(self.alice, pool.pk, expected_revision=2)
        self.assertEqual(conflict.exception.code, "revision_conflict")
        self.assertEqual(export_pool(self.alice, pool.pk,
                                     expected_revision=pool.revision)["original_author"], "最初作者")
        delete_pool(self.alice, pool.pk, expected_revision=pool.revision)
        reference = ExperimentConfig.objects.get(name="实验")
        self.assertIsNone(reference.pool_id)
        self.assertEqual(reference.pool_name_hint, "待删除池")


class PoolAPITests(TestCase):
    def setUp(self):
        self.admin = create_account(None, "admin", "123456", admin=True,
                                    must_change_password=False)
        self.alice = create_account(self.admin, "alice", "123456", must_change_password=False)
        self.bob = create_account(self.admin, "bob", "123456", must_change_password=False)
        self.client = Client()

    def login_as(self, user):
        self.client.force_login(user)
        session = self.client.session
        now = timezone.now().isoformat()
        session["created_at"] = now
        session["last_activity_at"] = now
        session["auth_version"] = user.auth_version
        session.save()

    def test_list_and_export_require_authentication_and_revision(self):
        pool = save_pool(self.alice, default_document("隐藏池"))
        self.assertEqual(self.client.get("/api/v1/pools/").status_code, 401)
        self.login_as(self.bob)
        self.assertEqual(self.client.get("/api/v1/pools/").json()["items"], [])
        self.assertEqual(self.client.get(f"/api/v1/pools/{pool.pk}/export/?expected_revision=1").status_code, 404)
        self.login_as(self.alice)
        response = self.client.get(f"/api/v1/pools/{pool.pk}/export/?expected_revision=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["name"], "隐藏池")

    def test_import_parses_raw_bytes_and_ignores_permission_intent(self):
        raw = default_document("导入池2")
        raw.update({"kind": "public", "owner_id": str(self.admin.pk), "is_superuser": True})
        self.login_as(self.alice)
        response = self.client.post("/api/v1/pools/import/", data=json.dumps(raw),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 201)
        imported = Pool.objects.get(pk=response.json()["id"])
        self.assertEqual(imported.kind, Pool.PRIVATE)
        self.assertEqual(imported.owner_id, self.alice.pk)
        raw = default_document("导入池")
        response = self.client.post("/api/v1/pools/import/", data=json.dumps(raw),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 201)
        pool = Pool.objects.get(pk=response.json()["id"])
        self.assertEqual(pool.kind, Pool.PRIVATE)
        self.assertEqual(pool.visibility, Pool.HIDDEN)
        self.assertEqual(pool.owner_id, self.alice.pk)
        duplicate_key = b'{"format_version":2,"format_version":2}'
        response = self.client.post("/api/v1/pools/import/", data=duplicate_key,
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_pagination_and_copy_api(self):
        pool = save_pool(self.admin, {**default_document("公共池"), "kind": Pool.PUBLIC})
        self.login_as(self.alice)
        listed = self.client.get("/api/v1/pools/?page_size=1")
        self.assertEqual(listed.json()["page_size"], 1)
        copied = self.client.post(f"/api/v1/pools/{pool.pk}/copy/",
                                  data=json.dumps({"name": "私有副本", "kind": "private"}),
                                  content_type="application/json")
        self.assertEqual(copied.status_code, 201)
        self.assertEqual(copied.json()["visibility"], Pool.HIDDEN)
