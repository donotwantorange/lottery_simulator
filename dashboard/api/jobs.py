"""Authenticated simulation endpoints; no filesystem paths cross this boundary."""

from django.db import OperationalError
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from dashboard.api.errors import APIError, error_response
from dashboard.api.experiments import _data_response
from dashboard.api.pools import _actor_or_error, _error_response, _json_body, _page
from dashboard.services.accounts import AccountError
from dashboard.jobs import JobStateUnavailable
from dashboard.services.runs import (
    RunError, cancel_job, get_job_for_actor, get_job_result_for_actor, preview_submission,
    get_job_trace_reader_for_actor, job_busy, job_detail, list_my_jobs,
    pagination, resave_job_for_actor, safe_json, submit_job,
)


ERRORS = (APIError, RunError, AccountError, OperationalError, ValueError, JobStateUnavailable)


def _error(error):
    if isinstance(error, JobStateUnavailable):
        return error_response("storage_busy", "任务状态暂不可用，请稍后重试", 503)
    if isinstance(error, RunError):
        return error_response(error.code, str(error), error.status)
    if isinstance(error, OperationalError):
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            return error_response("storage_busy", "存储暂忙，请稍后重试", 503)
        return error_response("storage_busy", "存储暂不可用", 503)
    if isinstance(error, ValueError) and not isinstance(error, AccountError):
        return error_response("validation_error", "请求参数或结果格式无效", 400)
    return _error_response(error)


def _pagination(request):
    return (_page(request.GET.get("page"), "page", 1, 2**31 - 1),
            _page(request.GET.get("page_size"), "page_size", 50, 200))


@csrf_protect
@require_POST
def create_job(request):
    try:
        state = submit_job(_actor_or_error(request), _json_body(request))
        return _data_response(job_detail(state), status=202)
    except ERRORS as error:
        return _error(error)


@csrf_protect
@require_POST
def preview(request):
    try:
        return _data_response(preview_submission(_actor_or_error(request), _json_body(request)))
    except ERRORS as error:
        return _error(error)


@require_GET
def busy(request):
    try:
        return _data_response(job_busy(_actor_or_error(request)))
    except ERRORS as error:
        return _error(error)


@require_GET
def mine(request):
    try:
        if request.GET.keys() - {"page", "page_size"}:
            raise RunError("本人任务列表不接受所有者筛选")
        return _data_response(list_my_jobs(_actor_or_error(request), *_pagination(request)))
    except ERRORS as error:
        return _error(error)


@require_GET
def detail(request, job_id):
    try:
        return _data_response(job_detail(get_job_for_actor(_actor_or_error(request), job_id)))
    except ERRORS as error:
        return _error(error)


@csrf_protect
@require_POST
def cancel(request, job_id):
    try:
        return _data_response(job_detail(cancel_job(_actor_or_error(request), job_id)))
    except ERRORS as error:
        return _error(error)


@csrf_protect
@require_POST
def resave(request, job_id):
    try:
        return _data_response(job_detail(resave_job_for_actor(_actor_or_error(request), job_id)))
    except ERRORS as error:
        return _error(error)


@require_GET
def result(request, job_id):
    try:
        return _data_response(get_job_result_for_actor(_actor_or_error(request), job_id))
    except ERRORS as error:
        return _error(error)


@require_GET
def trace(request, job_id):
    try:
        from dashboard.api.runs import _trace_filter
        actor = _actor_or_error(request)
        page, page_size = _pagination(request)
        start = pagination(page, page_size)
        if page_size not in {50, 100, 200}:
            raise RunError("逐抽分页大小必须是50、100或200")
        reader = get_job_trace_reader_for_actor(actor, job_id)
        filters = _trace_filter(request)
        items = reader.query_events(filters, limit=page_size, offset=start)
        total = reader.count_events(filters)
        return _data_response({"items": safe_json(items), "total": str(total),
                               "page": page, "page_size": page_size})
    except ERRORS as error:
        return _error(error)


@require_GET
def charts(request, job_id):
    try:
        from dashboard.api.runs import _position_chart, _summary_charts
        actor = _actor_or_error(request)
        payload = get_job_result_for_actor(actor, job_id, serialize=False)
        if request.GET.get("kind", "summary") == "summary":
            return _data_response(_summary_charts(request, payload))
        if request.GET["kind"] != "position":
            raise RunError("图表类型必须是summary或position")
        return _data_response(_position_chart(request, get_job_trace_reader_for_actor(actor, job_id), payload))
    except ERRORS as error:
        return _error(error)
