import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { JobDetail, JobSummary, Page, Pool, RunResult, RunSummary } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ResultView } from "./Results";

export function History() {
  const { user, sessionGeneration } = useAuth();
  const [params, setParams] = useSearchParams();
  const runId = params.get("run") ?? "";
  const [rule, setRule] = useState("");
  const [trace, setTrace] = useState("");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<Page<RunSummary> | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [submittedJobId, setSubmittedJobId] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [recentJobs, setRecentJobs] = useState<Page<JobSummary> | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const search = new URLSearchParams({ page: String(page), page_size: "20" });
    if (rule) search.set("rule_name", rule);
    if (trace) search.set("trace", trace);
    setList(null); setError("");
    void apiRequest<Page<RunSummary>>(`runs/?${search}`, {}, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setList(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [rule, trace, page, reload, user?.id, sessionGeneration]);

  useEffect(() => {
    if (!runId) { setResult(null); return; }
    const controller = new AbortController();
    setResult(null); setPendingDelete(false); setError("");
    void apiRequest<RunResult>(`runs/${runId}/`, {}, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setResult(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [runId, reload, user?.id, sessionGeneration]);

  async function remove() {
    if (!runId || !pendingDelete || busy) return;
    setBusy(true); setError("");
    try {
      await apiRequest<void>(`runs/${runId}/`, { method: "DELETE" });
      setParams({}); setResult(null); setPendingDelete(false); setSubmittedJobId(""); setReload((value) => value + 1);
      setMessage("历史记录已删除");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function rerun() {
    if (!result || !runId || busy || !result.pool_id_snapshot) return;
    setBusy(true); setError(""); setMessage(""); setSubmittedJobId(""); setUncertain(false); setRecentJobs(null);
    try {
      const pool = await apiRequest<Pool>(`pools/${result.pool_id_snapshot}/`);
      const differences = [
        pool.revision !== result.pool_revision_snapshot ? `池修订从 ${result.pool_revision_snapshot} 变为 ${pool.revision}` : null,
        pool.name !== result.pool_name_snapshot ? `池名称从「${result.pool_name_snapshot}」变为「${pool.name}」` : null,
        JSON.stringify(pool.rarity_labels) !== JSON.stringify(result.pool_config.rarity_labels ?? {}) ? "稀有度显示名称已变化" : null,
      ].filter(Boolean);
      const description = differences.length ? differences.join("；") : "当前角色池与历史快照没有发现差异";
      if (!window.confirm(`${description}。重跑使用当前角色池配置和历史参数；确认提交新任务？`)) return;
      // A revision may change while the user reads the warning. Recheck before submit.
      const latest = await apiRequest<Pool>(`pools/${pool.id}/`);
      if (latest.revision !== pool.revision) {
        setError("确认期间角色池修订已变化，请重新查看差异后再试"); return;
      }
      const parameters = { draws: String(result.main_draws), trials: String(result.trials),
        initial_pity: String(result.initial_pity), initial_five_star_pity: String(result.initial_five_star_pity),
        seed: result.seed, trace: result.trace_enabled };
      try {
        const job = await apiRequest<JobDetail>("jobs/", { method: "POST",
          body: JSON.stringify({ pool_id: latest.id, expected_revision: latest.revision, parameters }) });
        setSubmittedJobId(job.job_id);
        setMessage(`重跑任务已接受：${job.job_id}。`);
      } catch (cause) {
        if (cause instanceof ApiError && cause.status < 500) throw cause;
        setUncertain(true);
        setMessage("重跑提交结果未确认，系统没有自动重试。请按接受时间、角色池与参数人工核对本人任务。");
        try { setRecentJobs(await apiRequest<Page<JobSummary>>("jobs/mine/?page=1&page_size=50")); }
        catch (lookupError) { setError(errorMessage(lookupError)); }
      }
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function lookupJobs() {
    try { setRecentJobs(await apiRequest<Page<JobSummary>>("jobs/mine/?page=1&page_size=50")); setError(""); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  const pageCount = Math.max(1, Math.ceil((list?.total ?? 0) / 20));
  return <div className="page-stack"><section className="panel"><div className="section-heading"><div><h2>历史记录</h2><p className="muted">按创建时间倒序；权限由服务器逐项检查。</p></div></div>
    <div className="field-grid"><label className="compact-field">规则名称<input value={rule} onChange={(event) => { setRule(event.target.value); setPage(1); }} placeholder="全部规则" /></label><label className="compact-field">Trace<select value={trace} onChange={(event) => { setTrace(event.target.value); setPage(1); }}><option value="">全部</option><option value="true">含 Trace</option><option value="false">不含 Trace</option></select></label></div>
    <p className="muted">{list ? `共 ${list.total} 条 · 第 ${page}/${pageCount} 页` : "正在查询历史…"}</p>
    {list && <div className="table-wrap"><table><thead><tr><th>创建时间</th><th>角色池</th><th>规则</th><th>主抽数</th><th>轮数</th><th>Trace记录</th><th>操作</th></tr></thead><tbody>{list.items.map((item) => <tr key={item.id}><td>{new Date(item.created_at).toLocaleString()}</td><td>{item.pool_name_snapshot}</td><td>{item.rule_name}</td><td>{item.draws}</td><td>{item.trials}</td><td>{item.record_count}</td><td><button onClick={() => setParams({ run: item.id })}>查看</button></td></tr>)}</tbody></table></div>}
    <div className="button-row"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><button disabled={page >= pageCount} onClick={() => setPage(page + 1)}>下一页</button></div>
  </section>
    {runId && result && <><section className="panel"><div className="section-heading"><div><h2>历史快照</h2><p className="muted">{runId} · 保存时池修订 {result.pool_revision_snapshot}</p></div></div>
      <div className="button-row"><button disabled={busy} onClick={() => void rerun()}>按当前角色池重跑</button><button className="danger-button" disabled={busy} onClick={() => setPendingDelete(true)}>删除历史</button></div>
      {pendingDelete && <div className="import-preview"><p>确认删除这条历史记录及其 Trace？此操作不可撤销。</p><div className="button-row"><button className="danger-button" disabled={busy} onClick={() => void remove()}>确认删除</button><button onClick={() => setPendingDelete(false)}>取消</button></div></div>}
    </section><ResultView key={runId} base={`runs/${runId}`} result={result} runId={runId} /></>}
    {message && <p className="success-note" role="status">{message} {submittedJobId && <Link to={`/results/?job=${submittedJobId}`}>查看新任务</Link>}</p>}
    {uncertain && <section className="panel"><h2>本人最近任务</h2><p className="muted">空列表也不能证明提交失败，请勿自动重发。</p><button onClick={() => void lookupJobs()}>再次查询</button>{recentJobs && <div className="table-wrap"><table><thead><tr><th>接受时间</th><th>角色池</th><th>主抽数 / 轮数</th><th>状态</th><th>任务</th></tr></thead><tbody>{recentJobs.items.map((item) => <tr key={item.job_id}><td>{new Date(item.accepted_at).toLocaleString()}</td><td>{item.pool_name_snapshot}</td><td>{item.draws} / {item.trials}</td><td>{item.status}</td><td><Link to={`/results/?job=${item.job_id}`}>{item.job_id}</Link></td></tr>)}</tbody></table></div>}</section>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </div>;
}
