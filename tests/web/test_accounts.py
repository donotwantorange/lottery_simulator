from django.test import RequestFactory, TestCase
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from unittest.mock import patch

from dashboard.models import AppMeta, LoginLimit, Pool, User
from dashboard.services.accounts import (
    AccountError, create_account, normalize_username, update_account,
    validate_password, login_blocked, login_source, record_login_failure,
)


class AccountServiceTests(TestCase):
    def test_password_and_username_boundaries(self):
        with self.assertRaises(AccountError):
            validate_password("12345")
        self.assertEqual(validate_password("123456"), "123456")
        self.assertEqual(normalize_username("  Admin  "), ("Admin", "admin"))

    def test_last_available_admin_cannot_be_disabled_or_demoted(self):
        admin = create_account(None, "admin", "123456", admin=True,
                               must_change_password=False)
        with self.assertRaisesRegex(AccountError, "最后一个可用管理员"):
            update_account(admin, admin.pk, {"enabled": False})
        with self.assertRaisesRegex(AccountError, "最后一个可用管理员"):
            update_account(admin, admin.pk, {"role": "user"})
        self.assertTrue(User.objects.get(pk=admin.pk).is_superuser)

    def test_username_change_revokes_old_session_version(self):
        admin = create_account(None, "admin", "123456", admin=True,
                               must_change_password=False)
        user = create_account(admin, "Alice", "123456")
        previous = user.auth_version
        update_account(admin, user.pk, {"username": "alice2"})
        self.assertEqual(User.objects.get(pk=user.pk).auth_version, previous + 1)

    def test_init_admin_creates_pool_once(self):
        with patch("dashboard.management.commands.init_admin.getpass", side_effect=["123456", "123456"]):
            call_command("init_admin", username="first")
        self.assertTrue(AppMeta.objects.filter(key="initialized").exists())
        self.assertEqual(Pool.objects.filter(kind="public", owner=None).count(), 1)
        with self.assertRaises(CommandError):
            call_command("init_admin", username="second")

    def test_account_and_source_failures_are_separate(self):
        for _ in range(5):
            record_login_failure("unknown", "127.0.0.1")
        self.assertTrue(login_blocked("unknown", "different"))
        self.assertFalse(login_blocked("other", "127.0.0.1"))
        for _ in range(15):
            record_login_failure("other", "127.0.0.1")
        self.assertTrue(login_blocked("other", "127.0.0.1"))

    def test_untrusted_forwarded_header_does_not_choose_source(self):
        request = RequestFactory().get("/api/v1/auth/login/",
            HTTP_X_FORWARDED_FOR="203.0.113.8", REMOTE_ADDR="198.51.100.5")
        self.assertEqual(login_source(request), "198.51.100.5")

    def test_unlock_preserves_disabled_account_and_source_bucket(self):
        admin = create_account(None, "admin", "123456", admin=True, must_change_password=False)
        disabled = create_account(admin, "disabled", "123456", must_change_password=False)
        User.objects.filter(pk=disabled.pk).update(is_active=False)
        for _ in range(20):
            record_login_failure("disabled", "127.0.0.1")
        call_command("unlock_login", username="disabled")
        self.assertFalse(LoginLimit.objects.filter(scope="account", key="disabled").exists())
        self.assertTrue(login_blocked("someone", "127.0.0.1"))
        self.assertFalse(User.objects.get(pk=disabled.pk).is_active)

    def test_maintenance_commands_cannot_bypass_password_or_role_rules(self):
        admin = create_account(None, "admin", "123456", admin=True, must_change_password=False)
        ordinary = create_account(admin, "ordinary", "123456", must_change_password=False)
        for command in ("createsuperuser", "changepassword"):
            self.assertEqual(get_commands()[command], "dashboard")
            with self.subTest(command=command), self.assertRaises(CommandError):
                call_command(command)
        for username, password in (("admin", "12345"), ("ordinary", "abcdef")):
            with self.subTest(username=username), patch(
                "dashboard.management.commands.reset_admin_password.getpass",
                side_effect=[password, password]), self.assertRaises(CommandError):
                call_command("reset_admin_password", username=username)
        self.assertTrue(User.objects.get(pk=ordinary.pk).check_password("123456"))
        User.objects.filter(pk=admin.pk).update(is_active=False)
        with patch("dashboard.management.commands.reset_admin_password.getpass",
                   side_effect=["abcdef", "abcdef"]):
            call_command("reset_admin_password", username="admin")
        admin.refresh_from_db()
        self.assertTrue(admin.check_password("abcdef"))
        self.assertTrue(admin.must_change_password)
        self.assertFalse(admin.is_active)
        self.assertEqual(admin.auth_version, 2)
