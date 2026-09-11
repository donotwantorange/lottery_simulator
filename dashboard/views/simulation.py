"""Presentation of a completed simulation result."""

import json

from dashboard.charts import (
    count_distribution_rows,
    probability_rows,
    source_comparison_rows,
)
from lottery_simulator.cli import RULES


def render_result(st, payload: dict, trace_enabled: bool) -> None:
    relative_error = payload["mean_count_relative_error"]
    metrics = (
        ("主池抽数", payload["main_draws"]),
        ("赠送抽数", payload["bonus_draws"]),
        ("总抽数", payload["total_draws"]),
        ("主池模拟六星均值", f'{payload["mean_main_six_stars"]:.6f}'),
        ("赠送模拟六星均值", f'{payload["mean_bonus_six_stars"]:.6f}'),
        ("总模拟六星均值", f'{payload["mean_six_stars"]:.6f}'),
        ("主池理论期望", f'{payload["theoretical_expected_main_count"]:.6f}'),
        ("赠送理论期望", f'{payload["theoretical_expected_bonus_count"]:.6f}'),
        ("总理论期望", f'{payload["theoretical_expected_count"]:.6f}'),
        ("绝对误差", f'{abs(payload["mean_count_error"]):.6f}'),
        ("相对误差", "不可用" if relative_error is None else f"{abs(relative_error):.4%}"),
        ("初始主池累计抽数", payload["initial_main_draws"]),
        ("结束主池累计抽数", payload["final_main_draws"]),
        ("随机种子", payload["seed"]),
        ("运行耗时（秒）", f'{payload["duration_seconds"]:.3f}'),
    )
    for start in range(0, len(metrics), 3):
        for column, (label, value) in zip(st.columns(3), metrics[start : start + 3]):
            column.metric(label, value)

    rule = RULES[payload["rule_name"]]()
    probability_data = probability_rows(rule)
    count_data = count_distribution_rows(payload)
    source_data = source_comparison_rows(payload)

    st.subheader("主池六星概率")
    st.line_chart(
        probability_data,
        x="抽次",
        y=("条件六星概率", "首次六星累计概率"),
        width="stretch",
    )
    with st.expander("查看主池六星概率数值"):
        st.dataframe(probability_data, hide_index=True, width="stretch")

    st.subheader("六星数量分布")
    st.bar_chart(count_data, x="六星数量", y="实验次数", width="stretch")
    with st.expander("查看六星数量分布数值"):
        st.dataframe(count_data, hide_index=True, width="stretch")

    st.subheader("模拟值与理论期望")
    st.bar_chart(
        source_data,
        x="来源",
        y=("模拟均值", "理论期望"),
        width="stretch",
    )
    with st.expander("查看来源对比数值"):
        st.dataframe(source_data, hide_index=True, width="stretch")

    summary_tab, source_tab = st.tabs(("汇总", "主池与赠送拆分"))
    with summary_tab:
        st.write(
            {
                "规则": payload["rule_name"],
                "规则版本": payload["rule_version"],
                "实验轮数": payload["trials"],
                "至少一个六星概率": payload["at_least_one_rate"],
                "已完成周期平均间隔": payload["observed_mean_interval"],
                "完整周期理论平均间隔": payload["theoretical_mean_interval"],
            }
        )
    with source_tab:
        st.write(source_data)

    st.subheader("逐抽记录")
    records = payload.get("records")
    if trace_enabled and records:
        st.dataframe(records, hide_index=True, width="stretch")
    else:
        st.info("本次运行未保存逐抽记录")

    st.download_button(
        "下载结果 JSON",
        data=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        file_name="simulation-result.json",
        mime="application/json",
    )
