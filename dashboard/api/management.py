"""Explicit account administration; no generic model CRUD."""

from django.db import OperationalError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_protect

from dashboard.api.errors import APIError, error_response
from dashboard.api.pools import _actor_or_error, _error_response, _json_body, _page
from dashboard.models import AppMeta, ExperimentConfig, Pool, SimulationRun, User
from dashboard.services.accounts import (
    AccountError, DeleteIncomplete, _admin_actor, create_account, delete_account,
    reset_password, unlock_login, update_account,
)


def _summary(user):
    return {"id": str(user.pk), "username": user.username,
            "role": "admin" if user.is_superuser else "user",
            "enabled": user.is_active, "deleting": user.deleting,
            "must_change_password": user.must_change_password}


def _response(data, status=200):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _fields(data, allowed, required=()):
    if data.keys() - set(allowed) or set(required) - data.keys():
        raise APIError("validation_error", "账号操作字段无效", 400)


def _target(target_id):
    try:
        return User.objects.get(pk=target_id)
    except User.DoesNotExist:
        raise APIError("not_found", "账号不存在", 404) from None


def _deletion_scope(target):
    """Preview counts only; confirmation rechecks live state in delete_account."""
    from dashboard.services.runs import get_manager

    manager = get_manager()
    jobs = [state for path in manager.root.glob("*/state.json")
            if (state := manager.get(path.parent.name)) is not None
            and state.owner_id == str(target.pk)]
    manifest = AppMeta.objects.filter(key=f"account_deletion:{target.pk}").first()
    known_job_ids = {state.job_id for state in jobs}
    if manifest is not None:
        known_job_ids.update(manifest.value)
    exports = 0
    from django.conf import settings
    from pathlib import Path
    directory = Path(settings.EXPORTS_DIR)
    if directory.exists() and not directory.is_symlink():
        exports = sum(1 for path in directory.glob(f"user_{target.pk.hex}_*.jsonl")
                       if path.is_file() and not path.is_symlink())
    return {
        "private_pools": str(Pool.objects.filter(owner=target).count()),
        "experiment_configs": str(ExperimentConfig.objects.filter(owner=target).count()),
        "runs": str(SimulationRun.objects.filter(owner=target).count()),
        "job_directories": str(len(known_job_ids)),
        "export_files": str(exports),
        "other_users_pool_references": str(ExperimentConfig.objects.filter(
            pool__owner=target).exclude(owner=target).count()),
        "public_pools_preserved": str(Pool.objects.filter(kind=Pool.PUBLIC).count()),
    }


def _error(error):
    if isinstance(error, User.DoesNotExist):
        return error_response("not_found", "账号不存在", 404)
    if isinstance(error, DeleteIncomplete):
        return error_response("delete_incomplete", str(error), 409)
    if isinstance(error, AccountError):
        if str(error) == "请重新登录":
            return error_response("unauthenticated", str(error), 401)
        if str(error) == "无权管理账号":
            return error_response("forbidden", str(error), 403)
        return error_response("validation_error", str(error), 400)
    return _error_response(error)


@csrf_protect
def users(request):
    try:
        actor = _actor_or_error(request)
        _admin_actor(actor)
        if request.method == "GET":
            page = _page(request.GET.get("page"), "page", 1, 2**31 - 1)
            size = _page(request.GET.get("page_size"), "page_size", 50, 200)
            query = User.objects.order_by("username_key", "id")
            start = (page - 1) * size
            return _response({"items": [_summary(user) for user in query[start:start + size]],
                              "total": query.count(), "page": page, "page_size": size})
        if request.method == "POST":
            data = _json_body(request)
            _fields(data, {"username", "password", "role"}, {"username", "password"})
            role = data.get("role", "user")
            if role not in ("admin", "user"):
                raise AccountError("角色无效")
            user = create_account(actor, data["username"], data["password"], admin=role == "admin")
            return _response(_summary(user), 201)
        return HttpResponse(status=405)
    except (APIError, AccountError, OperationalError, User.DoesNotExist) as error:
        return _error(error)


@csrf_protect
def user_resource(request, target_id):
    try:
        actor = _actor_or_error(request)
        _admin_actor(actor)
        target = _target(target_id)
        if request.method == "GET":
            return _response({**_summary(target), "delete_impact": _deletion_scope(target)})
        if request.method == "PATCH":
            data = _json_body(request)
            _fields(data, {"username", "role", "enabled"})
            return _response(_summary(update_account(actor, target.pk, data)))
        if request.method == "DELETE":
            data = _json_body(request)
            _fields(data, {"confirm"}, {"confirm"})
            if data["confirm"] is not True:
                raise AccountError("请二次确认删除账号及其个人数据")
            delete_account(actor, target.pk)
            return HttpResponse(status=204)
        return HttpResponse(status=405)
    except (APIError, AccountError, OperationalError, User.DoesNotExist) as error:
        return _error(error)


@csrf_protect
def password_reset(request, target_id):
    try:
        actor = _actor_or_error(request)
        _admin_actor(actor)
        target = _target(target_id)
        if request.method != "POST":
            return HttpResponse(status=405)
        data = _json_body(request)
        _fields(data, {"password"}, {"password"})
        return _response(_summary(reset_password(actor, target.pk, data["password"])))
    except (APIError, AccountError, OperationalError, User.DoesNotExist) as error:
        return _error(error)


@csrf_protect
def login_unlock(request, target_id):
    try:
        actor = _actor_or_error(request)
        _admin_actor(actor)
        target = _target(target_id)
        if request.method != "POST":
            return HttpResponse(status=405)
        _fields(_json_body(request), set())
        unlock_login(actor, target.username)
        return _response({"message": "账号登录限制已解除，启用状态未改变"})
    except (APIError, AccountError, OperationalError, User.DoesNotExist) as error:
        return _error(error)


def jobs(request):
    """List retained jobs across users for administrators only."""
    try:
        actor = _actor_or_error(request)
        _admin_actor(actor)
        if request.method != "GET":
            return HttpResponse(status=405)
        page = _page(request.GET.get("page"), "page", 1, 2**31 - 1)
        size = _page(request.GET.get("page_size"), "page_size", 50, 200)
        from datetime import datetime
        from dashboard.services.runs import get_manager, job_summary

        manager = get_manager()
        states = [state for path in manager.root.glob("*/state.json")
                  if (state := manager.get(path.parent.name)) is not None]
        states.sort(key=lambda state: (datetime.fromisoformat(state.accepted_at), state.job_id),
                    reverse=True)
        owners = {str(user.pk): user.username
                  for user in User.objects.filter(pk__in={state.owner_id for state in states})}
        items = [{**job_summary(state), "owner_id": state.owner_id,
                  "owner_name": owners.get(state.owner_id, "已删除账号")}
                 for state in states[(page - 1) * size:page * size]]
        return _response({"items": items, "total": len(states), "page": page,
                          "page_size": size})
    except (APIError, AccountError, OperationalError) as error:
        return _error(error)
