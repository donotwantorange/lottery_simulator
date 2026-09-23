"""Presentation of a completed simulation result."""

import json
from numbers import Real

from dashboard.charts import (
    character_rows,
    format_comparison_value,
    comparison_bar_chart,
    pity_rows,
    rarity_comparison_rows,
    reward_rows,
    six_star_category_rows,
)
from dashboard.views.trace_details import result_owner


def _summary_payload(payload):
    """Return the downloadable summary without ever materializing Trace records."""
    return {key: value for key, value in payload.items() if key != "records"}


def render_summary_download(st, payload: dict, *, key: str) -> None:
    st.download_button(
        "下载汇总 JSON",
        data=json.dumps(_summary_payload(payload), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        file_name="simulation-result.json",
        mime="application/json",
        key=key,
    )


def _render_overview(st, payload):
    """Summary-only rendering; this function intentionally has no reader access."""
    metrics = (
        ("模拟六星均值", format_comparison_value(payload.get("mean_six_stars", 0))),
        ("理论六星期望", format_comparison_value(payload.get("theoretical_expected_count", 0))),
        ("相对误差", "不可用" if payload.get("mean_count_relative_error") is None
         else f'{abs(payload["mean_count_relative_error"]):.4%}'),
        ("每轮主池抽数", payload.get("draws", 0)),
        ("每轮赠送抽数", payload.get("bonus_draws", 0)),
        ("每轮总抽数", payload.get("total_draws", 0)),
        ("实验总主池抽数", payload.get("draws", 0) * payload.get("trials", 1)),
        ("实验总赠送抽数", payload.get("bonus_draws", 0) * payload.get("trials", 1)),
        ("实验总抽数", payload.get("total_draws", 0) * payload.get("trials", 1)),
    )
    for start in range(0, len(metrics), 3):
        for column, (label, value) in zip(st.columns(3), metrics[start : start + 3]):
            column.metric(label, value)
    draws = payload.get("draws", 0)
    bonus = payload.get("bonus_draws", 0)
    trials = int(payload.get("trials", 1))
    rows = [
        {"范围": "每轮", "主池抽数": draws, "赠送抽数": bonus,
         "总抽数": draws + bonus},
        {"范围": f"全实验（{trials:,}轮）", "主池抽数": draws * trials,
         "赠送抽数": bonus * trials, "总抽数": (draws + bonus) * trials},
    ]
    st.dataframe(rows, hide_index=True, width="stretch")
    st.write({
        "规则": payload.get("rule_name"), "规则版本": payload.get("rule_version"),
        "实验轮数": payload.get("trials"), "种子": payload.get("seed"),
        "运行耗时（秒）": payload.get("duration_seconds"),
    })


def _render_category(st, payload, *, owner=None):
    owner = result_owner(st, payload) if owner is None else owner
    source_label = st.radio(
        "数据来源", ("主池", "赠送", "总计"), index=2,
        horizontal=True, key=f'result-source-{owner}',
    )
    source = {"主池": "main", "赠送": "bonus", "总计": "total"}[source_label]
    category = st.selectbox(
        "分类统计", ("星级", "六星构成", "六星具体角色", "奖励", "保底"),
        key=f'result-category-{owner}',
    )
    if category == "星级":
        data = rarity_comparison_rows(payload, source)
        category_field = "星级"
        unit = "每轮平均数量"
    elif category == "六星构成":
        data = six_star_category_rows(payload, source)
        category_field = "类型"
        unit = "每轮平均数量"
    elif category == "六星具体角色":
        data = character_rows(payload, source)
        category_field = "角色"
        unit = "每轮平均数量"
    elif category == "奖励":
        data = reward_rows(payload, source)
        category_field = "奖励"
        unit = "奖励量"
    else:
        data = pity_rows(payload, source)
        category_field = "保底类型"
        unit = "触发次数"
    if data:
        horizontal = category == "六星具体角色" and (
            len(data) > 8
            or any(len(str(row[category_field])) > 8 for row in data)
        )
        chart = comparison_bar_chart(
            data,
            category_field=category_field,
            unit=f"{unit}（{source_label}）",
            horizontal=horizontal,
        )
        st.altair_chart(chart, width="stretch")
    elif category == "奖励":
        st.info("未配置奖励，暂无奖励统计。")
    numeric_columns = {
        field: st.column_config.NumberColumn(format="%.12g")
        for field in (data[0] if data else {})
        if any(
            isinstance(row.get(field), Real) and not isinstance(row.get(field), bool)
            for row in data
        )
    }
    st.dataframe(
        data, hide_index=True, width="stretch", column_config=numeric_columns,
    )


def render_result(st, payload: dict, trace_reader=None, *, saved_snapshot=False) -> None:
    """Render exactly one result view using a summary payload and optional reader."""
    view = st.radio(
        "结果视图", ("实验概览", "分类统计", "按抽次分析", "逐抽明细"),
        horizontal=True, key=f'result-view-{result_owner(st, payload)}',
    )
    if view == "实验概览":
        _render_overview(st, payload)
    elif view == "分类统计":
        _render_category(st, payload)
    elif view == "按抽次分析":
        from dashboard.views.trace_details import render_position_analysis
        render_position_analysis(st, payload, trace_reader)
    else:
        from dashboard.views.trace_details import render_trace_details
        render_trace_details(st, payload, trace_reader)
