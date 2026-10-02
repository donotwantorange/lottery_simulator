"""Convert simulator and analyzer results into chart-ready numeric rows."""

import math

import altair as alt

from lottery_simulator.rules.definitions import PoolDefinition, RuleDefinition


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


def summary_chart_data(payload: dict, source: str) -> dict:
    """Project frozen v6 summaries; UI refinements belong to the result page."""
    rule = RuleDefinition.from_dict(payload["rule_snapshot"])
    pool = PoolDefinition.from_dict(payload["pool_snapshot"])
    if source not in {"main", "bonus", "total", "grants", "acquisitions"}:
        raise ValueError("统计来源无效")
    observed = payload["simulation"]
    expected = payload["theoretical"]
    if source in {"main", "bonus", "total"}:
        observed, expected = observed["draws"][source], expected["draws"][source]
    else:
        observed, expected = observed[source], expected[source]
    labels = {r.id: pool.rarity_labels.get(r.id, r.name) for r in rule.rarities}
    chart_approximate = False
    def row(label, key, simulated, theoretical):
        nonlocal chart_approximate
        chart_approximate |= any(type(value) in (int, float) and abs(value) > 9007199254740991
                                 for value in (simulated, theoretical))
        error = None if theoretical == 0 else (simulated - theoretical) / theoretical
        return {key: label,
                "模拟均值": str(simulated) if type(simulated) is int and abs(simulated) > 9007199254740991 else simulated,
                "理论期望": str(theoretical) if type(theoretical) is int and abs(theoretical) > 9007199254740991 else theoretical,
                "相对误差": error}
    rarity = [row(labels[r.id], "稀有度", observed["rarity_counts"][r.id],
                  expected["rarity_counts"][r.id]) for r in sorted(rule.rarities, key=lambda r:r.rank)]
    characters = [row(f"{c.name}（{labels[c.rarity_id]}）", "角色",
                      observed["character_counts"].get(c.id, 0),
                      expected["character_counts"].get(c.id, 0))
                  for group in pool.rarity_pools for c in group.characters]
    categories = [row(f"{labels[r.id]} · {label}", "类型",
                      observed["category_counts"][r.id][key], expected["category_counts"][r.id][key])
                  for r in rule.rarities for key,label in
                  (("up","UP"),("other_limited","其他限定"),("standard","常驻"),("unnamed","未配置名单"))]
    rewards = [row(reward.name,"奖励",observed["reward_totals"][reward.id],
                   expected["reward_totals"][reward.id]) for reward in pool.rewards] if "reward_totals" in observed else []
    pity = []
    if "pity_triggers" in observed:
        for kind,label in (("soft","软保底"),("hard","硬保底")):
            pity.extend(row(f"{labels[r.id]}{label}","保底类型",
                observed["pity_triggers"][kind].get(r.id,0),
                expected["pity_triggers"][kind].get(r.id,0)) for r in rule.rarities)
        pity.append(row("大保底","保底类型",observed["pity_triggers"]["big"],expected["pity_triggers"]["big"]))
    groups={"rarity":(rarity,"稀有度"),"categories":(categories,"类型"),
            "characters":(characters,"角色"),"rewards":(rewards,"奖励"),"pity":(pity,"保底类型")}
    return {"specs": {name: comparison_bar_chart(rows,category_field=field,
                unit="每轮数量",horizontal=name=="characters").to_dict() if rows else None
                for name,(rows,field) in groups.items()},
            "rows": {name: rows for name,(rows,_) in groups.items()}, "rarity_labels":labels,
            "chart_approximate": chart_approximate}
