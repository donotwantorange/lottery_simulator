"""Authenticated rendering of an active dashboard job."""


def render_active_job(st, manager, current_id, authenticate) -> None:
    """Authenticate before every status read or cancellation action."""
    authenticate()
    current = manager.get(current_id)
    if current is None or current.status not in {"queued", "running"}:
        st.rerun()
        return
    st.info("写入明细/保存历史" if current.phase == "saving" else
            "等待运行" if current.status == "queued" else "模拟运行中")
    st.progress(
        current.completed_units / current.total_units if current.total_units else 0.0,
        text=f"{current.completed_units:,} / {current.total_units:,}",
    )
    elapsed = current.duration_seconds or 0.0
    if current.started_at:
        from datetime import datetime, timezone
        elapsed = max(
            elapsed,
            (datetime.now(timezone.utc) - datetime.fromisoformat(current.started_at)).total_seconds(),
        )
    st.caption(f"已用时 {elapsed:.1f} 秒")
    if st.button("停止模拟", key="stop-active-job"):
        manager.cancel(current_id)
