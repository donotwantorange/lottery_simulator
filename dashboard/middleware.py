"""Validate server-side sessions on every protected API request."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.utils import timezone


def auth_error(message="请重新登录"):
    response = JsonResponse({"error": {"code": "unauthenticated", "message": message,
                                       "fields": {}}}, status=401)
    response["Cache-Control"] = "no-store"
    return response


class AccountSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # AuthenticationMiddleware must run first.
        if request.path.startswith("/api/") and request.user.is_authenticated:
            user = request.user
            session = request.session
            created = session.get("created_at")
            active = session.get("last_activity_at")
            version = session.get("auth_version")
            now = timezone.now()
            try:
                created_at = timezone.datetime.fromisoformat(created)
                active_at = timezone.datetime.fromisoformat(active)
            except (TypeError, ValueError):
                created_at = active_at = now - timedelta(days=2)
            expired = (now - created_at).total_seconds() >= settings.LOTTERY_ABSOLUTE_SECONDS or (
                now - active_at).total_seconds() >= settings.LOTTERY_IDLE_SECONDS
            if not user.is_active or user.deleting or version != user.auth_version or expired:
                logout(request)
                return auth_error()
            allowed = {"/api/v1/auth/me/", "/api/v1/auth/csrf/",
                       "/api/v1/auth/change-password/", "/api/v1/auth/logout/"}
            if user.must_change_password and request.path not in allowed:
                response = JsonResponse({"error": {"code": "forbidden",
                     "message": "请先修改密码", "fields": {}}}, status=403)
                response["Cache-Control"] = "no-store"
                return response
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store"
            # Only successful explicit actions renew idleness; failed CSRF and polling do not.
            if (request.user.is_authenticated and request.method in {"POST", "PATCH", "DELETE"}
                    and response.status_code < 400 and request.path not in {
                        "/api/v1/auth/login/", "/api/v1/auth/logout/",
                        "/api/v1/auth/change-password/",
                    } and "/download" not in request.path):
                request.session["last_activity_at"] = timezone.now().isoformat()
        return response
