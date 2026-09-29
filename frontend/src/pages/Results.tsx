import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import { saveSmallJson } from "../api/files";
import type { JobDetail, JobSummary, Page, RunResult } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ChartPanel } from "../components/ChartPanel";
import { TraceTable } from "../components/TraceTable";

const views = ["实验概览", "分类统计", "按抽次分析", "逐抽明细"] as const;

export function ResultView({ base, result, runId }: { base: string; result: RunResult; runId?: string | null }) {
  const [view, setView] = useState<(typeof views)[number]>("实验概览");
  const rarityLabels = result.pool_config.rarity_labels ?? { "4": "四星", "5": "五星", "6": "六星" };
  const overview = [
    [`模拟${rarityLabels["6"]}均值`, result.mean_six_stars], [`理论${rarityLabels["6"]}期望`, result.theoretical_expected_count],
    ["相对误差", result.mean_count_relative_error === null ? "不可用" : `${(Math.abs(result.mean_count_relative_error) * 100).toFixed(4)}%`],
    ["每轮主池抽数", result.main_draws], ["每轮赠送抽数", result.bonus_draws], ["每轮总抽数", result.total_draws],
    ["实验总主池抽数", String(BigInt(result.main_draws) * BigInt(result.trials))],
    ["实验总赠送抽数", String(BigInt(result.bonus_draws) * BigInt(result.trials))],
    ["实验总抽数", String(BigInt(result.total_draws) * BigInt(result.trials))],
  ] as const;
  return <section className="panel page-stack"><div className="button-row" role="tablist" aria-label="结果视图">{views.map((name) => <button key={name} role="tab" aria-selected={view === name} onClick={() => setView(name)}>{name}</button>)}</div>
    {view === "实验概览" && <><div className="metric-grid">{overview.map(([label, value]) => <div key={label} className="metric-card"><span>{label}</span><strong>{value}</strong></div>)}</div><p className="muted">规则 {result.rule_name} · 版本 {result.rule_version} · {result.trials} 轮 · 种子 {result.seed} · 耗时 {result.duration_seconds ?? "—"} 秒</p><p className="muted">角色池快照：{result.pool_name_snapshot ?? "—"}；Trace {result.trace_enabled ? `${result.record_count} 条` : "未启用"}。</p><button onClick={() => saveSmallJson(Object.fromEntries(Object.entries(result).filter(([key]) => key !== "records")), "simulation-result.json")}>下载汇总 JSON</button></>}
    {view === "分类统计" && <ChartPanel key={`${base}-summary`} base={base} result={result} mode="summary" />}
    {view === "按抽次分析" && <ChartPanel key={`${base}-position`} base={base} result={result} mode="position" />}
    {view === "逐抽明细" && (result.trace_enabled ? <TraceTable key={base} base={base} runId={runId} result={result} /> : <p className="muted">本次运行未保存逐抽结果。</p>)}
  </section>;
}

export function Results() {
  const { user, sessionGeneration } = useAuth();
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job") ?? "";
  const [jobs, setJobs] = useState<Page<JobSummary> | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setJobs(null); setJob(null); setResult(null);
    void apiRequest<Page<JobSummary>>("jobs/mine/?page=1&page_size=50", {}, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setJobs(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [user?.id, sessionGeneration]);

  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    setJob(null); setResult(null); setError("");
    function schedule(delay: number) {
      timer = setTimeout(() => { timer = undefined; void refresh(); }, delay);
    }
    async function refresh() {
      try {
        const value = await apiRequest<JobDetail>(`jobs/${jobId}/`, {}, controller.signal);
        if (stopped) return;
        setJob(value);
        if (value.status === "queued" || value.status === "running") {
          schedule(document.hidden ? 10_000 : 2_000);
        }
      } catch (cause) {
        if (stopped) return;
        setError(errorMessage(cause));
        if (cause instanceof TypeError || (cause instanceof ApiError && cause.status >= 500)) {
          schedule(document.hidden ? 10_000 : 2_000);
        }
      }
    }
    function visibilityChanged() {
      if (timer) { clearTimeout(timer); schedule(document.hidden ? 10_000 : 0); }
    }
    document.addEventListener("visibilitychange", visibilityChanged);
    void refresh();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", visibilityChanged); };
  }, [jobId, user?.id, sessionGeneration]);

  useEffect(() => {
    if (job?.status !== "completed") return;
    const controller = new AbortController();
    void apiRequest<RunResult>(`jobs/${job.job_id}/result/`, {}, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setResult(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [job?.job_id, job?.status, sessionGeneration]);

  async function cancel() {
    if (!job || busy) return;
    setBusy(true); setError("");
    try { setJob(await apiRequest<JobDetail>(`jobs/${job.job_id}/cancel/`, { method: "POST" })); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  return <div className="page-stack"><section className="panel"><div className="section-heading"><div><h2>当前任务</h2><p className="muted">活动任务每2秒更新；隐藏页面会降低查询频率。</p></div></div>
    <label className="compact-field">本人最近任务<select value={jobId} onChange={(event) => setParams(event.target.value ? { job: event.target.value } : {})}><option value="">选择任务</option>{jobId && jobs && !jobs.items.some((item) => item.job_id === jobId) && <option value={jobId}>{job?.pool_name_snapshot ?? jobId} · 当前查看</option>}{jobs?.items.map((item) => <option key={item.job_id} value={item.job_id}>{new Date(item.accepted_at).toLocaleString()} · {item.pool_name_snapshot} · {item.status}</option>)}</select></label>
    {job && <><p>状态：{job.status} {job.phase ? `· ${job.phase}` : ""}{job.cancel_requested ? " · 已请求停止" : ""}</p><p className="muted">进度：{job.completed_units} / {job.total_units}{job.phase_total ? `；当前阶段 ${job.phase_completed ?? 0} / ${job.phase_total}` : ""}</p>{(job.status === "queued" || job.status === "running") && <button disabled={busy || job.cancel_requested} onClick={() => void cancel()}>停止任务</button>}{job.error && <p className="form-error">{job.error}</p>}{job.persistence_error && <p className="form-error">结果未保存到历史：{job.persistence_error}</p>}{job.run_id && <p><Link to={`/history/?run=${job.run_id}`}>查看已保存历史</Link></p>}</>}
    {!jobId && <p className="muted">请选择本人任务，或从新建实验提交后进入本页。</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>{result && job && <ResultView base={`jobs/${job.job_id}`} result={result} runId={job.run_id} />}</div>;
}
