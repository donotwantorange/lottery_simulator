"""History, Trace and controlled chart API adapters."""

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET

from dashboard.api.experiments import _data_response
from dashboard.api.jobs import ERRORS, _error, _pagination
from dashboard.api.pools import _actor_or_error
from dashboard.repository import HistoryRepository
from dashboard.services.runs import (
    RunError, decimal_integer, delete_run_for_actor, get_run_for_actor,
    get_trace_reader_for_actor, list_runs_for_actor, query_trace_for_actor, safe_json,
)
from dashboard.trace_store import TraceFilter


def _optional_int(request, name, default=None):
    value = request.GET.get(name)
    return default if value is None else decimal_integer(value, name, minimum=1)


def _trace_filter(request):
    values = {name: _optional_int(request, name) for name in (
        "trial_from", "trial_to", "source_from", "source_to")}
    values["source"] = request.GET.get("source")
    rarity = request.GET.get("rarity")
    values["rarity"] = None if rarity is None else decimal_integer(rarity, "rarity", minimum=4, maximum=6)
    values["character_name"] = request.GET.get("character_name")
    unnamed = request.GET.get("unnamed_character", "false")
    if unnamed not in {"true", "false"}:
        raise RunError("未配置角色筛选必须是true或false")
    values["unnamed_character"] = unnamed == "true"
    return TraceFilter(**values)


@require_GET
def collection(request):
    try:
        filters = {}
        if request.GET.get("rule_name"):
            filters["rule_name"] = request.GET["rule_name"]
        if "trace" in request.GET:
            if request.GET["trace"] not in {"true", "false"}:
                raise RunError("trace筛选必须是true或false")
            filters["trace_enabled"] = request.GET["trace"] == "true"
        return _data_response(list_runs_for_actor(_actor_or_error(request), *_pagination(request), filters=filters))
    except ERRORS as error:
        return _error(error)


@csrf_protect
def resource(request, run_id):
    try:
        actor = _actor_or_error(request)
        if request.method == "GET":
            return _data_response(safe_json(HistoryRepository.summary(get_run_for_actor(actor, run_id))))
        if request.method == "DELETE":
            delete_run_for_actor(actor, run_id)
            return HttpResponse(status=204)
        return HttpResponse(status=405)
    except ERRORS as error:
        return _error(error)


@require_GET
def trace(request, run_id):
    try:
        return _data_response(query_trace_for_actor(_actor_or_error(request), run_id,
                                                   _trace_filter(request), **dict(zip(
                                                       ("page", "page_size"), _pagination(request)))))
    except ERRORS as error:
        return _error(error)


def _position_chart(request, reader, payload):
    source = request.GET.get("source", "main")
    if source not in {"main", "bonus"}:
        raise RunError("图表来源必须是main或bonus")
    mode = request.GET.get("mode", "count")
    if mode not in {"count", "rate"}:
        raise RunError("图表模式必须是count或rate")
    selected = request.GET.getlist("rarity") if "rarity" in request.GET else ["4", "5", "6"]
    if selected == [""]:
        selected = []
    rarities = {decimal_integer(value, "rarity", minimum=4, maximum=6) for value in selected}
    source_from = _optional_int(request, "source_from", 1)
    maximum = payload["main_draws"] if source == "main" else payload["bonus_draws"]
    if maximum == 0:
        rows = []
    else:
        rows = reader.position_counts(source=source,
            trial_from=_optional_int(request, "trial_from", 1),
            trial_to=_optional_int(request, "trial_to", payload["trials"]),
            source_from=source_from,
            source_to=_optional_int(request, "source_to", min(maximum, source_from + 999)))
    labels = payload["pool_config"].get("rarity_labels", {})
    fields = {4: "four", 5: "five", 6: "six"}
    values = [{"position": row["source_index"], "rarity": labels.get(str(rarity), f"{rarity}星"),
               "value": row[f"{fields[rarity]}_{mode}"] if mode == "rate" else row[f"{fields[rarity]}_count"]}
              for row in rows for rarity in sorted(rarities)]
    if any(abs(item["position"]) > 9007199254740991 or abs(item["value"]) > 9007199254740991 for item in values):
        raise RunError("该计数超过图表可安全呈现范围，请缩小筛选窗口")
    specification = {"$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "data": {"values": values}, "mark": "line", "encoding": {
            "x": {"field": "position", "type": "quantitative", "title": "抽次"},
            "y": {"field": "value", "type": "quantitative", "title": "比例" if mode == "rate" else "计数"},
            "color": {"field": "rarity", "type": "nominal", "title": "稀有度"}}}
    return {"spec": specification, "rarity_labels": labels}


@require_GET
def charts(request, run_id):
    try:
        actor = _actor_or_error(request)
        run = get_run_for_actor(actor, run_id)
        if request.GET.get("kind", "summary") == "summary":
            return _data_response(_summary_charts(request, run.result_json))
        if request.GET["kind"] != "position":
            raise RunError("图表类型必须是summary或position")
        return _data_response(_position_chart(request, get_trace_reader_for_actor(actor, run_id), run.result_json))
    except ERRORS as error:
        return _error(error)


def _summary_charts(request, payload):
    from dashboard.charts import summary_chart_data
    source = request.GET.get("source", "total")
    if source not in {"main", "bonus", "total"}:
        raise RunError("图表来源必须是main、bonus或total")
    return summary_chart_data(payload, source)
