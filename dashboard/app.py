"""Run with: streamlit run dashboard/app.py."""

from datetime import datetime, timezone
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
from dashboard.jobs import (
    ACTIVE_STATUSES,
    JobAlreadyRunning,
    JobManager,
    validate_parameters_for_active_rule,
)
from dashboard.models import RunParameters
from dashboard.repository import HistoryRepository
from dashboard.views.configuration import render_pool_config_editor
from dashboard.views.history import apply_pending_reuse, render_history
from dashboard.views.simulation import render_result
from lottery_simulator.cli import RULES


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


st.set_page_config(page_title="抽奖概率实验室", layout="wide")
require_dashboard_access()

data_dir = Path(os.environ.get("LOTTERY_DATA_DIR", project_root / "data"))
database_path = Path(os.environ.get("LOTTERY_DB_PATH", data_dir / "history_v2.sqlite3"))
manager = startup_job_manager(str(data_dir / "jobs"), str(database_path))
repository = HistoryRepository(database_path)
try:
    repository.initialize()
except Exception:
    logging.getLogger(__name__).exception("History database initialization failed")
    st.error("历史数据库暂不可用；当前为只读错误页。请联系管理员检查迁移或从备份恢复。")
    st.stop()
apply_pending_reuse(st, repository)
current_id = st.session_state.get("current_job_id")
current = manager.get_active()
if current is not None:
    current_id = current.job_id
    st.session_state["current_job_id"] = current_id
else:
    current = manager.get(current_id)
live = current is not None and current.status in ACTIVE_STATUSES

st.title("抽奖概率实验室")
st.session_state.setdefault("draws", 100)
with st.sidebar:
    rule_name = st.selectbox("规则", tuple(RULES), key="rule_name")
    draws = st.number_input("主池抽数", min_value=1, step=1, key="draws")
    trials = st.number_input("实验轮数", min_value=1, step=1, key="trials")
    initial_pity = st.number_input("假设主池已累计多少抽仍未出6星", min_value=0,
                                   step=1, key="initial_pity",
                                   help="该值同时初始化主池保底位置与累计主池抽数；累计抽数决定首次30抽赠送是已领取还是会在本次模拟中触发。")
    seed_text = st.text_input("随机种子（留空自动生成）", key="seed_text")
    trace = st.toggle("Trace", disabled=trials != 1, help="逐抽记录仅支持单轮模拟", key="trace")
    with st.expander("高级设置"):
        five_star_pity_enabled = st.session_state.get("pool_five_star_pity_enabled", True)
        if not five_star_pity_enabled:
            st.session_state["initial_five_star_pity"] = 0
        initial_five_star_pity = st.number_input(
            "假设主池已连续多少抽未出5星及以上", min_value=0, step=1,
            disabled=not five_star_pity_enabled, key="initial_five_star_pity",
        )
    try:
        pool_config = render_pool_config_editor(st)
    except ValueError as error:
        st.error(str(error))
        pool_config = None
    if st.button("开始模拟", disabled=live):
        try:
            seed = int(seed_text) if seed_text.strip() else None
        except ValueError:
            st.error("随机种子必须为整数")
        else:
            try:
                if pool_config is None:
                    raise ValueError("奖池配置无效，请修正后重试")
                parameters = validate_parameters_for_active_rule(
                    RunParameters(rule_name, draws, trials, initial_pity,
                                  seed, trace and trials == 1,
                                  initial_five_star_pity, pool_config.to_dict())
                )
            except ValueError as error:
                st.error(str(error))
            else:
                try:
                    state = manager.start(
                        parameters, synchronous=os.environ.get("DASHBOARD_SYNC_JOBS") == "1")
                except JobAlreadyRunning:
                    st.error("已有模拟任务正在运行")
                except Exception:
                    logging.getLogger(__name__).exception("Could not start simulation")
                    st.error("模拟任务启动失败")
                else:
                    st.session_state["current_job_id"] = state.job_id
                    st.rerun()

if live:
    @st.fragment(run_every=0.5)
    def poll_job():
        require_dashboard_access()
        state = manager.get(current_id)
        if state is None or state.status not in ACTIVE_STATUSES:
            st.rerun()
        st.info("等待运行" if state.status == "queued" else "模拟运行中")
        st.progress(state.completed_units / state.total_units if state.total_units else 0.0,
                    text=f"{state.completed_units:,} / {state.total_units:,}")
        elapsed = state.duration_seconds or 0.0
        if state.started_at:
            elapsed = max(elapsed, (datetime.now(timezone.utc)
                                   - datetime.fromisoformat(state.started_at)).total_seconds())
        st.caption(f"已用时 {elapsed:.1f} 秒")
        if st.button("停止模拟"):
            manager.cancel(current_id)
    poll_job()
elif current is None:
    st.info("设置参数后开始模拟")
elif current.status == "cancelled":
    st.info("模拟已取消")
elif current.status == "failed":
    st.error("模拟任务失败")
elif current.status == "completed":
    st.success("模拟已完成")
    if current.persistence_error:
        st.warning("历史保存失败")
    payload = manager.get_result(current_id)
    if payload is not None:
        render_result(st, payload, trace_enabled=current.parameters["trace"])
    else:
        st.error("模拟结果暂不可用")

render_history(st, repository)
