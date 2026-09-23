"""Run with: streamlit run dashboard/app.py."""

import logging
import os
from pathlib import Path
import sys

import streamlit as st

# Streamlit's console entrypoint adds dashboard/, not the project package root.
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dashboard.auth import AuthConfig, require_access
from dashboard.jobs import ACTIVE_STATUSES, JobManager
from dashboard.repository import HistoryRepository
from dashboard.views.history import apply_pending_reuse, render_history, reuse_parameters
from dashboard.views.job_status import render_active_job
from dashboard.views.new_experiment import render_new_experiment
from dashboard.views.simulation import render_result, render_summary_download
from dashboard.views.trace_details import result_owner


def require_dashboard_access():
    try:
        config = AuthConfig.from_env()
        if config.environment == "production" and os.environ.get("DASHBOARD_SYNC_JOBS") == "1":
            st.error("生产环境禁止 DASHBOARD_SYNC_JOBS=1")
            st.stop()
        require_access(st, config)
    except ValueError:
        st.error("认证配置无效，请联系管理员")
        st.stop()


@st.cache_resource
def startup_job_manager(job_root: str, database_path: str) -> JobManager:
    """Reconcile abandoned jobs once for this Streamlit process and data root."""
    manager = JobManager(job_root, database_path)
    manager.reconcile_after_restart()
    return manager


@st.cache_resource
def startup_repository(database_path: str) -> HistoryRepository:
    repository = HistoryRepository(database_path)
    repository.initialize()
    return repository


def _selected_result(st):
    value = st.session_state.get("selected_result")
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return tuple(value)
    return None


def _render_active_status(manager, current_id):
    state = manager.get(current_id) if current_id is not None else None
    if state is None or state.status not in ACTIVE_STATUSES:
        return

    @st.fragment(run_every=0.5)
    def poll_job():
        render_active_job(st, manager, current_id, require_dashboard_access)

    poll_job()


def _render_selected_result(st, manager, repository):
    selected = _selected_result(st)
    if selected is None:
        st.info("请选择一个实验结果，或先开始模拟")
        return
    kind, identifier = selected
    if st.session_state.get("result-owner") != selected:
        st.session_state["result-owner"] = selected
        for key in ("trace-page", "trace-download", "trace-filter-signature"):
            st.session_state.pop(key, None)
    payload = None
    trace_enabled = False
    trace_reader = None
    saved_snapshot = kind == "history"
    persistence_error = False
    history_saved = saved_snapshot
    if kind == "job":
        state = manager.get(identifier)
        if state is not None and state.cleanup_error:
            st.warning("计算已停止，残次文件清理未完成")
        if state is not None and state.status == "cancelled":
            st.info("模拟已取消")
            return
        if state is not None and state.status == "failed":
            st.error("模拟任务失败")
            return
        if state is not None and state.history_saved:
            history_id = state.run_id or identifier
            if repository.get_run(history_id) is None:
                st.info("历史记录已删除，当前任务结果不可恢复")
                return
        payload = manager.get_result(identifier)
        if state is not None:
            trace_enabled = bool(state.parameters.get("trace"))
            persistence_error = bool(state.persistence_error)
            history_saved = bool(state.history_saved)
        if payload is None and state is not None and state.status in ACTIVE_STATUSES:
            st.info("模拟运行中，请稍候")
            return
        result_view = st.session_state.get(
            f'result-view-{result_owner(st, payload)}' if payload is not None else "",
            "实验概览",
        )
        if payload is not None and trace_enabled and result_view in ("按抽次分析", "逐抽明细"):
            trace_reader = manager.get_trace_reader(identifier)
    elif kind == "history":
        payload = repository.get_run(identifier)
        if payload is None:
            st.warning("所选历史记录已不存在")
            st.session_state.pop("selected_result", None)
            return
        trace_enabled = payload["trace_enabled"]
        result_view = st.session_state.get(
            f'result-view-{result_owner(st, payload)}', "实验概览"
        )
        if trace_enabled and result_view in ("按抽次分析", "逐抽明细"):
            trace_reader = repository.get_trace_reader(identifier)
    else:
        st.warning("所选实验结果引用无效")
        st.session_state.pop("selected_result", None)
        return
    if payload is None:
        st.info("模拟结果暂不可用")
        return
    if kind == "job":
        st.success("模拟已完成")
        state = manager.get(identifier)
        if state is not None and state.persistence_error:
            st.warning("历史保存失败")
    st.subheader("实验结果")
    st.caption(f"结果来源：{'历史记录' if saved_snapshot else '当前任务'} · {identifier}")
    draws = payload.get("draws", 0)
    bonus_draws = payload.get("bonus_draws", 0)
    trials = payload.get("trials", 0)
    st.subheader("实验规模")
    scale = st.columns(3)
    scale[0].metric("实验轮数", f"{trials:,}")
    scale[1].metric("每轮总抽数", f"{draws + bonus_draws:,}")
    scale[2].metric("全实验总抽数", f"{(draws + bonus_draws) * trials:,}")
    save_state = "已完成且已保存" if history_saved else (
        "已完成但历史保存失败" if persistence_error else "已完成，未保存"
    )
    st.caption(
        f"{save_state} · Trace：{'启用' if trace_enabled else '关闭'} · "
        f"记录数：{payload.get('record_count', 0):,}"
    )
    actions = st.columns(2)
    with actions[0]:
        reuse_requested = st.button("复用参数", key=f"result-reuse-{kind}-{identifier}")
    render_summary_download(
        actions[1], payload, key=f"result-download-{kind}-{identifier}",
    )
    with st.expander("参数与配置快照"):
        st.json({key: payload.get(key) for key in (
            "rule_name", "rule_version", "main_draws", "trials", "seed",
            "initial_pity", "initial_five_star_pity", "trace_enabled",
            "result_format_version", "sampling_version", "pool_config",
        )})
    if reuse_requested:
        if reuse_parameters(st, payload):
            st.rerun()
    render_result(st, payload, trace_reader, saved_snapshot=saved_snapshot)


st.set_page_config(page_title="抽奖概率实验室", layout="wide")
require_dashboard_access()

data_dir = Path(os.environ.get("LOTTERY_DATA_DIR", project_root / "data"))
database_path = Path(os.environ.get("LOTTERY_DB_PATH", data_dir / "history_v4.sqlite3"))
manager = startup_job_manager(str(data_dir / "jobs_v4"), str(database_path))
try:
    repository = startup_repository(str(database_path))
except Exception:
    logging.getLogger(__name__).exception("History database initialization failed")
    st.error("历史数据库暂不可用；当前为只读错误页。请联系管理员检查迁移或从备份恢复。")
    st.stop()

apply_pending_reuse(st, repository)
pending_delete = st.session_state.get("pending_delete_id")
if pending_delete and repository.get_run(pending_delete) is None:
    st.session_state.pop("pending_delete_id", None)
    st.warning("待删除的历史记录已不存在")
pending_page = st.session_state.pop("_pending_page", None)
if pending_page in ("新建实验", "实验结果", "历史记录"):
    st.session_state["page"] = pending_page
current_id = st.session_state.get("current_job_id")
active = manager.get_active()
if active is not None:
    current_id = active.job_id
    st.session_state["current_job_id"] = current_id
elif current_id is not None and manager.get(current_id) is None:
    st.session_state.pop("current_job_id", None)
    current_id = None
live = active is not None

st.title("抽奖概率实验室")
st.session_state.setdefault("page", "新建实验")
with st.sidebar:
    page = st.radio("导航", ("新建实验", "实验结果", "历史记录"), key="page")
    if live:
        st.caption(f"当前任务：{current_id}")
    _render_active_status(manager, current_id)

if page == "新建实验":
    render_new_experiment(
        st, manager, live=live,
        synchronous=os.environ.get("DASHBOARD_SYNC_JOBS") == "1",
    )
elif page == "实验结果":
    _render_selected_result(st, manager, repository)
elif page == "历史记录":
    render_history(st, repository)
