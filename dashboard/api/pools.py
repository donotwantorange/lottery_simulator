"""Authenticated pool endpoints."""

import json

from django.db import OperationalError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework.exceptions import ValidationError
from rest_framework import serializers

from dashboard.api.auth import require_actor
from dashboard.api.errors import APIError, error_response
from dashboard.api.query import query_integer
from dashboard.api.serializers import (PoolControlsSerializer, PoolCopySerializer,
                                       PoolSerializer, StrictSerializer)
from dashboard.models import Pool
from dashboard.services.accounts import AccountError
from dashboard.services.pools import (
    PoolError, confirm_pool_import, copy_pool, delete_pool, export_pool,
    preview_pool_import, save_pool, visible_pools,
)
from lottery_simulator.config_documents import MAX_CONFIG_BYTES, parse_config_json


_DOCUMENT_FIELDS = {
    "format_version", "id", "name", "original_author", "rule_ref", "rarity_pools",
    "rarity_labels", "rewards", "mechanism_targets",
}


def _json_body(request, *, max_bytes=MAX_CONFIG_BYTES):
    if len(request.body) > max_bytes:
        raise APIError("validation_error", "请求内容过大", 400)
    try:
        return parse_config_json(request.body, max_bytes)
    except ValueError as error:
        raise APIError("validation_error", str(error), 400) from error


def _validated(serializer_class, data):
    serializer = serializer_class(data=data)
    if not serializer.is_valid():
        raise ValidationError(serializer.errors)
    return serializer.validated_data


def _pool_payload(data, *, controls=()):
    allowed = _DOCUMENT_FIELDS | set(controls)
    extras = data.keys() - allowed
    if extras:
        raise APIError("validation_error", "请求包含不支持字段", 400,
                       {key: ["不支持的字段"] for key in sorted(extras)})
    if _DOCUMENT_FIELDS - data.keys():
        raise APIError("validation_error", "池配置缺少字段", 400)
    return {key: data[key] for key in _DOCUMENT_FIELDS} | {
        key: data[key] for key in controls if key in data
    }


def _actor_or_error(request):
    try:
        return require_actor(request)
    except AccountError as error:
        raise APIError("unauthenticated", str(error), 401) from error


def _error_response(error):
    if isinstance(error, APIError):
        return error_response(error.code, error.message, error.status, error.fields)
    if isinstance(error, PoolError):
        return error_response(error.code, str(error), error.status)
    if isinstance(error, AccountError):
        code, status = ("unauthenticated", 401) if str(error) == "请重新登录" else ("validation_error", 400)
        return error_response(code, str(error), status)
    if isinstance(error, ValidationError):
        return error_response("validation_error", "请求参数无效", 400, error.detail)
    if isinstance(error, OperationalError) and (
        "locked" in str(error).lower() or "busy" in str(error).lower()
    ):
        return error_response("storage_busy", "存储暂忙，请稍后重试", 503)
    raise error


def _pool_or_404(actor, pool_id):
    try:
        return visible_pools(actor).select_related("owner").get(pk=pool_id)
    except (Pool.DoesNotExist, ValueError):
        raise PoolError("角色池不存在或不可访问", status=404, code="not_found") from None


def _page(value, label, default, maximum):
    if value is None:
        return default
    number = query_integer(value, label)
    if number < 1 or number > maximum:
        raise APIError("validation_error", f"{label}必须在1至{maximum}之间", 400)
    return number


@require_GET
def pools(request):
    try:
        actor = _actor_or_error(request)
        page = _page(request.GET.get("page"), "page", 1, 2**31 - 1)
        page_size = _page(request.GET.get("page_size"), "page_size", 50, 200)
        query = visible_pools(actor).select_related("owner", "rule").order_by("name", "id")
        total = query.count()
        start = (page - 1) * page_size
        items = PoolSerializer(query[start:start + page_size], many=True).data
        response = JsonResponse({"items": items, "total": total, "page": page, "page_size": page_size})
        response["Cache-Control"] = "no-store"
        return response
    except (APIError, PoolError, AccountError, ValidationError) as error:
        return _error_response(error)


@require_GET
def pool_detail(request, pool_id):
    try:
        actor = _actor_or_error(request)
        pool = _pool_or_404(actor, pool_id)
        pool = Pool.objects.select_related("owner", "rule").get(pk=pool.pk)
        response = JsonResponse(PoolSerializer(pool).data)
        response["Cache-Control"] = "no-store"
        return response
    except (APIError, PoolError, AccountError, ValidationError) as error:
        return _error_response(error)


@csrf_protect
@require_POST
def create_pool(request):
    try:
        actor = _actor_or_error(request)
        data = _json_body(request)
        controls = _validated(PoolCreateControlsSerializer, {
            key: data[key] for key in ("kind", "visibility", "expected_rule_revision") if key in data
        })
        payload = _pool_payload(data, controls=("kind", "visibility", "expected_rule_revision"))
        pool = save_pool(actor, payload, expected_rule_revision=controls["expected_rule_revision"])
        response = JsonResponse(PoolSerializer(pool).data, status=201)
        response["Cache-Control"] = "no-store"
        return response
    except (APIError, PoolError, AccountError, ValidationError) as error:
        return _error_response(error)


def pool_collection(request):
    if request.method == "GET":
        return pools(request)
    if request.method == "POST":
        return create_pool(request)
    return HttpResponse(status=405)


@csrf_protect
@require_POST
def import_pool(request):
    return preview_pool_import_view(request)


@csrf_protect
def pool_mutation(request, pool_id):
    if request.method == "PATCH":
        try:
            actor = _actor_or_error(request)
            data = _json_body(request)
            controls = _validated(PoolControlsSerializer, {
                key: data[key] for key in ("kind", "visibility", "expected_revision",
                                           "expected_rule_revision", "rarity_mapping",
                                           "clear_unmapped") if key in data
            })
            if {"expected_revision", "expected_rule_revision"} - controls.keys():
                raise APIError("validation_error", "缺少expected_revision或expected_rule_revision", 400)
            payload = _pool_payload(data, controls=("kind", "visibility", "expected_revision",
                                                    "expected_rule_revision", "rarity_mapping",
                                                    "clear_unmapped"))
            pool = save_pool(actor, payload, pool_id=pool_id,
                             expected_revision=controls["expected_revision"],
                             expected_rule_revision=controls["expected_rule_revision"],
                             rarity_mapping=controls.get("rarity_mapping"),
                             clear_unmapped=controls.get("clear_unmapped", False))
            response = JsonResponse(PoolSerializer(pool).data)
            response["Cache-Control"] = "no-store"
            return response
        except (APIError, PoolError, AccountError, ValidationError) as error:
            return _error_response(error)
    if request.method == "DELETE":
        try:
            actor = _actor_or_error(request)
            data = _json_body(request)
            controls = _validated(PoolControlsSerializer, data)
            if set(data) != {"expected_revision"}:
                raise APIError("validation_error", "删除仅接受expected_revision", 400)
            if "expected_revision" not in controls:
                raise APIError("validation_error", "缺少expected_revision", 400)
            delete_pool(actor, pool_id, expected_revision=controls["expected_revision"])
            return HttpResponse(status=204)
        except (APIError, PoolError, AccountError, ValidationError) as error:
            return _error_response(error)
    return HttpResponse(status=405)


def pool_resource(request, pool_id):
    if request.method == "GET":
        return pool_detail(request, pool_id)
    return pool_mutation(request, pool_id)


@csrf_protect
@require_POST
def copy_pool_view(request, pool_id):
    try:
        actor = _actor_or_error(request)
        data = _json_body(request)
        allowed = {"name", "kind", "expected_revision", "expected_source_rule_revision",
                   "rule_ref", "expected_rule_revision", "rarity_mapping", "clear_unmapped"}
        if not isinstance(data, dict) or data.keys() - allowed:
            raise APIError("validation_error", "复制请求包含不支持字段", 400)
        required = {"name", "kind", "expected_revision", "expected_source_rule_revision"}
        if required - data.keys():
            raise APIError("validation_error", "复制请求缺少必需字段", 400)
        values = _validated(PoolCopySerializer, data)
        pool = copy_pool(actor, pool_id, **values)
        pool = Pool.objects.select_related("owner", "rule").get(pk=pool.pk)
        response = JsonResponse(PoolSerializer(pool).data, status=201)
        response["Cache-Control"] = "no-store"
        return response
    except (APIError, PoolError, AccountError, ValidationError) as error:
        return _error_response(error)


@require_GET
def export_pool_view(request, pool_id):
    try:
        actor = _actor_or_error(request)
        raw_revision = request.GET.get("expected_revision")
        from dashboard.api.serializers import StrictRevisionField
        revision = _validated(ExportRevisionSerializer, {
            "expected_revision": query_integer(raw_revision, "expected_revision")
        })
        document = export_pool(actor, pool_id, expected_revision=revision["expected_revision"])
        response = HttpResponse(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                                content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="pool.json"'
        response["Cache-Control"] = "no-store"
        return response
    except (APIError, PoolError, AccountError, ValidationError) as error:
        return _error_response(error)


@csrf_protect
@require_POST
def preview_pool_import_view(request):
    try:
        actor = _actor_or_error(request)
        body = _json_body(request)
        document = body["document"] if set(body) == {"document"} else body
        return JsonResponse(preview_pool_import(actor, document))
    except (APIError, PoolError, AccountError, ValidationError) as error:
        return _error_response(error)


@csrf_protect
@require_POST
def confirm_pool_import_view(request):
    try:
        actor = _actor_or_error(request)
        body = _json_body(request)
        if not isinstance(body, dict) or set(body) != {"document", "rule_id", "rule_revision"}:
            raise APIError("validation_error", "导入确认字段无效", 400)
        from dashboard.api.serializers import StrictRevisionField
        class Confirm(StrictSerializer):
            rule_id = serializers.UUIDField()
            rule_revision = StrictRevisionField(min_value=1)
        values = _validated(Confirm, {key: body[key] for key in ("rule_id", "rule_revision")})
        pool = confirm_pool_import(actor, body["document"], **values)
        pool = Pool.objects.select_related("owner", "rule").get(pk=pool.pk)
        return JsonResponse(PoolSerializer(pool).data, status=201)
    except (APIError, PoolError, AccountError, ValidationError) as error:
        return _error_response(error)


class ExportRevisionSerializer(StrictSerializer):
    from dashboard.api.serializers import StrictRevisionField
    expected_revision = StrictRevisionField(min_value=1)


class PoolCreateControlsSerializer(StrictSerializer):
    from dashboard.api.serializers import StrictRevisionField
    kind = serializers.ChoiceField(choices=("public", "private"), required=False)
    visibility = serializers.ChoiceField(choices=("public", "hidden"), required=False)
    expected_rule_revision = StrictRevisionField(min_value=1)
