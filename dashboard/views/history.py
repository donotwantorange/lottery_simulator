"""History browsing and comparison of immutable saved snapshots."""

from datetime import datetime, time, timezone
from io import StringIO

from dashboard.views.configuration import set_pool_config_editor_state
from dashboard.views.simulation import render_result
from lottery_simulator.cli import RULES, _write_config_summary
from lottery_simulator.rules.pool_config import PoolConfig


def apply_pending_reuse(st, repository):
    run_id = st.session_state.pop("pending_reuse_id", None)
    if run_id is None:
        return
    run = repository.get_run(run_id)
    if run is None:
        st.warning("历史记录已不存在")
        return
    if run["rule_name"] not in RULES:
        st.warning("当前程序不支持此历史规则，无法复用参数")
        return
    if run["rule_version"] != RULES[run["rule_name"]]().version:
        st.warning("规则版本不同；下次模拟将使用当前规则版本")
    try:
        pool_config = PoolConfig.from_dict(run["pool_config"])
    except (KeyError, TypeError, ValueError):
        st.warning("历史配置无效，无法复用参数")
        return
    st.session_state.update(
        rule_name=run["rule_name"], draws=run["main_draws"], trials=run["trials"],
        initial_pity=run["initial_pity"], seed_text=str(run["seed"]),
        trace=run["trace_enabled"] and run["trials"] == 1,
        initial_five_star_pity=run["initial_five_star_pity"],
    )
    set_pool_config_editor_state(st, pool_config)


def render_history(st, repository):
    st.header("历史记录")
    recent_rules = {row["rule_name"] for row in repository.list_runs({}, limit=20, offset=0)}
    rule_name = st.selectbox("历史规则", ("全部", *sorted(set(RULES) | recent_rules)), accept_new_options=True,
                             help="可输入已停用的历史规则名称")
    trace = st.selectbox("历史 Trace", ("全部", "含 Trace", "不含 Trace"))
    start = st.date_input("历史开始日期（UTC）", value=None)
    end = st.date_input("历史结束日期（UTC）", value=None)
    page = st.number_input("历史页码", min_value=1, value=1, step=1)
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
    rows = repository.list_runs(filters, limit=20, offset=(page - 1) * 20)
    st.caption("每页最多 20 条，按创建时间倒序；改变筛选后可将页码设为 1")
    if rows:
        st.dataframe([{
            "运行 ID": row["id"], "时间": row["created_at"], "规则": row["rule_name"],
            "种子": str(row["seed"]), "主池抽数": row["main_draws"],
            "实验轮数": row["trials"], "总六星均值": row["mean_six_stars"],
            "误差": row["mean_count_error"],
        } for row in rows], hide_index=True, width="stretch")
    else:
        st.info("此页没有历史记录")
    ids = [row["id"] for row in rows]
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
            del st.session_state["pending_delete_id"]
            st.rerun()
        if st.button("取消删除"):
            del st.session_state["pending_delete_id"]
            st.rerun()
    summaries = {row["id"]: row for row in rows}
    runs = [
        repository.get_run(run_id, include_records=summaries[run_id]["trace_enabled"])
        for run_id in selected if run_id in summaries
    ]
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
            with st.expander("配置摘要"):
                summary = StringIO()
                _write_config_summary(run["pool_config"], summary)
                print(f'初始五星进度：{run["initial_five_star_pity"]}', file=summary)
                st.text(summary.getvalue())
            if st.button("复用参数 " + run["id"]):
                st.session_state["pending_reuse_id"] = run["id"]
                st.rerun()
            if st.button("删除历史 " + run["id"]):
                st.session_state["pending_delete_id"] = run["id"]
                st.rerun()
            render_result(st, run, trace_enabled=run["trace_enabled"], saved_snapshot=True)
