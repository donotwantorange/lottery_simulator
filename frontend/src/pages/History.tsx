import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { ExperimentParameters, JobDetail, JobSummary, Page, Pool, Rule, RunResult, RunSummary, SimulationPreview } from "../api/types";
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
    if (!result || !runId || busy || uncertain || !result.pool_id_snapshot) return;
    setBusy(true); setError(""); setMessage(""); setSubmittedJobId(""); setUncertain(false); setRecentJobs(null);
    try {
      const pool = await apiRequest<Pool>(`pools/${result.pool_id_snapshot}/`);
      const rule = await apiRequest<Rule>(`rules/${pool.rule_ref.id}/`);
      const zeroed: ExperimentParameters = {
        ...result.parameters, initial_main_draws: "0", initial_small_pity: {},
        initial_big_pity: { target_obtained: false, misses: "0" },
      };
      const preview = await apiRequest<SimulationPreview>("jobs/preview/", { method: "POST", body: JSON.stringify({
        pool_id: pool.id, expected_pool_revision: pool.revision,
        expected_rule_revision: rule.revision, parameters: zeroed, initial_context: null,
      }) });
      const contextChanged = JSON.stringify(preview.current_context) !== JSON.stringify(result.initial_context);
      const hasInitialState = result.parameters.initial_main_draws !== "0" ||
        Object.values(result.parameters.initial_small_pity).some((value) => value !== "0") ||
        result.parameters.initial_big_pity.target_obtained || result.parameters.initial_big_pity.misses !== "0";
      const differences = [
        pool.revision !== result.pool_revision_snapshot ? `角色池修订从 ${result.pool_revision_snapshot} 变为 ${pool.revision}` : null,
        rule.revision !== result.rule_revision_snapshot ? `规则修订从 ${result.rule_revision_snapshot} 变为 ${rule.revision}` : null,
        pool.rule_ref.id !== result.rule_id_snapshot ? "角色池已绑定到另一条规则" : null,
        contextChanged ? `初始上下文已变化：当前顺序 ${preview.current_context.rarity_ids.join(" → ")}，大保底目标 ${preview.current_context.big_target_id ?? "未启用"}` : null,
      ].filter(Boolean);
      const description = differences.length ? differences.join("；") : "当前角色池、规则与初始上下文和历史快照一致";
      let parameters = result.parameters;
      let resetInitial = false;
      if (contextChanged && hasInitialState) {
        if (!window.confirm("历史初始上下文已变化。确认后会将历史抽数、小保底和大保底状态全部重置为零；取消会停止重跑。")) return;
        resetInitial = true;
        parameters = { ...parameters, initial_main_draws: "0", initial_small_pity: {},
          initial_big_pity: { target_obtained: false, misses: "0" } };
      }
      let validated: SimulationPreview;
      try {
        validated = await apiRequest<SimulationPreview>("jobs/preview/", { method: "POST", body: JSON.stringify({
          pool_id: pool.id, expected_pool_revision: pool.revision, expected_rule_revision: rule.revision,
          parameters, initial_context: preview.current_context,
        }) });
      } catch (cause) {
        if (contextChanged && hasInitialState && !resetInitial) {
          setError(`历史初始条件不适用于当前上下文：${errorMessage(cause)}。重跑不会自动改变初始条件。`);
          return;
        }
        throw cause;
      }
      if (!window.confirm(`${description}。${resetInitial ? "初始条件已重置为零。" : "原初始条件已按当前规则验证。"}确认提交新任务？`)) return;
      const [latestPool, latestRule] = await Promise.all([
        apiRequest<Pool>(`pools/${pool.id}/`), apiRequest<Rule>(`rules/${rule.id}/`),
      ]);
      if (latestPool.revision !== pool.revision || latestRule.revision !== rule.revision ||
          latestPool.rule_ref.id !== rule.id) {
        setError("确认期间角色池或规则已变化，请重新查看差异后再试"); return;
      }
      try {
        const job = await apiRequest<JobDetail>("jobs/", { method: "POST",
          body: JSON.stringify({ pool_id: latestPool.id, expected_pool_revision: latestPool.revision,
            expected_rule_revision: latestRule.revision, parameters,
            initial_context: validated.current_context }) });
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
    {list && <div className="table-wrap"><table><thead><tr><th>创建时间</th><th>角色池</th><th>规则</th><th>主抽数</th><th>轮数</th><th>过程事件</th><th>操作</th></tr></thead><tbody>{list.items.map((item) => <tr key={item.id}><td>{new Date(item.created_at).toLocaleString()}</td><td>{item.pool_name_snapshot}</td><td>{item.rule_name}</td><td>{item.draws}</td><td>{item.trials}</td><td>{item.event_count}</td><td><button onClick={() => setParams({ run: item.id })}>查看</button></td></tr>)}</tbody></table></div>}
    <div className="button-row"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><button disabled={page >= pageCount} onClick={() => setPage(page + 1)}>下一页</button></div>
  </section>
    {runId && result && <><section className="panel"><div className="section-heading"><div><h2>历史快照</h2><p className="muted">{runId}</p></div></div>
      <p>角色池：{result.pool_snapshot.name} · 修订 {result.pool_revision_snapshot} · 作者 {result.pool_original_author_snapshot || "未署名"}</p>
      <p>规则：{result.rule_snapshot.name} · 修订 {result.rule_revision_snapshot} · 作者 {result.rule_original_author_snapshot || "未署名"}</p>
      <p className="muted">本次初始上下文：{result.initial_context.rarity_ids.map((id) => result.pool_snapshot.rarity_labels[id] ?? result.rule_snapshot.rarities.find((rarity) => rarity.id === id)?.name ?? id).join(" → ")}；大保底目标 {result.initial_context.big_target_id ?? "未启用"}</p>
      <div className="button-row"><button disabled={busy || uncertain} onClick={() => void rerun()}>按当前角色池重跑</button><button className="danger-button" disabled={busy} onClick={() => setPendingDelete(true)}>删除历史</button></div>
      {pendingDelete && <div className="import-preview"><p>确认删除这条历史记录及其 Trace？此操作不可撤销。</p><div className="button-row"><button className="danger-button" disabled={busy} onClick={() => void remove()}>确认删除</button><button onClick={() => setPendingDelete(false)}>取消</button></div></div>}
    </section><ResultView key={runId} base={`runs/${runId}`} result={result} runId={runId} /></>}
    {message && <p className="success-note" role="status">{message} {submittedJobId && <Link to={`/results/?job=${submittedJobId}`}>查看新任务</Link>}</p>}
    {uncertain && <section className="panel"><h2>本人最近任务</h2><p className="muted">空列表也不能证明提交失败，请勿自动重发。</p><button onClick={() => void lookupJobs()}>再次查询</button>{recentJobs && <div className="table-wrap"><table><thead><tr><th>接受时间</th><th>角色池</th><th>主抽数 / 轮数</th><th>状态</th><th>任务</th></tr></thead><tbody>{recentJobs.items.map((item) => <tr key={item.job_id}><td>{new Date(item.accepted_at).toLocaleString()}</td><td>{item.pool_name_snapshot}</td><td>{item.draws} / {item.trials}</td><td>{item.status}</td><td><Link to={`/results/?job=${item.job_id}`}>{item.job_id}</Link></td></tr>)}</tbody></table></div>}</section>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </div>;
}
