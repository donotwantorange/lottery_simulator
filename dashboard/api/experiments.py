"""Authenticated experiment configuration endpoints."""

import json

from django.db import OperationalError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from dashboard.api.errors import APIError, error_response
from dashboard.api.pools import _actor_or_error, _json_body, _page, _validated
from dashboard.api.serializers import (
    ExperimentConfigSerializer, ExperimentImportConfirmSerializer,
    ExperimentImportPreviewSerializer, ExperimentSaveSerializer, StrictRevisionField,
)
from dashboard.models import ExperimentConfig
from dashboard.services.accounts import AccountError
from dashboard.services.experiments import (
    ExperimentError, confirm_experiment_import, delete_experiment, export_experiment,
    import_preview, save_experiment, visible_experiments,
)


def _error(error):
    if isinstance(error, ExperimentError):
        return error_response(error.code, str(error), error.status)
    if isinstance(error, OperationalError) and (
        "locked" in str(error).lower() or "busy" in str(error).lower()
    ):
        return error_response("storage_busy", "存储暂忙，请稍后重试", 503)
    from dashboard.api.pools import _error_response
    return _error_response(error)


def _ensure_fields(data, allowed):
    if not isinstance(data, dict):
        raise APIError("validation_error", "请求必须是JSON对象", 400)
    extras = data.keys() - set(allowed)
    if extras:
        raise APIError("validation_error", "请求包含不支持字段", 400,
                       {key: ["不支持的字段"] for key in sorted(extras)})


def _ensure_config_fields(data):
    _ensure_fields(data, {"name", "pool_ref", "parameters", "owner_id"})
    if "pool_ref" in data:
        _ensure_fields(data["pool_ref"], {"id", "name"})
    if "parameters" in data:
        _ensure_fields(data["parameters"], {
            "draws", "trials", "initial_pity", "initial_five_star_pity", "seed", "trace",
        })


def _write_payload(validated):
    return {
        "name": validated["name"],
        "pool_ref": {"id": str(validated["pool_ref"]["id"]),
                     "name": validated["pool_ref"]["name"]},
        "parameters": validated["parameters"],
    }


def _data_response(data, status=200):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def experiment_configs(request):
    try:
        actor = _actor_or_error(request)
        page = _page(request.GET.get("page"), "page", 1, 2**31 - 1)
        page_size = _page(request.GET.get("page_size"), "page_size", 50, 200)
        query = visible_experiments(actor)
        total = query.count()
        start = (page - 1) * page_size
        items = ExperimentConfigSerializer(query[start:start + page_size], many=True,
                                           context={"actor": actor}).data
        return _data_response({"items": items, "total": total,
                               "page": page, "page_size": page_size})
    except (APIError, ExperimentError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@csrf_protect
@require_POST
def create_experiment_config(request):
    try:
        actor = _actor_or_error(request)
        data = _json_body(request)
        _ensure_config_fields(data)
        values = _validated(ExperimentSaveSerializer, data)
        config = save_experiment(actor, _write_payload(values), owner_id=values.get("owner_id"))
        config = ExperimentConfig.objects.select_related("owner", "pool").get(pk=config.pk)
        return _data_response(ExperimentConfigSerializer(config, context={"actor": actor}).data,
                              status=201)
    except (APIError, ExperimentError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@require_GET
def _experiment_config_detail(request, config_id):
    try:
        actor = _actor_or_error(request)
        try:
            config = visible_experiments(actor).get(pk=config_id)
        except (ExperimentConfig.DoesNotExist, ValueError):
            raise ExperimentError("实验配置不存在或无权管理", status=404,
                                  code="not_found") from None
        return _data_response(ExperimentConfigSerializer(config, context={"actor": actor}).data)
    except (APIError, ExperimentError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@csrf_protect
def experiment_config_mutation(request, config_id):
    try:
        actor = _actor_or_error(request)
        data = _json_body(request)
        if request.method == "PATCH":
            _ensure_fields(data, {"name", "pool_ref", "parameters", "expected_revision"})
            _ensure_config_fields({key: value for key, value in data.items()
                                   if key != "expected_revision"})
            if "expected_revision" not in data:
                raise APIError("validation_error", "缺少expected_revision", 400)
            controls = _validated(RevisionOnlySerializer, {
                "expected_revision": data["expected_revision"]
            })
            payload_data = {key: data[key] for key in ("name", "pool_ref", "parameters")
                            if key in data}
            values = _validated(ExperimentSaveSerializer, payload_data)
            config = save_experiment(actor, _write_payload(values), config_id=config_id,
                                     expected_revision=controls["expected_revision"])
            config = ExperimentConfig.objects.select_related("owner", "pool").get(pk=config.pk)
            return _data_response(ExperimentConfigSerializer(config, context={"actor": actor}).data)
        if request.method == "DELETE":
            _ensure_fields(data, {"expected_revision"})
            if set(data) != {"expected_revision"}:
                raise APIError("validation_error", "删除仅接受expected_revision", 400)
            controls = _validated(RevisionOnlySerializer, data)
            delete_experiment(actor, config_id, expected_revision=controls["expected_revision"])
            return HttpResponse(status=204)
        return HttpResponse(status=405)
    except (APIError, ExperimentError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


class RevisionOnlySerializer(serializers.Serializer):
    expected_revision = StrictRevisionField(min_value=1)


@csrf_protect
@require_POST
def preview_experiment_import(request):
    try:
        actor = _actor_or_error(request)
        body = _json_body(request)
        _ensure_fields(body, {"document", "owner_id"})
        values = _validated(ExperimentImportPreviewSerializer, body)
        result = import_preview(actor, values["document"], owner_id=values.get("owner_id"))
        return _data_response(result)
    except (APIError, ExperimentError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@csrf_protect
@require_POST
def confirm_experiment_import_view(request):
    try:
        actor = _actor_or_error(request)
        body = _json_body(request)
        _ensure_fields(body, {"document", "pool_id", "pool_revision", "owner_id"})
        values = _validated(ExperimentImportConfirmSerializer, body)
        config = confirm_experiment_import(
            actor, values["document"], pool_id=values["pool_id"],
            pool_revision=values["pool_revision"], owner_id=values.get("owner_id"),
        )
        config = ExperimentConfig.objects.select_related("owner", "pool").get(pk=config.pk)
        return _data_response(ExperimentConfigSerializer(config, context={"actor": actor}).data,
                              status=201)
    except (APIError, ExperimentError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


@require_GET
def export_experiment_view(request, config_id):
    try:
        actor = _actor_or_error(request)
        value = request.GET.get("expected_revision")
        if value is None or not value.isdecimal():
            raise APIError("validation_error", "缺少有效expected_revision", 400)
        document = export_experiment(actor, config_id, expected_revision=int(value))
        response = HttpResponse(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                                content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="experiment.json"'
        response["Cache-Control"] = "no-store"
        return response
    except (APIError, ExperimentError, AccountError, ValidationError, OperationalError) as error:
        return _error(error)


def experiment_config_collection(request):
    if request.method == "GET":
        return experiment_configs(request)
    if request.method == "POST":
        return create_experiment_config(request)
    return HttpResponse(status=405)


def experiment_config_resource(request, config_id):
    if request.method == "GET":
        return _experiment_config_detail(request, config_id)
    if request.method in {"PATCH", "DELETE"}:
        return experiment_config_mutation(request, config_id)
    return HttpResponse(status=405)
