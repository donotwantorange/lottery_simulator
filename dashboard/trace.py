"""Small projection helpers for process-event traces."""


def trace_rows(events):
    rows = []
    for event in events:
        row = {"轮次": event["trial_index"], "事件序号": event["event_index"],
               "主池累计抽数": event["main_draws_completed"],
               "事件类型": "抽取" if event["event_type"] == "draw" else "角色赠送",
               "机制": event["mechanism_id"]}
        if event["event_type"] == "draw":
            draw = event["draw_result"]
            outcome = draw["outcome"]
            row.update({"抽取序号": event["draw_index"], "来源": event["source"],
                        "来源序号": event["source_index"], "稀有度ID": outcome["rarity_id"],
                        "角色ID": outcome["character_id"], "角色": outcome["character_name"],
                        "概率": draw["probabilities"], "角色概率": draw["character_probability"]})
        else:
            row["赠送"] = event["grant"]
        rows.append(row)
    return rows
