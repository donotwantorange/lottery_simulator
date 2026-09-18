"""Pure helpers for rendering nested Trace records."""

from collections.abc import Sequence


def trace_rows(records: list[dict], reward_names: Sequence[str]) -> list[dict]:
    """Flatten nested JSON records into stable Chinese display rows.

    The input records are read only.  Probability values intentionally remain
    in their JSON scale (0..1); the dashboard applies percentage formatting at
    the table boundary.
    """
    rows = []
    for record in records:
        result = record["draw_result"]
        outcome = result["outcome"]
        probabilities = result["probabilities"]
        source_before = result["state_before"]
        source_after = result["state_after"]
        main_before = record["main_state_before"]
        main_after = record["main_state_after"]
        row = {
            "总体抽取序号": record["draw_index"],
            "来源": "主池" if record["source"] == "main" else "赠送",
            "来源内序号": record["source_index"],
            "主池累计抽数": record["main_draws_completed"],
            "星级": outcome["rarity"],
            "角色": outcome["character_name"] or "未配置角色名单",
            "是否UP": outcome["is_up"],
            "是否限定": outcome["is_limited"],
            "四星概率": probabilities["four_star"],
            "五星概率": probabilities["five_star"],
            "六星概率": probabilities["six_star"],
            "来源池抽前未出六星": source_before["misses_since_six_star"],
            "来源池抽前未出五星及以上": source_before["misses_since_five_or_higher"],
            "来源池抽后未出六星": source_after["misses_since_six_star"],
            "来源池抽后未出五星及以上": source_after["misses_since_five_or_higher"],
            "主池抽前未出六星": main_before["misses_since_six_star"],
            "主池抽前未出五星及以上": main_before["misses_since_five_or_higher"],
            "主池抽后未出六星": main_after["misses_since_six_star"],
            "主池抽后未出五星及以上": main_after["misses_since_five_or_higher"],
            "五星保底触发": outcome["five_star_pity_triggered"],
            "六星硬保底触发": outcome["six_star_hard_pity_triggered"],
            "赠送事件": record["bonus_event"],
        }
        rewards = outcome["rewards"]
        for name in reward_names:
            row[f"奖励：{name}"] = rewards.get(name, 0.0)
        rows.append(row)
    return rows
