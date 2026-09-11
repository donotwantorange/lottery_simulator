"""Convert simulator and analyzer results into chart-ready numeric rows."""

from lottery_simulator.analysis import distribution_stats, waiting_time_distribution
from lottery_simulator.rules.base import DrawState


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
