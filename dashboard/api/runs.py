"""History, Trace and controlled chart API adapters."""

import json

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET

from dashboard.api.experiments import _data_response
from dashboard.api.jobs import ERRORS, _error, _pagination
from dashboard.api.pools import _actor_or_error
from dashboard.repository import HistoryRepository
from dashboard.services.runs import (
    RunError, decimal_integer, delete_run_for_actor, get_run_for_actor,
    get_trace_reader_for_actor, list_runs_for_actor, safe_json,
)
from dashboard.trace_store import TraceFilter


def _optional_int(request, name, default=None):
    value = request.GET.get(name)
    return default if value is None else decimal_integer(value, name, minimum=1)


def _trace_filter(request):
    allowed = {"trial_from", "trial_to", "source", "source_from", "source_to",
               "rarity_id", "character_id", "unnamed_character", "event_type",
               "main_from", "main_to", "page", "page_size"}
    if request.GET.keys() - allowed:
        raise RunError("逐抽筛选字段无效")
    values = {name: _optional_int(request, name) for name in (
        "trial_from", "trial_to", "source_from", "source_to", "main_from", "main_to")}
    values["source"] = request.GET.get("source")
    values["rarity_id"] = request.GET.get("rarity_id")
    values["character_id"] = request.GET.get("character_id")
    values["event_type"] = request.GET.get("event_type")
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
        return _data_response(safe_json(list_runs_for_actor(
            _actor_or_error(request), *_pagination(request), filters=filters)))
    except ERRORS as error:
        return _error(error)


@csrf_protect
def resource(request, run_id):
    try:
        actor = _actor_or_error(request)
        if request.method == "GET":
            raw_result = HistoryRepository.summary(get_run_for_actor(actor, run_id))
            if request.GET.get("download") == "json":
                response = HttpResponse(json.dumps(raw_result, ensure_ascii=False, indent=2) + "\n",
                                        content_type="application/json; charset=utf-8")
                response["Content-Disposition"] = 'attachment; filename="simulation-result.json"'
                response["Cache-Control"] = "no-store"
                return response
            return _data_response(safe_json(raw_result))
        if request.method == "DELETE":
            delete_run_for_actor(actor, run_id)
            return HttpResponse(status=204)
        return HttpResponse(status=405)
    except ERRORS as error:
        return _error(error)


@require_GET
def trace(request, run_id):
    try:
        actor = _actor_or_error(request)
        page, page_size = _pagination(request)
        if page_size not in {50, 100, 200}:
            raise RunError("逐抽分页大小必须是50、100或200")
        reader = get_trace_reader_for_actor(actor, run_id)
        filters = _trace_filter(request)
        return _data_response({"items": safe_json(reader.query_events(filters, limit=page_size,
                offset=(page - 1) * page_size)), "total": str(reader.count_events(filters)),
                "page": page, "page_size": page_size})
    except ERRORS as error:
        return _error(error)


def _position_chart(request, reader, payload):
    allowed = {"kind", "source", "mode", "rarity_id", "trial_from", "trial_to", "source_from", "source_to"}
    if request.GET.keys() - allowed:
        raise RunError("位置图表筛选字段无效")
    source, mode = request.GET.get("source", "main"), request.GET.get("mode", "count")
    if source not in {"main", "bonus"} or mode not in {"count", "rate"}:
        raise RunError("图表来源或统计口径无效")
    selected = request.GET.getlist("rarity_id") if "rarity_id" in request.GET else None
    parameters = payload["parameters"]
    source_from = _optional_int(request, "source_from", 1)
    maximum = (int(parameters["draws"]) if source == "main" else
               int(payload["rule_snapshot"]["bonus"]["draws"])
               if payload["rule_snapshot"]["bonus"]["enabled"] else 0)
    if maximum == 0 or source_from > maximum:
        rows = []
    else:
        source_to = min(maximum, _optional_int(request, "source_to", min(maximum, source_from + 999)), source_from + 999)
        rows = [] if source_to < source_from else reader.position_counts(source=source,
            trial_from=_optional_int(request, "trial_from", 1),
            trial_to=_optional_int(request, "trial_to", int(parameters["trials"])),
            source_from=source_from, source_to=source_to)
    rarities = payload["rule_snapshot"]["rarities"]
    all_ids = [item["id"] for item in rarities]
    if selected is not None and (set(selected) - set(all_ids) or len(selected) != len(set(selected))):
        raise RunError("稀有度ID筛选无效")
    rarity_ids = all_ids if selected is None else selected
    fields = {rarity_id: f"r{index}" for index, rarity_id in enumerate(all_ids)}
    source_labels = payload["pool_snapshot"].get("rarity_labels", {})
    labels = {item["id"]: source_labels.get(item["id"], item["name"]) for item in rarities}
    table_rows, approximate = [], False
    for index, row in enumerate(rows):
        item = {"position": str(row["source_index"]), "window_position": index,
                "observations": str(row["observations"])}
        for rarity in rarity_ids:
            exact = row["rarity_counts"].get(rarity, 0)
            approximate |= exact > 9007199254740991
            item[f"{fields[rarity]}_count"] = str(exact)
            item[f"{fields[rarity]}_rate"] = exact / row["observations"] if row["observations"] else 0
        table_rows.append(item)
    values = [{**row, "rarity": labels[rarity], "value": int(row[f"{fields[rarity]}_count"])
               if mode == "count" else row[f"{fields[rarity]}_rate"]}
              for row in table_rows for rarity in rarity_ids]
    tooltip = [{"field": "position", "type": "nominal", "title": "来源内抽次"},
               {"field": "observations", "type": "nominal", "title": "有效轮数"}]
    for rarity in rarity_ids:
        label = labels[rarity]
        tooltip.extend([
            {"field": f"{fields[rarity]}_count", "type": "nominal", "title": f"{label}次数"},
            {"field": f"{fields[rarity]}_rate", "type": "quantitative", "title": f"{label}比例", "format": ".2%"},
        ])
    tick_positions = sorted({round(i * (len(table_rows) - 1) / (min(6, len(table_rows)) - 1))
                             for i in range(min(6, len(table_rows)))}) if len(table_rows) > 1 else ([0] if table_rows else [])
    label_expr = " : ".join(
        f'datum.value === {index} ? {json.dumps(table_rows[index]["position"], ensure_ascii=False)}'
        for index in tick_positions
    )
    if label_expr:
        label_expr += ' : ""'
    specification = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "width": "container", "height": 420,
        "autosize": {"type": "fit", "contains": "padding"},
        "encoding": {"x": {"field": "window_position", "type": "quantitative",
                            "title": "主池抽次" if source == "main" else "赠送抽次",
                            "scale": {"domain": [0, max(1, len(table_rows) - 1)], "nice": False},
                            "axis": {"values": tick_positions, "labelExpr": label_expr}}},
        "layer": [
            {"data": {"values": values}, "mark": {"type": "line", "strokeWidth": 2,
                                                   "point": len(table_rows) <= 40},
             "encoding": {"y": {"field": "value", "type": "quantitative",
                       "title": "模拟观察比例" if mode == "rate" else "出现轮数",
                       "axis": {"format": ".0%" if mode == "rate" else ",.0f"}},
                 "color": {"field": "rarity", "type": "nominal", "title": "稀有度"}}},
            {"data": {"values": table_rows}, "params": [{"name": "hover_position", "select": {
                 "type": "point", "fields": ["window_position"], "nearest": True,
                 "on": "pointerover", "clear": "pointerout"}}],
             "mark": {"type": "point", "opacity": 0}, "encoding": {"tooltip": tooltip}},
            {"data": {"values": table_rows}, "transform": [{"filter": {"param": "hover_position", "empty": False}}],
             "mark": {"type": "rule", "color": "#77849a", "strokeDash": [4, 4]}, "encoding": {"tooltip": tooltip}},
        ],
    }
    return {"spec": specification, "rows": table_rows, "rarity_labels": labels,
            "chart_approximate": approximate}



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
    if source not in {"main", "bonus", "total", "grants", "acquisitions"}:
        raise RunError("图表来源无效")
    return summary_chart_data(payload, source)
