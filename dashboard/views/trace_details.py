"""The result-page Trace views.

The view deliberately receives a reader instead of a record collection.  This
keeps the summary payload small and makes it possible to put a hard boundary
around every SQL operation made by the selected result view.
"""

from dataclasses import asdict

from dashboard.limits import TraceLimits
from dashboard.charts import position_rows
from dashboard.trace import trace_rows
from dashboard.trace_export import iter_jsonl
from dashboard.trace_store import TraceFilter


_SOURCE_LABELS = {"全部": None, "主池": "main", "赠送": "bonus"}
_BASE_COLUMNS = (
    "轮次", "轮内总抽次", "来源", "来源内序号", "星级", "角色",
    "主池累计抽数", "是否UP", "是否限定",
)


def _session(st):
    value = getattr(st, "session_state", None)
    return value if value is not None else {}


def result_owner(st, payload):
    selected = _session(st).get("selected_result")
    if isinstance(selected, (tuple, list)) and len(selected) == 2:
        return tuple(selected)
    return ("history", payload.get("id") or payload.get("run_id"))


def _reward_names(payload):
    rewards = payload.get("pool_config", {}).get("rewards", ())
    return tuple(item.get("name", "") if isinstance(item, dict) else item for item in rewards)


def _filter_controls(st, payload):
    trials = max(1, int(payload.get("trials", 1)))
    trial_options = ("第1轮", "指定轮次", "轮次范围", "全部轮次") if trials > 1 else ("第1轮",)
    trial_label = st.selectbox("轮次", trial_options, key=f"trace-trial-{result_owner(st, payload)}")
    trial_from = None if trial_label == "全部轮次" else 1
    trial_to = None if trial_label == "全部轮次" else 1
    if trial_label == "指定轮次":
        trial_from = trial_to = st.number_input(
            "指定轮次", min_value=1, max_value=trials, value=1, step=1,
            key=f"trace-single-trial-{result_owner(st, payload)}",
        )
    elif trial_label == "轮次范围":
        trial_from = st.number_input(
            "轮次起", min_value=1, max_value=trials, value=1, step=1,
            key=f"trace-trial-from-{result_owner(st, payload)}",
        )
        trial_to = st.number_input(
            "轮次止", min_value=trial_from, max_value=trials, value=trials, step=1,
            key=f"trace-trial-to-{result_owner(st, payload)}",
        )

    source_label = st.selectbox(
        "来源", tuple(_SOURCE_LABELS), key=f"trace-source-{result_owner(st, payload)}"
    )
    rarity = st.selectbox(
        "星级", ("全部", 4, 5, 6), key=f"trace-rarity-{result_owner(st, payload)}"
    )
    rarity_value = None if rarity == "全部" else rarity
    catalog = _character_catalog(payload)
    if rarity_value is None:
        character_options = ("全部", *(
            f"{item_rarity}星：{name}" for item_rarity, name in catalog
        ))
    else:
        character_options = (
            "全部", "未配置角色名单",
            *(name for item_rarity, name in catalog if item_rarity == rarity_value),
        )
    character_label = st.selectbox(
        "角色", character_options, key=f"trace-character-{result_owner(st, payload)}"
    )
    restrict_range = st.checkbox(
        "限制来源抽次区间", value=False, key=f"trace-range-{result_owner(st, payload)}"
    )
    source_from = source_to = None
    if restrict_range:
        source_from = st.number_input("来源抽次起", min_value=1, value=1, step=1)
        source_to = st.number_input("来源抽次止", min_value=source_from, value=source_from, step=1)

    if character_label == "未配置角色名单":
        character_name = None
        unnamed = True
    elif character_label == "全部":
        character_name = None
        unnamed = False
    elif rarity_value is None and "：" in character_label:
        rarity_text, character_name = character_label.split("：", 1)
        rarity_value = int(rarity_text.removesuffix("星"))
        unnamed = False
    else:
        character_name = character_label
        unnamed = False
    filters = TraceFilter(
        trial_from=trial_from, trial_to=trial_to,
        source=_SOURCE_LABELS[source_label], rarity=rarity_value,
        character_name=character_name, unnamed_character=unnamed,
        source_from=source_from, source_to=source_to,
    )
    return filters


def _character_catalog(payload):
    """Return configured Trace character identities as (rarity, name) pairs."""
    config = payload.get("pool_config", {})
    catalog = []
    for rarity, key in (
        (4, "four_star_characters"),
        (5, "five_star_characters"),
        (6, "six_star_characters"),
    ):
        for item in config.get(key, ()):
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name:
                catalog.append((rarity, name))
    return tuple(catalog)


def _display_rows(rows, reward_names, full):
    try:
        flattened = trace_rows(rows, reward_names)
    except KeyError:
        # A reader contract normally returns validated nested records.  Keeping
        # a raw fallback makes the presentation boundary diagnosable for a
        # corrupt/third-party reader without issuing another query.
        return rows
    if full:
        return flattened
    return [{name: row[name] for name in _BASE_COLUMNS if name in row} for row in flattened]


def render_trace_details(st, payload, reader):
    """Render one paginated detail page and an optional bounded JSONL download."""
    if reader is None:
        st.info("本次运行未保存逐抽结果")
        return
    filters = _filter_controls(st, payload)
    state = _session(st)
    run_key = result_owner(st, payload)
    signature = (run_key, tuple(asdict(filters).items()))
    signature_key = "trace-filter-signature"
    if state.get(signature_key) != signature:
        state[signature_key] = signature
        state["trace-page"] = 1
        state.pop("trace-download", None)

    page_size = st.selectbox("每页条数", (50, 100, 200), index=1,
                             key=f"trace-page-size-{run_key}")
    page = int(state.get("trace-page", 1))
    rows, total = reader.query_records(filters, limit=page_size, offset=(page - 1) * page_size)
    page_count = max(1, (total + page_size - 1) // page_size)
    if page > page_count:
        page = page_count
        state["trace-page"] = page
        rows, total = reader.query_records(filters, limit=page_size, offset=(page - 1) * page_size)
    st.caption(f"匹配 {total:,} 条 · 第 {page}/{page_count} 页")
    full = st.radio("明细列", ("基础列", "完整列"), horizontal=True,
                    key=f"trace-columns-{run_key}") == "完整列"
    st.dataframe(_display_rows(rows, _reward_names(payload), full), hide_index=True, width="stretch")

    if page > 1 and st.button("上一页", key=f"trace-prev-{run_key}"):
        state["trace-page"] = page - 1
        st.rerun()
    if page < page_count and st.button("下一页", key=f"trace-next-{run_key}"):
        state["trace-page"] = page + 1
        st.rerun()

    if st.button("准备下载", key=f"trace-prepare-download-{run_key}"):
        _, matched = reader.query_records(filters, limit=50, offset=0)
        if matched > TraceLimits.from_env().max_download_records:
            state.pop("trace-download", None)
            st.warning("匹配记录超过单次下载上限，请缩小筛选范围")
        else:
            state["trace-download"] = b"".join(
                line.encode("utf-8") if isinstance(line, str) else line
                for line in iter_jsonl(payload, reader, filters)
            )
    download = state.get("trace-download")
    if download is not None:
        st.download_button(
            "下载明细 JSONL", data=download,
            file_name="trace.jsonl", mime="application/x-ndjson",
            key=f"trace-download-{run_key}",
        )


def render_position_analysis(st, payload, reader):
    """Render SQL-backed position frequencies using one aggregate result."""
    if reader is None:
        st.info("本次运行未保存逐抽结果，无法进行按抽次分析")
        return
    trials = max(1, int(payload.get("trials", 1)))
    source_label = st.selectbox("位置来源", ("主池", "赠送"), key="position-source")
    source = "main" if source_label == "主池" else "bonus"
    trial_from = st.number_input("位置轮次起", min_value=1, max_value=trials, value=1, step=1)
    trial_to = st.number_input("位置轮次止", min_value=trial_from, max_value=trials,
                               value=trials, step=1)
    available = payload.get("draws", 200) if source == "main" else payload.get("bonus_draws", 200)
    available = max(1, int(available or 1))
    source_from = st.number_input("位置起", min_value=1, max_value=available, value=1, step=1)
    source_to = st.number_input("位置止", min_value=source_from,
                                max_value=min(source_from + 999, available),
                                value=min(source_from + 199, available), step=1)
    mode = st.radio("统计口径", ("计数", "比例"), horizontal=True, key="position-mode")
    rows = reader.position_counts(
        source=source, trial_from=trial_from, trial_to=trial_to,
        source_from=source_from, source_to=source_to,
    )
    if not rows:
        st.info("当前来源和位置范围无数据")
        return
    suffix = "轮数" if mode == "计数" else "模拟频率"
    chart_rows = position_rows(rows, mode)
    st.dataframe(chart_rows, hide_index=True, width="stretch")
    st.line_chart(chart_rows, x="抽次", y=("四星", "五星", "六星"), width="stretch")
    st.caption(f"纵轴：{suffix}；主池与赠送来源分别统计")
