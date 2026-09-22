"""History browsing and comparison of immutable saved snapshots."""

from datetime import datetime, time, timezone
from io import StringIO
import json

from streamlit.errors import StreamlitAPIException

from dashboard.views.configuration import set_pool_config_editor_state
from dashboard.views.new_experiment import update_draft_from_history
from dashboard.views.simulation import _render_category, _render_overview, render_result
from lottery_simulator.cli import RULES, _write_config_summary
from lottery_simulator.rules.pool_config import PoolConfig


def _clear_deleted_run_state(st, run_id):
    """Drop UI references and bounded caches that belong to one history run."""
    state = st.session_state
    filtered_ids = [
        value for value in state.get("selected_history_ids", []) if value != run_id
    ]
    try:
        state["selected_history_ids"] = filtered_ids
    except StreamlitAPIException:
        # A confirmation button is rendered after the multiselect.  Streamlit
        # forbids mutating that widget's key in the same run; apply it before
        # recreating the widget on the rerun instead.
        state["_pending_history_selection_clear"] = run_id
    selected = state.get("selected_result")
    if isinstance(selected, (tuple, list)) and tuple(selected) == ("history", run_id):
        state.pop("selected_result", None)

    # These keys are shared by the currently displayed trace result.  Clear
    # them only when their owner is the deleted run; another history result may
    # still be open while the list is being managed.
    signature = state.get("trace-filter-signature")
    selected_owner = selected[1] if isinstance(selected, (tuple, list)) and len(selected) == 2 else None
    signature_owner = signature[0] if isinstance(signature, (tuple, list)) and signature else None
    if isinstance(signature_owner, (tuple, list)) and len(signature_owner) == 2:
        signature_owner = signature_owner[1]
    if run_id in (selected_owner, signature_owner):
        for key in ("trace-page", "trace-download", "trace-filter-signature"):
            state.pop(key, None)
    for key in tuple(state):
        suffixes = (f"-{run_id}", f"-{('job', run_id)}", f"-{('history', run_id)}")
        if isinstance(key, str) and key.endswith(suffixes) and key.startswith(
            ("trace-", "result-", "history-download-")
        ):
            state.pop(key, None)


def _history_count(repository, filters):
    counter = getattr(repository, "count_runs", None)
    if counter is not None:
        return int(counter(filters))
    # Compatibility for small test repositories from before count_runs existed.
    total = 0
    offset = 0
    while True:
        batch = repository.list_runs(filters, limit=100, offset=offset)
        total += len(batch)
        if len(batch) < 100:
            return total
        offset += len(batch)


def _render_config_summary(st, run):
    with st.expander("配置摘要"):
        summary = StringIO()
        _write_config_summary(run["pool_config"], summary)
        print(f'初始五星进度：{run["initial_five_star_pity"]}', file=summary)
        st.text(summary.getvalue())


def _render_saved_summary_download(st, run):
    st.download_button(
        "下载汇总 JSON",
        data=json.dumps(
            {key: value for key, value in run.items() if key != "records"},
            ensure_ascii=False, indent=2, sort_keys=True,
        ).encode("utf-8"),
        file_name="simulation-result.json", mime="application/json",
        key=f"history-download-{run['id']}",
    )


def _render_comparison(st, run):
    """Render only immutable summary/config/category data for history comparison."""
    with st.expander("汇总"):
        _render_overview(st, run)
    _render_config_summary(st, run)
    with st.expander("分类统计"):
        _render_category(st, run)
    _render_saved_summary_download(st, run)


def apply_pending_reuse(st, repository):
    run_id = st.session_state.pop("pending_reuse_id", None)
    if run_id is None:
        return
    run = repository.get_run(run_id)
    if run is None:
        st.warning("历史记录已不存在")
        return
    reuse_parameters(st, run)


def reuse_parameters(st, run):
    """Reuse a completed job or saved snapshot through the same validation path."""
    if run["rule_name"] not in RULES:
        st.warning("当前程序不支持此历史规则，无法复用参数")
        return False
    if run["rule_version"] != RULES[run["rule_name"]]().version:
        st.warning("规则版本不同；下次模拟将使用当前规则版本")
    try:
        pool_config = PoolConfig.from_dict(run["pool_config"])
    except (KeyError, TypeError, ValueError):
        st.warning("历史配置无效，无法复用参数")
        return False
    update_draft_from_history(st, run)
    # Keep the old keys for callers that still render the legacy editor.
    st.session_state.update(
        rule_name=run["rule_name"], draws=run["main_draws"], trials=run["trials"],
        initial_pity=run["initial_pity"], seed_text=str(run["seed"]),
        trace=run["trace_enabled"],
        initial_five_star_pity=run["initial_five_star_pity"],
    )
    set_pool_config_editor_state(st, pool_config)
    st.session_state["_pending_page"] = "新建实验"
    return True


def render_history(st, repository):
    st.header("历史记录")
    recent_rules = {row["rule_name"] for row in repository.list_runs({}, limit=20, offset=0)}
    rule_name = st.selectbox("历史规则", ("全部", *sorted(set(RULES) | recent_rules)), accept_new_options=True,
                             help="可输入已停用的历史规则名称")
    trace = st.selectbox("历史 Trace", ("全部", "含 Trace", "不含 Trace"))
    start = st.date_input("历史开始日期（UTC）", value=None)
    end = st.date_input("历史结束日期（UTC）", value=None)
    filters = {}
    if rule_name != "全部":
        filters["rule_name"] = rule_name
    if trace != "全部":
        filters["trace_enabled"] = trace == "含 Trace"
    if start:
        filters["created_from"] = datetime.combine(start, time.min, timezone.utc).isoformat()
    if end:
        filters["created_to"] = datetime.combine(end, time.max, timezone.utc).isoformat()
    if start and end and start > end:
        st.error("开始日期不能晚于结束日期")
        return
    total = _history_count(repository, filters)
    page_count = max(1, (total + 19) // 20)
    requested_page = int(st.session_state.get("history-page", 1))
    if requested_page > page_count:
        requested_page = page_count
        # Remove the stale widget value before recreating it with the legal page.
        st.session_state.pop("history-page", None)
    page = st.number_input("历史页码", min_value=1, value=requested_page, step=1,
                           key="history-page")
    page = min(int(page), page_count)
    rows = repository.list_runs(filters, limit=20, offset=(page - 1) * 20)
    st.caption(f"共 {total:,} 条记录 · 第 {page}/{page_count} 页 · 每页最多 20 条，按创建时间倒序")
    if rows:
        st.dataframe([{
            "运行 ID": row["id"], "时间": row["created_at"], "规则": row["rule_name"],
            "种子": str(row["seed"]), "主池抽数": row["main_draws"],
            "实验轮数": row["trials"], "总六星均值": row["mean_six_stars"],
            "Trace记录数": row["record_count"],
            "误差": row["mean_count_error"],
        } for row in rows], hide_index=True, width="stretch")
    else:
        st.info("此页没有历史记录")
    for row in rows:
        if st.button("查看结果 " + row["id"], key=f"history-view-{row['id']}"):
            st.session_state["selected_result"] = ("history", row["id"])
            st.session_state["_pending_page"] = "实验结果"
            st.rerun()
    ids = [row["id"] for row in rows]
    pending_selection_clear = st.session_state.pop(
        "_pending_history_selection_clear", None
    )
    if pending_selection_clear is not None:
        st.session_state["selected_history_ids"] = [
            value for value in st.session_state.get("selected_history_ids", [])
            if value != pending_selection_clear
        ]
    st.session_state["selected_history_ids"] = [
        run_id for run_id in st.session_state.get("selected_history_ids", []) if run_id in ids
    ]

    def limit_selection():
        if len(st.session_state["selected_history_ids"]) > 2:
            st.error("最多选择两次运行")
            st.session_state["selected_history_ids"] = st.session_state["selected_history_ids"][:2]

    selected = st.multiselect("选择历史运行", ids, key="selected_history_ids",
                              on_change=limit_selection)
    pending_delete = st.session_state.get("pending_delete_id")
    if pending_delete and repository.get_run(pending_delete) is None:
        st.session_state.pop("pending_delete_id", None)
        st.warning("待删除的历史记录已不存在")
        pending_delete = None
    if pending_delete:
        st.warning(f"确认删除历史 {pending_delete}？逐抽记录也会删除，无法撤销。")
        if st.button("确认删除"):
            repository.delete_run(pending_delete)
            _clear_deleted_run_state(st, pending_delete)
            del st.session_state["pending_delete_id"]
            st.rerun()
        if st.button("取消删除"):
            del st.session_state["pending_delete_id"]
            st.rerun()
    summaries = {row["id"]: row for row in rows}
    runs = [repository.get_run(run_id) for run_id in selected if run_id in summaries]
    runs = [run for run in runs if run is not None]
    if len(runs) == 2 and any(runs[0].get(field) != runs[1].get(field)
                              for field in ("rule_name", "rule_version", "schema_version")):
        st.warning("统计口径不同：规则、版本或快照结构不同，仅并排展示，不叠加曲线")
    if not runs:
        return
    for column, run in zip(st.columns(len(runs)), runs):
        with column:
            st.subheader("历史运行 " + run["id"])
            st.caption(f'{run["created_at"]} · {run["rule_name"]} · {run["rule_version"]}')
            _render_comparison(st, run)
            if st.button("复用参数 " + run["id"]):
                st.session_state["pending_reuse_id"] = run["id"]
                st.rerun()
            if st.button("删除历史 " + run["id"]):
                st.session_state["pending_delete_id"] = run["id"]
                st.rerun()
