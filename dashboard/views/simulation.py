"""Presentation of a completed simulation result."""

import json

from dashboard.views.trace_details import result_owner


def _summary_payload(payload):
    """Return the downloadable summary without ever materializing Trace records."""
    return {key: value for key, value in payload.items() if key != "records"}


def _render_overview(st, payload):
    """Summary-only rendering; this function intentionally has no reader access."""
    metrics = (
        ("每轮主池抽数", payload.get("draws", 0)),
        ("每轮赠送抽数", payload.get("bonus_draws", 0)),
        ("每轮总抽数", payload.get("total_draws", 0)),
        ("实验总主池抽数", payload.get("draws", 0) * payload.get("trials", 1)),
        ("实验总赠送抽数", payload.get("bonus_draws", 0) * payload.get("trials", 1)),
        ("实验总抽数", payload.get("total_draws", 0) * payload.get("trials", 1)),
        ("模拟六星均值", payload.get("mean_six_stars", 0)),
        ("理论六星期望", payload.get("theoretical_expected_count", 0)),
        ("相对误差", "不可用" if payload.get("mean_count_relative_error") is None
         else f'{abs(payload["mean_count_relative_error"]):.4%}'),
    )
    for start in range(0, len(metrics), 3):
        for column, (label, value) in zip(st.columns(3), metrics[start : start + 3]):
            column.metric(label, value)
    trials = int(payload.get("trials", 1))
    per_trial = [
        {"范围": f"第{trial}轮", "主池抽数": payload.get("draws", 0),
         "赠送抽数": payload.get("bonus_draws", 0), "总抽数": payload.get("total_draws", 0)}
        for trial in range(1, trials + 1)
    ]
    per_trial.append({
        "范围": "全实验", "主池抽数": payload.get("draws", 0) * trials,
        "赠送抽数": payload.get("bonus_draws", 0) * trials,
        "总抽数": payload.get("total_draws", 0) * trials,
    })
    st.dataframe(per_trial, hide_index=True, width="stretch")
    st.write({
        "规则": payload.get("rule_name"), "规则版本": payload.get("rule_version"),
        "实验轮数": payload.get("trials"), "种子": payload.get("seed"),
        "运行耗时（秒）": payload.get("duration_seconds"),
    })


def _render_category(st, payload):
    source_label = st.radio(
        "数据来源", ("主池", "赠送", "总计"), index=2,
        horizontal=True, key=f'result-source-{result_owner(st, payload)}',
    )
    source = {"主池": "main", "赠送": "bonus", "总计": "total"}[source_label]
    category = st.selectbox(
        "分类统计", ("星级", "六星构成", "六星具体角色", "奖励", "保底"),
        key=f'result-category-{result_owner(st, payload)}',
    )
    from dashboard.charts import (
        character_rows, pity_rows, rarity_comparison_rows,
        reward_rows, six_star_category_rows,
    )
    if category == "星级":
        data = rarity_comparison_rows(payload, source)
        x, y = "星级", ("模拟均值", "理论期望")
    elif category == "六星构成":
        data = six_star_category_rows(payload, source)
        x, y = "类型", ("模拟均值", "理论期望")
    elif category == "六星具体角色":
        data = character_rows(payload, source)
        x, y = "角色", ("模拟均值", "理论期望")
    elif category == "奖励":
        data = reward_rows(payload, source)
        x, y = "奖励", ("模拟均值", "理论期望")
    else:
        data = pity_rows(payload, source)
        x, y = "保底类型", ("模拟均值", "理论期望")
    if data:
        st.bar_chart(data, x=x, y=y, width="stretch")
    st.dataframe(data, hide_index=True, width="stretch")


def render_result(st, payload: dict, trace_reader=None, *, saved_snapshot=False) -> None:
    """Render exactly one result view using a summary payload and optional reader."""
    view = st.selectbox(
        "结果视图", ("实验概览", "分类统计", "按抽次分析", "逐抽明细"),
        key=f'result-view-{result_owner(st, payload)}',
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

    download_key = (
        f'history-download-{payload.get("id", "current")}' if saved_snapshot else None
    )
    st.download_button(
        "下载汇总 JSON",
        data=json.dumps(_summary_payload(payload), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        file_name="simulation-result.json",
        mime="application/json",
        key=download_key,
    )
