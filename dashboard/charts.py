"""Convert simulator and analyzer results into chart-ready numeric rows."""

import math

import altair as alt

from lottery_simulator.analysis import distribution_stats, waiting_time_distribution
from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.pool_config import PoolConfig


_COMPARISON_SERIES = ("模拟均值", "理论期望")
_COMPARISON_COLORS = ("#4C78A8", "#F58518")


def _comparison_value_domain(values: list[object]) -> list[float]:
    numeric = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            numeric.append(number)
    minimum = min(numeric, default=0.0)
    maximum = max(numeric, default=0.0)
    if minimum >= 0:
        if maximum == 0:
            return [0.0, 1.0]
        upper = maximum * 1.2
        if upper <= maximum:
            upper = math.nextafter(maximum, math.inf)
        return [0.0, upper]
    span = maximum - minimum
    return [minimum - span * 0.05, maximum + span * 0.2]


def format_comparison_value(value: float) -> str:
    """Format a bar label without hiding small non-zero values."""
    numeric = float(value)
    if numeric == 0:
        return "0"
    formatted = f"{numeric:.4f}"
    if float(formatted) == 0:
        return f"{numeric:.4e}"
    return formatted


def comparison_bar_chart(
    rows: list[dict], *, category_field: str, unit: str, horizontal: bool = False
) -> alt.LayerChart:
    """Build the shared grouped simulation/theory chart for a category."""
    categories = [row[category_field] for row in rows]
    long_rows = [
        {
            "类别": row[category_field],
            "系列": series,
            "值": row[series],
            "标签": format_comparison_value(row[series]),
        }
        for row in rows
        for series in _COMPARISON_SERIES
    ]
    data = alt.Data(values=long_rows)
    value_domain = _comparison_value_domain([row["值"] for row in long_rows])
    category = alt.SortArray(categories)
    series_sort = list(_COMPARISON_SERIES)
    color = alt.Color(
        "系列:N",
        scale=alt.Scale(domain=series_sort, range=list(_COMPARISON_COLORS)),
        legend=alt.Legend(
            title=None, orient="top", symbolType="square", values=series_sort,
        ),
    )
    # Offset and legend carry the explicit display order; Vega-Lite's order
    # channel accepts only ascending/descending in Altair 6.
    order = alt.Order("系列:N", sort="ascending")
    tooltip = [
        alt.Tooltip("类别:N", title=category_field),
        alt.Tooltip("系列:N", title="系列"),
        alt.Tooltip("值:Q", title=unit, format=".12~g"),
    ]
    if horizontal:
        value = alt.X(
            "值:Q", title=unit, scale=alt.Scale(domain=value_domain, zero=True), stack=None,
        )
        group = alt.YOffset("系列:N", sort=alt.SortArray(series_sort))
        category_axis = alt.Y(
            "类别:N", sort=category, title=category_field, scale=alt.Scale(padding=0.15),
        )
        text_kwargs = {"dx": 5, "align": "left", "baseline": "middle"}
        height = max(220, len(categories) * 34)
    else:
        category_axis = alt.X(
            "类别:N", sort=category, title=category_field, scale=alt.Scale(padding=0.25),
        )
        group = alt.XOffset("系列:N", sort=alt.SortArray(series_sort))
        value = alt.Y(
            "值:Q", title=unit, scale=alt.Scale(domain=value_domain, zero=True), stack=None,
        )
        text_kwargs = {"dy": -5, "align": "center", "baseline": "bottom"}
        height = 320

    common = alt.Chart(data).encode(
        color=color,
        order=order,
        tooltip=tooltip,
    )
    bars = common.mark_bar().encode(category_axis, group, value)
    labels = common.mark_text(**text_kwargs).encode(category_axis, group, value, text="标签:N")
    return (bars + labels).properties(height=height, width="container")


def _theoretical_values(payload: dict, source: str, field: str) -> dict:
    summary = payload["theoretical_source_summaries"][source]
    if field in summary:
        return summary[field]
    return summary[f"mean_{field}"]


def rarity_comparison_rows(payload: dict, source: str) -> list[dict]:
    simulated = payload["source_summaries"][source]["mean_rarity_counts"]
    theoretical = _theoretical_values(payload, source, "rarity_counts")
    return [
        {"星级": label, "模拟均值": simulated[rarity], "理论期望": theoretical[rarity]}
        for rarity, label in (("4", "四星"), ("5", "五星"), ("6", "六星"))
    ]


def six_star_category_rows(payload: dict, source: str) -> list[dict]:
    simulated = payload["source_summaries"][source]["mean_six_star_categories"]
    theoretical = _theoretical_values(payload, source, "six_star_categories")
    return [
        {"类型": label, "模拟均值": simulated[name], "理论期望": theoretical[name]}
        for name, label in (
            ("up", "UP限定"),
            ("other_limited", "其他限定"),
            ("standard", "常驻"),
        )
    ]


def character_rows(payload: dict, source: str) -> list[dict]:
    config = PoolConfig.from_dict(payload["pool_config"])
    probabilities = config.character_probabilities(6)
    simulated = payload["source_summaries"][source]["mean_character_counts"]
    theoretical = _theoretical_values(payload, source, "character_counts")
    six_mean = payload["source_summaries"][source]["mean_rarity_counts"]["6"]
    return [
        {
            "角色": character.name,
            "类型": (
                "UP限定"
                if character.is_up
                else "其他限定"
                if character.is_limited
                else "常驻"
            ),
            "模拟均值": simulated[character.name],
            "理论期望": theoretical[character.name],
            "六星内实际占比": (
                simulated[character.name] / six_mean if six_mean else None
            ),
            "六星内理论占比": probabilities[character.name],
            "占比误差": (
                simulated[character.name] / six_mean - probabilities[character.name]
                if six_mean
                else None
            ),
        }
        for character in config.six_star_characters
    ]


def reward_rows(payload: dict, source: str) -> list[dict]:
    config = PoolConfig.from_dict(payload["pool_config"])
    simulated = payload["source_summaries"][source]["mean_rewards"]
    theoretical = _theoretical_values(payload, source, "rewards")
    return [
        {
            "奖励": reward.name,
            "模拟均值": simulated[reward.name],
            "理论期望": theoretical[reward.name],
        }
        for reward in config.rewards
    ]


def reward_distribution_rows(
    payload: dict, source: str, reward_name: str
) -> list[dict]:
    distribution = payload["source_distributions"][source]["reward_totals"][reward_name]
    trials = payload["trials"]
    return [
        {"奖励总量": float(total), "实验次数": frequency, "占比": frequency / trials}
        for total, frequency in sorted(
            distribution.items(), key=lambda item: float(item[0])
        )
    ]


def pity_rows(payload: dict, source: str) -> list[dict]:
    simulated = payload["source_summaries"][source]["mean_pity_triggers"]
    theoretical = _theoretical_values(payload, source, "pity_triggers")
    return [
        {"保底类型": label, "模拟均值": simulated[name], "理论期望": theoretical[name]}
        for name, label in (("five_star", "五星保底"), ("six_star_hard", "六星硬保底"))
    ]


def summary_chart_data(payload: dict, source: str) -> dict:
    """Build the five snapshot-based category charts and their table rows."""
    labels = payload["pool_config"].get("rarity_labels", {})
    rarity = rarity_comparison_rows(payload, source)
    for row, key in zip(rarity, ("4", "5", "6")):
        row["星级"] = labels.get(key, row["星级"])
    characters = character_rows(payload, source)
    for row in characters:
        row[f'{labels.get("6", "六星")}内实际占比'] = row.pop("六星内实际占比")
        row[f'{labels.get("6", "六星")}内理论占比'] = row.pop("六星内理论占比")
    pity = pity_rows(payload, source)
    pity[0]["保底类型"] = f'{labels.get("5", "五星")}保底'
    pity[1]["保底类型"] = f'{labels.get("6", "六星")}硬保底'
    categories = {
        "rarity": (rarity, "星级", "每轮平均数量"),
        "six_star_categories": (six_star_category_rows(payload, source), "类型", "每轮平均数量"),
        "characters": (characters, "角色", "每轮平均数量"),
        "rewards": (reward_rows(payload, source), "奖励", "奖励量"),
        "pity": (pity, "保底类型", "触发次数"),
    }
    specs = {}
    for kind, (rows, field, unit) in categories.items():
        if not rows:
            specs[kind] = None
            continue
        horizontal = kind == "characters" and (
            len(rows) > 8 or any(len(str(row[field])) > 8 for row in rows)
        )
        specs[kind] = comparison_bar_chart(
            rows, category_field=field, unit=unit, horizontal=horizontal,
        ).to_dict()
    return {"specs": specs, "rows": {kind: rows for kind, (rows, _, _) in categories.items()},
            "rarity_labels": labels}


def probability_rows(rule) -> list[dict]:
    probabilities = waiting_time_distribution(rule)
    analyzed_probabilities = distribution_stats(rule).probabilities
    cumulative = 0.0
    rows = []
    for pull, (first_probability, analyzed_probability) in enumerate(
        zip(probabilities, analyzed_probabilities, strict=True), start=1
    ):
        cumulative += analyzed_probability
        rows.append(
            {
                "抽次": pull,
                "条件六星概率": rule.probability(DrawState(pull - 1)),
                "首次六星概率": first_probability,
                "首次六星累计概率": cumulative,
            }
        )
    return rows


def count_distribution_rows(payload: dict) -> list[dict]:
    trials = payload["trials"]
    return [
        {"六星数量": int(count), "实验次数": frequency, "占比": frequency / trials}
        for count, frequency in sorted(
            payload["count_distribution"].items(), key=lambda item: int(item[0])
        )
    ]


def source_comparison_rows(payload: dict) -> list[dict]:
    return [
        {
            "来源": source,
            "模拟均值": payload[simulated],
            "理论期望": payload[theoretical],
        }
        for source, simulated, theoretical in (
            (
                "主池",
                "mean_main_six_stars",
                "theoretical_expected_main_count",
            ),
            (
                "赠送",
                "mean_bonus_six_stars",
                "theoretical_expected_bonus_count",
            ),
            ("总计", "mean_six_stars", "theoretical_expected_count"),
        )
    ]


def position_rows(rows: list[dict], mode: str = "count") -> list[dict]:
    """Project one TraceReader position aggregate for table and chart use."""
    if mode in ("比例", "rate"):
        fields = ("four_rate", "five_rate", "six_rate")
    elif mode in ("计数", "count"):
        fields = ("four_count", "five_count", "six_count")
    else:
        raise ValueError("mode must be count or rate")
    return [
        {
            "抽次": row["source_index"],
            "四星": row[fields[0]],
            "五星": row[fields[1]],
            "六星": row[fields[2]],
        }
        for row in rows
    ]


position_chart_rows = position_rows
