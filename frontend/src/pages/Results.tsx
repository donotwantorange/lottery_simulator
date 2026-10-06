import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { JobDetail, JobSummary, Page, RunResult } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ChartPanel } from "../components/ChartPanel";
import { TraceTable } from "../components/TraceTable";

const views = ["实验概览", "分类统计", "按抽次分析", "过程明细"] as const;
const count = (value: string) => BigInt(value).toLocaleString("zh-CN");

export function ResultView({ base, result, runId }: { base: string; result: RunResult; runId?: string | null }) {
  const [view, setView] = useState<(typeof views)[number]>("实验概览");
  const labels = Object.fromEntries(result.rule_snapshot.rarities.map((rarity) => [
    rarity.id, result.pool_snapshot.rarity_labels[rarity.id] ?? rarity.name,
  ]));
  const acquired = result.simulation.acquisitions.character_count ?? 0;
  const expectedAcquired = result.theoretical.acquisitions.character_count ?? 0;
  const acquisitionError = expectedAcquired === 0 ? "不可用" :
    `${(Math.abs((acquired - expectedAcquired) / expectedAcquired) * 100).toPrecision(6)}%`;
  const overview = [
    ["每轮主池抽数", count(result.parameters.draws)], ["实验轮数", count(result.parameters.trials)],
    ["主池抽取总数", count(result.counts.main_draws)], ["赠送抽总数", count(result.counts.bonus_draws)],
    ["真实抽取总数", count(result.counts.total_draws)], ["直接赠送事件", count(result.counts.grant_triggers)],
    ["直接赠送角色数", count(result.counts.granted_characters)],
    ["每轮角色获得均值", String(acquired)], ["理论每轮角色获得期望", String(expectedAcquired)],
    ["角色获得均值相对误差", acquisitionError],
  ] as const;
  return <section className="panel page-stack"><div className="button-row" role="tablist" aria-label="结果视图">{views.map((name) => <button key={name} role="tab" aria-selected={view === name} onClick={() => setView(name)}>{name}</button>)}</div>
    {view === "实验概览" && <><div className="metric-grid">{overview.map(([label, value]) => <div key={label} className="metric-card"><span>{label}</span><strong>{value}</strong></div>)}</div>
      <p className="muted">规则：{result.rule_snapshot.name}（修订 {result.rule_source?.revision ?? result.rule_revision_snapshot ?? "—"}）· 角色池：{result.pool_snapshot.name}（修订 {result.pool_source?.revision ?? result.pool_revision_snapshot ?? "—"}）</p>
      <p className="muted">稀有度：{Object.values(labels).join("、")}</p>
      <p className="muted">随机种子 {result.seed} · 耗时 {result.duration_seconds} 秒 · {result.trace_enabled ? `过程明细 ${count(result.event_count)} 条` : "未启用过程明细"}</p>
      <p className="muted">抽取会计入抽数、概率和奖励；周期赠送是独立事件；角色获得统计会同时包含抽取与赠送。</p>
      {runId ? <a className="secondary-button" href={`/api/v1/runs/${encodeURIComponent(runId)}/?download=json`}>下载汇总 JSON</a> : <p className="muted">本任务尚未保存历史，暂不能下载完整快照JSON。</p>}</>}
    {view === "分类统计" && <ChartPanel key={`${base}-summary`} base={base} result={result} mode="summary" />}
    {view === "按抽次分析" && <ChartPanel key={`${base}-position`} base={base} result={result} mode="position" />}
    {view === "过程明细" && (result.trace_enabled ? <TraceTable key={base} base={base} runId={runId} result={result} /> : <p className="muted">本次运行未保存过程明细，无法事后补生成。</p>)}
    <p className="muted">规则、角色池及理论和模拟统计均来自本次冻结快照。零理论期望时，相对误差不可用。</p>
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
  const [pollError, setPollError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setError(""); setPollError("");
    setJobs(null); setJob(null); setResult(null);
    void apiRequest<Page<JobSummary>>("jobs/mine/?page=1&page_size=50", {}, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setJobs(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [user?.id, sessionGeneration]);

  useEffect(() => {
    setJob(null); setResult(null); setError(""); setPollError("");
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const schedule = (delay: number) => { timer = setTimeout(() => { timer = undefined; void refresh(); }, delay); };
    async function refresh() {
      try {
        const value = await apiRequest<JobDetail>(`jobs/${jobId}/`, {}, controller.signal);
        if (stopped) return;
        setPollError("");
        setJob(value);
        if (value.status === "queued" || value.status === "running") schedule(document.hidden ? 10_000 : 2_000);
      } catch (cause) {
        if (stopped) return;
        setPollError(errorMessage(cause));
        if (cause instanceof TypeError || (cause instanceof ApiError && cause.status >= 500)) schedule(document.hidden ? 10_000 : 2_000);
      }
    }
    function visibilityChanged() { if (timer) { clearTimeout(timer); schedule(document.hidden ? 10_000 : 0); } }
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

  return <div className="page-stack"><section className="panel"><div className="section-heading"><div><h2>当前任务</h2><p className="muted">活动任务定期更新；页面隐藏时降低查询频率。</p></div></div>
    <label className="compact-field">本人最近任务<select value={jobId} onChange={(event) => setParams(event.target.value ? { job: event.target.value } : {})}><option value="">选择任务</option>{jobId && jobs && !jobs.items.some((item) => item.job_id === jobId) && <option value={jobId}>{job?.pool_name_snapshot ?? jobId} · 当前查看</option>}{jobs?.items.map((item) => <option key={item.job_id} value={item.job_id}>{new Date(item.accepted_at).toLocaleString()} · {item.pool_name_snapshot} · {item.job_id === job?.job_id ? job.status : item.status}</option>)}</select></label>
    {job && <><p>状态：{job.status}{job.phase ? ` · ${job.phase}` : ""}{job.cancel_requested ? " · 已请求停止" : ""}</p><p className="muted">总进度：{job.completed_units} / {job.total_units}{job.phase_total ? `；当前阶段 ${job.phase_completed ?? "0"} / ${job.phase_total}` : ""}</p>{(job.status === "queued" || job.status === "running") && <button disabled={busy || job.cancel_requested} onClick={() => void cancel()}>停止任务</button>}{job.error && <p className="form-error">{job.error}</p>}{job.cleanup_error && <p className="form-error">临时任务文件清理待处理：{job.cleanup_error}</p>}{job.persistence_error && <p className="form-error">结果未保存到历史：{job.persistence_error}</p>}{job.run_id && <p><Link to={`/history/?run=${job.run_id}`}>查看已保存历史</Link></p>}</>}
    {!jobId && <p className="muted">请选择本人任务，或从新建实验提交后进入本页。</p>}{pollError && <p className="form-error" role="alert">{pollError}</p>}{error && <p className="form-error" role="alert">{error}</p>}
  </section>{result && job && <ResultView base={`jobs/${job.job_id}`} result={result} runId={job.run_id} />}</div>;
}
