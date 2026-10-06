"""Rule definition endpoints; resource policy stays in the service layer."""

import json

from django.db import OperationalError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from dashboard.api.errors import APIError, error_response
from dashboard.api.query import query_integer
from dashboard.api.pools import _actor_or_error, _json_body, _page, _validated
from dashboard.api.serializers import RuleSerializer, StrictRevisionField
from dashboard.api.serializers import StrictSerializer
from dashboard.models import Rule
from dashboard.services.accounts import AccountError
from dashboard.services.rules import (
    RuleError, copy_rule, delete_rule, export_rule, rule_document, save_rule, visible_rules,
)
from lottery_simulator.config_documents import load_rule_document


def _error(error):
    if isinstance(error, RuleError):
        return error_response(error.code, str(error), error.status)
    if isinstance(error, (TypeError, ValueError)) and not isinstance(error, AccountError):
        return error_response("validation_error", str(error), 400)
    if isinstance(error, OperationalError) and ("locked" in str(error).lower() or "busy" in str(error).lower()):
        return error_response("storage_busy", "存储暂忙，请稍后重试", 503)
    from dashboard.api.pools import _error_response
    return _error_response(error)


def _fields(data, allowed):
    if not isinstance(data, dict):
        raise APIError("validation_error", "请求必须是JSON对象", 400)
    extra = data.keys() - set(allowed)
    if extra:
        raise APIError("validation_error", "请求包含不支持字段", 400,
                       {key: ["不支持的字段"] for key in sorted(extra)})


def _output(rule, actor):
    return RuleSerializer(rule, context={"actor": actor}).data


def _page_response(actor, query):
    page = _page(query.get("page"), "page", 1, 2**31 - 1)
    page_size = _page(query.get("page_size"), "page_size", 50, 200)
    rules = visible_rules(actor).select_related("owner").order_by("name", "id")
    scope = query.get("scope", "all")
    if scope == "public":
        rules = rules.filter(kind=Rule.PUBLIC)
    elif scope == "mine":
        rules = rules.filter(kind=Rule.PRIVATE, owner=actor)
    elif scope == "others_public":
        rules = rules.filter(kind=Rule.PRIVATE, visibility=Rule.PUBLIC).exclude(owner=actor)
    elif scope == "all_private":
        if not actor.is_superuser:
            raise RuleError("仅管理员可以查看全部私有规则", status=403, code="forbidden")
        rules = rules.filter(kind=Rule.PRIVATE)
    elif scope != "all":
        raise RuleError("规则筛选无效")
    return {"items": [_output(item, actor) for item in rules[(page - 1) * page_size:page * page_size]],
            "total": rules.count(), "page": page, "page_size": page_size}


def _definition(data):
    _fields(data, {"format_version", "id", "name", "original_author", "algorithm", "rarities",
                   "big_pity", "bonus", "grant", "kind", "visibility", "expected_revision"})
    return {key: value for key, value in data.items()
            if key not in {"kind", "visibility", "expected_revision"}}


@csrf_protect
def rule_collection(request):
    try:
        actor = _actor_or_error(request)
        if request.method == "GET":
            return JsonResponse(_page_response(actor, request.GET))
        if request.method != "POST":
            return HttpResponse(status=405)
        body = _json_body(request)
        if isinstance(body, dict) and "expected_revision" in body:
            raise APIError("validation_error", "新建规则不接受expected_revision", 400)
        definition = _definition(body)
        rule = save_rule(actor, {**definition, **{key: body[key] for key in ("kind", "visibility") if key in body}})
        return JsonResponse(_output(rule, actor), status=201)
    except (APIError, RuleError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@csrf_protect
def rule_resource(request, rule_id):
    try:
        actor = _actor_or_error(request)
        query = visible_rules(actor).select_related("owner")
        try:
            rule = query.get(pk=rule_id)
        except (Rule.DoesNotExist, ValueError):
            raise RuleError("规则不存在或不可访问", status=404, code="not_found") from None
        if request.method == "GET":
            return JsonResponse(_output(rule, actor))
        body = _json_body(request)
        if request.method == "DELETE":
            _fields(body, {"expected_revision"})
            values = _validated(RevisionSerializer, body)
            delete_rule(actor, rule_id, values["expected_revision"])
            return HttpResponse(status=204)
        if request.method == "PATCH":
            _fields(body, {"document", "name", "visibility", "expected_revision"})
            if "expected_revision" not in body:
                raise APIError("validation_error", "缺少expected_revision", 400)
            values = _validated(RevisionSerializer, {"expected_revision": body["expected_revision"]})
            document = body.get("document", rule_document(rule))
            if not isinstance(document, dict):
                raise APIError("validation_error", "document必须是对象", 400)
            try:
                definition = load_rule_document(document).to_dict()
            except (TypeError, ValueError) as error:
                raise APIError("validation_error", str(error), 400) from error
            payload = {**definition, "name": body.get("name", document.get("name", rule.name)),
                       "visibility": body.get("visibility", rule.visibility)}
            saved = save_rule(actor, payload, rule_id=rule_id,
                              expected_revision=values["expected_revision"])
            return JsonResponse(_output(saved, actor))
        return HttpResponse(status=405)
    except (APIError, RuleError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@csrf_protect
@require_POST
def copy_rule_view(request, rule_id):
    try:
        actor = _actor_or_error(request)
        body = _json_body(request)
        _fields(body, {"name", "kind"})
        values = _validated(CopyRuleSerializer, body)
        rule = copy_rule(actor, rule_id, **values)
        return JsonResponse(_output(rule, actor), status=201)
    except (APIError, RuleError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@require_GET
def export_rule_view(request, rule_id):
    try:
        actor = _actor_or_error(request)
        raw = request.GET.get("expected_revision")
        values = _validated(RevisionSerializer, {
            "expected_revision": query_integer(raw, "expected_revision")
        })
        document = export_rule(actor, rule_id, expected_revision=values["expected_revision"])
        response = HttpResponse(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                                content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="rule.json"'
        response["Cache-Control"] = "no-store"
        return response
    except (APIError, RuleError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@csrf_protect
@require_POST
def preview_rule_import(request):
    try:
        actor = _actor_or_error(request)
        body = _json_body(request)
        _fields(body, {"document"})
        if "document" not in body:
            raise APIError("validation_error", "缺少document", 400)
        document = load_rule_document(body["document"]).to_dict()
        return JsonResponse({"document": document})
    except (APIError, RuleError, AccountError, ValidationError, TypeError, ValueError) as error:
        return _error(error)


@csrf_protect
@require_POST
def confirm_rule_import(request):
    try:
        actor = _actor_or_error(request)
        body = _json_body(request)
        _fields(body, {"document"})
        if "document" not in body:
            raise APIError("validation_error", "缺少document", 400)
        document = load_rule_document(body["document"]).to_dict()
        rule = save_rule(actor, document)
        return JsonResponse(_output(rule, actor), status=201)
    except (APIError, RuleError, AccountError, ValidationError, TypeError, ValueError) as error:
        return _error(error)


class RevisionSerializer(StrictSerializer):
    expected_revision = StrictRevisionField(min_value=1)


class CopyRuleSerializer(StrictSerializer):
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    kind = serializers.ChoiceField(choices=(Rule.PUBLIC, Rule.PRIVATE))
