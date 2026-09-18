"""Presentation of a completed simulation result."""

import json

from dashboard.charts import (
    character_rows,
    pity_rows,
    probability_rows,
    rarity_comparison_rows,
    reward_distribution_rows,
    reward_rows,
    six_star_category_rows,
)
from dashboard.trace import trace_rows
from lottery_simulator.cli import RULES


def _trace_column_config(st):
    number_column = getattr(getattr(st, "column_config", None), "NumberColumn", None)
    if number_column is None:
        return {}
    return {
        name: number_column(format="percent")
        for name in ("四星概率", "五星概率", "六星概率")
    }


def render_result(st, payload: dict, trace_enabled: bool, *, saved_snapshot=False) -> None:
    source_options = ("主池", "赠送", "总计")
    source_kwargs = {"key": f'result-source-{payload["id"]}'} if saved_snapshot else {}
    source_label = st.radio(
        "数据来源", source_options, index=2, horizontal=True, **source_kwargs
    )
    source = {"主池": "main", "赠送": "bonus", "总计": "total"}[source_label]
    (
        overview_tab,
        category_tab,
        character_tab,
        reward_tab,
        pity_tab,
        trace_tab,
    ) = st.tabs(("总览", "六星构成", "具体角色", "附赠奖励", "保底统计", "Trace"))

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

    with overview_tab:
        for start in range(0, len(metrics), 3):
            for column, (label, value) in zip(
                st.columns(3), metrics[start : start + 3]
            ):
                column.metric(label, value)

        if saved_snapshot:
            st.info("历史快照未保存概率曲线；仅展示保存时的指标与分布")
        else:
            rule = RULES[payload["rule_name"]]()
            probability_data = probability_rows(rule)
            st.line_chart(
                probability_data,
                x="抽次",
                y=("条件六星概率", "首次六星累计概率"),
                width="stretch",
            )
            with st.expander("查看主池六星概率数值"):
                st.dataframe(probability_data, hide_index=True, width="stretch")

        rarity_data = rarity_comparison_rows(payload, source)
        st.bar_chart(
            rarity_data,
            x="星级",
            y=("模拟均值", "理论期望"),
            width="stretch",
        )
        with st.expander("查看星级对比数值"):
            st.dataframe(rarity_data, hide_index=True, width="stretch")

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
        with st.expander("运行信息"):
            st.write({
                "sampling_version": payload.get("sampling_version"),
                "rng_algorithm": payload.get("rng_algorithm"),
                "python_implementation": payload.get("python_implementation"),
                "python_version": payload.get("python_version"),
            })

    with category_tab:
        category_data = six_star_category_rows(payload, source)
        st.bar_chart(
            category_data,
            x="类型",
            y=("模拟均值", "理论期望"),
            width="stretch",
        )
        with st.expander("查看六星构成数值"):
            st.dataframe(category_data, hide_index=True, width="stretch")

    with character_tab:
        character_data = character_rows(payload, source)
        st.bar_chart(
            character_data,
            x="角色",
            y=("模拟均值", "理论期望"),
            width="stretch",
        )
        with st.expander("查看具体角色数值"):
            st.dataframe(character_data, hide_index=True, width="stretch")

    with reward_tab:
        rewards = reward_rows(payload, source)
        if rewards:
            st.bar_chart(
                rewards,
                x="奖励",
                y=("模拟均值", "理论期望"),
                width="stretch",
            )
            with st.expander("查看附赠奖励数值"):
                st.dataframe(rewards, hide_index=True, width="stretch")
            reward_kwargs = (
                {"key": f'result-reward-{payload["id"]}'} if saved_snapshot else {}
            )
            reward_name = st.selectbox(
                "奖励分布",
                tuple(row["奖励"] for row in rewards),
                **reward_kwargs,
            )
            reward_distribution = reward_distribution_rows(
                payload, source, reward_name
            )
            st.bar_chart(
                reward_distribution,
                x="奖励总量",
                y="实验次数",
                width="stretch",
            )
            with st.expander("查看奖励分布数值"):
                st.dataframe(
                    reward_distribution, hide_index=True, width="stretch"
                )
        else:
            st.info("当前配置没有附赠奖励")

    with pity_tab:
        pity_data = pity_rows(payload, source)
        st.bar_chart(
            pity_data,
            x="保底类型",
            y=("模拟均值", "理论期望"),
            width="stretch",
        )
        with st.expander("查看保底统计数值"):
            st.dataframe(pity_data, hide_index=True, width="stretch")

    with trace_tab:
        records = payload.get("records")
        if trace_enabled and records:
            reward_names = tuple(
                reward["name"] for reward in payload.get("pool_config", {}).get("rewards", ())
            )
            st.dataframe(
                trace_rows(records, reward_names),
                hide_index=True,
                width="stretch",
                column_config=_trace_column_config(st),
            )
        else:
            st.info("本次运行未保存逐抽记录")

    st.download_button(
        "下载结果 JSON",
        data=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        file_name="simulation-result.json",
        mime="application/json",
        key=f'history-download-{payload["id"]}' if saved_snapshot else None,
    )
