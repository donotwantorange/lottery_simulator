import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from dashboard.models import User
from dashboard.services.accounts import create_account


class SessionTests(TestCase):
    def setUp(self):
        self.user = create_account(None, "admin", "123456", admin=True,
                                   must_change_password=False)
        self.client = Client(enforce_csrf_checks=True)

    def _csrf(self):
        response = self.client.get("/api/v1/auth/csrf/")
        return response.json()["csrf_token"]

    def _login(self):
        token = self._csrf()
        return self.client.post("/api/v1/auth/login/",
            data=json.dumps({"username": "admin", "password": "123456"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token)

    def test_anonymous_login_requires_csrf(self):
        response = self.client.post("/api/v1/auth/login/",
            data=json.dumps({"username": "admin", "password": "123456"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")

    def test_login_session_and_revoke(self):
        self.assertEqual(self._login().status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)
        User.objects.filter(pk=self.user.pk).update(auth_version=2)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_poll_does_not_extend_activity(self):
        self.assertEqual(self._login().status_code, 200)
        before = self.client.session["last_activity_at"]
        self.client.get("/api/v1/auth/me/")
        self.assertEqual(self.client.session["last_activity_at"], before)

    def test_idle_expiry_rejects_request(self):
        self.assertEqual(self._login().status_code, 200)
        session = self.client.session
        session["last_activity_at"] = (timezone.now() - timedelta(minutes=31)).isoformat()
        session.save()
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_absolute_expiry_cannot_be_renewed_by_activity(self):
        self.assertEqual(self._login().status_code, 200)
        token = self._csrf()
        session = self.client.session
        session["created_at"] = (timezone.now() - timedelta(hours=12)).isoformat()
        session["last_activity_at"] = timezone.now().isoformat()
        session.save()
        response = self.client.post("/api/v1/auth/activity/", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 401)

    def test_unknown_wrong_password_and_disabled_login_errors_are_identical(self):
        bodies = []
        for username, password, disabled in (("unknown", "123456", False),
                ("admin", "wrongpass", False), ("admin", "123456", True)):
            if disabled:
                User.objects.filter(pk=self.user.pk).update(is_active=False)
            response = self.client.post("/api/v1/auth/login/", data=json.dumps({
                "username": username, "password": password}), content_type="application/json",
                HTTP_X_CSRFTOKEN=self._csrf())
            self.assertEqual(response.status_code, 401)
            bodies.append(response.json())
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[1], bodies[2])

    def test_login_rotates_csrf_and_maintenance_reset_revokes_session(self):
        from django.core.management import call_command
        from unittest.mock import patch
        self._csrf()
        initial = self.client.cookies["csrftoken"].value
        self.assertEqual(self._login().status_code, 200)
        self._csrf()
        self.assertNotEqual(initial, self.client.cookies["csrftoken"].value)
        self.assertEqual(self.client.post("/api/v1/auth/activity/").status_code, 403)
        with patch("dashboard.management.commands.reset_admin_password.getpass",
                   side_effect=["abcdef", "abcdef"]):
            call_command("reset_admin_password", username="admin")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_forced_password_change_blocks_business_activity(self):
        User.objects.filter(pk=self.user.pk).update(must_change_password=True)
        self.assertEqual(self._login().status_code, 200)
        token = self._csrf()
        blocked = self.client.post("/api/v1/auth/activity/", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)

    def test_change_password_invalidates_other_session(self):
        self.assertEqual(self._login().status_code, 200)
        second = Client(enforce_csrf_checks=True)
        token = second.get("/api/v1/auth/csrf/").json()["csrf_token"]
        response = second.post("/api/v1/auth/login/",
            data=json.dumps({"username": "admin", "password": "123456"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        token = self._csrf()
        response = self.client.post("/api/v1/auth/change-password/",
            data=json.dumps({"current_password": "123456", "new_password": "abcdef"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(second.get("/api/v1/auth/me/").status_code, 401)
