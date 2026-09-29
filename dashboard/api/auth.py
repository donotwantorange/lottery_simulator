"""CSRF-protected browser login and account session endpoints."""

import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from dashboard.api.errors import error_response
from dashboard.services.accounts import (
    AccountError, change_password, clear_account_failures, login_blocked,
    login_source, normalize_username, record_login_failure,
)


def require_actor(request):
    actor = request.user
    if not actor.is_authenticated or not actor.is_active or actor.deleting:
        raise AccountError("请重新登录")
    return actor


def _body(request):
    if len(request.body) > 16 * 1024:
        raise AccountError("请求内容过大")
    try:
        value = json.loads(request.body)
    except (UnicodeError, ValueError):
        raise AccountError("请求必须是JSON对象") from None
    if not isinstance(value, dict):
        raise AccountError("请求必须是JSON对象")
    return value


def _ok(payload=None):
    result = JsonResponse(payload or {})
    result["Cache-Control"] = "no-store"
    return result


@ensure_csrf_cookie
@require_GET
def csrf(request):
    from django.middleware.csrf import get_token
    return _ok({"csrf_token": get_token(request)})


@csrf_protect
@require_POST
def login_view(request):
    try:
        body = _body(request)
        username = body.get("username")
        password = body.get("password")
        if not isinstance(password, str):
            raise AccountError("账号或密码错误")
        _, key = normalize_username(username)
    except AccountError:
        return error_response("unauthenticated", "账号或密码错误", 401)
    source = login_source(request)
    if login_blocked(key, source):
        return error_response("rate_limited", "登录暂时受限，请稍后再试", 429)
    user = authenticate(request, username=username, password=password)
    if user is None:
        record_login_failure(key, source)
        return error_response("unauthenticated", "账号或密码错误", 401)
    clear_account_failures(key)
    login(request, user)
    from django.utils import timezone
    now = timezone.now().isoformat()
    request.session["created_at"] = now
    request.session["last_activity_at"] = now
    request.session["auth_version"] = user.auth_version
    return _ok({"id": str(user.pk), "username": user.username,
                "role": "admin" if user.is_superuser else "user",
                "must_change_password": user.must_change_password})


@require_GET
def me(request):
    try:
        user = require_actor(request)
    except AccountError:
        return error_response("unauthenticated", "请重新登录", 401)
    return _ok({"id": str(user.pk), "username": user.username,
                "role": "admin" if user.is_superuser else "user",
                "must_change_password": user.must_change_password})


@csrf_protect
@require_POST
def logout_view(request):
    logout(request)
    return _ok()


@csrf_protect
@require_POST
def change_password_view(request):
    try:
        user = require_actor(request)
        body = _body(request)
        change_password(user, body.get("current_password"), body.get("new_password"))
    except AccountError as error:
        code = "unauthenticated" if str(error) == "请重新登录" else "validation_error"
        return error_response(code, str(error), 401 if code == "unauthenticated" else 400)
    logout(request)
    return _ok({"message": "密码已修改，请重新登录"})


@csrf_protect
@require_POST
def activity(request):
    try:
        require_actor(request)
    except AccountError:
        return error_response("unauthenticated", "请重新登录", 401)
    return _ok()
