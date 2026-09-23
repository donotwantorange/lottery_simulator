"""Authenticated rendering of an active dashboard job."""


def render_active_job(st, manager, current_id, authenticate) -> None:
    """Authenticate before every status read or cancellation action."""
    authenticate()
    current = manager.get(current_id)
    if current is None or current.status not in {"queued", "running"}:
        st.rerun()
        return
    phases = {
        "simulating": "模拟运行中", "theory": "计算理论统计",
        "validating": "校验明细", "saving": "写入明细/保存历史", "committing": "提交历史",
    }
    st.info("已请求停止，正在安全结束任务" if current.cancel_requested else
            "等待运行" if current.status == "queued" else
            phases.get(current.phase, "模拟运行中"))
    if current.phase_total is not None:
        st.progress(current.phase_completed / current.phase_total if current.phase_total else 0.0,
                    text=f"{current.phase_completed:,} / {current.phase_total:,}")
    elif current.phase in (None, "simulating"):
        st.progress(current.completed_units / current.total_units if current.total_units else 0.0,
                    text=f"{current.completed_units:,} / {current.total_units:,}")
    elapsed = current.duration_seconds or 0.0
    if current.started_at:
        from datetime import datetime, timezone
        elapsed = max(
            elapsed,
            (datetime.now(timezone.utc) - datetime.fromisoformat(current.started_at)).total_seconds(),
        )
    st.caption(f"已用时 {elapsed:.1f} 秒")
    st.caption(f"主抽 {current.completed_units:,} / {current.total_units:,}")
    if st.button("停止模拟", key="stop-active-job", disabled=current.cancel_requested):
        manager.cancel(current_id)
        st.rerun()
