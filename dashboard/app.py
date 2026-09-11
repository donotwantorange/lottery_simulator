"""Run with: streamlit run dashboard/app.py."""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
from uuid import uuid4

import streamlit as st

# Streamlit's console entrypoint adds dashboard/, not the project package root.
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dashboard.auth import AuthConfig, require_access
from dashboard.jobs import ACTIVE_STATUSES, JobAlreadyRunning, JobManager, timestamp
from dashboard.models import JobState, RunParameters, write_json
from dashboard.views.simulation import render_result
from dashboard.worker import run
from lottery_simulator.cli import RULES


class SynchronousJobManager(JobManager):
    """Development AppTest adapter; reuse the real worker and persistence path."""

    def start(self, parameters):
        parameters.validate()
        with self._locked():
            if any(self._active_states()):
                raise JobAlreadyRunning("已有模拟任务正在运行")
            state = JobState(str(uuid4()), "queued", parameters.to_dict(), 0,
                             parameters.draws * parameters.trials, updated_at=timestamp())
            job_dir = self.root / state.job_id
            write_json(job_dir / "parameters.json", parameters.to_dict())
            write_json(job_dir / "state.json", state.to_dict())
        run(job_dir, self.database_path)
        return self.get(state.job_id)


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


st.set_page_config(page_title="抽奖概率实验室", layout="wide")
require_dashboard_access()

data_dir = Path(os.environ.get("LOTTERY_DATA_DIR", project_root / "data"))
manager_type = SynchronousJobManager if os.environ.get("DASHBOARD_SYNC_JOBS") == "1" else JobManager
manager = manager_type(data_dir / "jobs", data_dir / "history.sqlite3")
current_id = st.session_state.get("current_job_id")
current = manager.get(current_id)
live = current is not None and current.status in ACTIVE_STATUSES

st.title("抽奖概率实验室")
with st.sidebar:
    rule_name = st.selectbox("规则", tuple(RULES))
    draws = st.number_input("主池抽数", min_value=1, value=100, step=1)
    trials = st.number_input("实验轮数", min_value=1, value=1, step=1)
    initial_pity = st.number_input("假设主池已累计多少抽仍未出6星", min_value=0,
                                   value=0, step=1)
    seed_text = st.text_input("随机种子（留空自动生成）")
    trace = st.toggle("Trace", disabled=trials != 1, help="逐抽记录仅支持单轮模拟")
    if st.button("开始模拟", disabled=live):
        try:
            seed = int(seed_text) if seed_text.strip() else None
        except ValueError:
            st.error("随机种子必须为整数")
        else:
            try:
                parameters = RunParameters(rule_name, draws, trials, initial_pity,
                                           seed, trace and trials == 1).validate()
            except ValueError as error:
                st.error(str(error))
            else:
                try:
                    state = manager.start(parameters)
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
