"""Convert simulator and analyzer results into chart-ready numeric rows."""

from lottery_simulator.analysis import distribution_stats, waiting_time_distribution
from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.pool_config import PoolConfig


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
