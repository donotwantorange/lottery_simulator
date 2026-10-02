import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { ExperimentConfig, ExperimentParameters, InitialContext, JobDetail, JobSummary, Page, Pool, Rule, SimulationPreview as PreviewResult } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ExperimentForm, initialParameters, validateParameters } from "../components/ExperimentForm";
import { InitialConditions, currentInitialContext } from "../components/InitialConditions";
import { SimulationPreview } from "../components/SimulationPreview";
import { ImportDialog } from "../components/ImportDialog";

interface ExperimentFile { format_version: 2; name: string; pool_ref: { id: string; name: string }; parameters: ExperimentParameters; initial_context: InitialContext | null; }
interface ImportResult { document: ExperimentFile; resolution: { status: string; candidates: Array<{id:string;name:string;revision:number;rule:{revision:number}}> }; }

async function loadAll<T>(path: string, signal?: AbortSignal): Promise<T[]> {
  const first = await apiRequest<Page<T>>(`${path}?page=1&page_size=200`, {}, signal);
  const rest = await Promise.all(Array.from({ length: Math.ceil(first.total / 200) - 1 }, (_, index) => apiRequest<Page<T>>(`${path}?page=${index + 2}&page_size=200`, {}, signal)));
  return [...first.items, ...rest.flatMap((page) => page.items)];
}

function nonzero(parameters: ExperimentParameters) {
  return parameters.initial_main_draws !== "0" || Object.values(parameters.initial_small_pity).some((n) => n !== "0")
    || parameters.initial_big_pity.target_obtained || parameters.initial_big_pity.misses !== "0";
}

function sameContext(a: InitialContext | null, b: InitialContext) {
  return Boolean(a && a.rule_id === b.rule_id && a.big_mode === b.big_mode && a.big_target_id === b.big_target_id
    && a.rarity_ids.length === b.rarity_ids.length && a.rarity_ids.every((id, index) => id === b.rarity_ids[index]));
}

export function NewExperiment() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedConfig = searchParams.get("config");
  const { user, sessionGeneration } = useAuth();
  const [pools, setPools] = useState<Pool[]>([]);
  const [configs, setConfigs] = useState<ExperimentConfig[]>([]);
  const [poolId, setPoolId] = useState("");
  const [simulationPoolId, setSimulationPoolId] = useState("");
  const [rule, setRule] = useState<Rule | null>(null);
  const [configRule, setConfigRule] = useState<Rule | null>(null);
  const [config, setConfig] = useState<ExperimentConfig | null>(null);
  const [configId, setConfigId] = useState("");
  const [name, setName] = useState("新实验");
  const [parameters, setParameters] = useState<ExperimentParameters>(initialParameters);
  const [simulationContext, setSimulationContext] = useState<InitialContext | null>(null);
  const [configContextConfirmed, setConfigContextConfirmed] = useState<InitialContext | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importPoolId, setImportPoolId] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [jobs, setJobs] = useState<Page<JobSummary> | null>(null);
  const [chosenJobId, setChosenJobId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setPools([]); setConfigs([]); setConfig(null); setConfigId(""); setPoolId(""); setSimulationPoolId(""); setRule(null); setConfigRule(null);
    void Promise.all([loadAll<Pool>("pools/", controller.signal), loadAll<ExperimentConfig>("experiment-configs/", controller.signal)])
      .then(([availablePools, savedConfigs]) => {
        if (controller.signal.aborted) return;
        setPools(availablePools); setConfigs(savedConfigs);
        const selected = requestedConfig ? savedConfigs.find((item) => item.id === requestedConfig) : null;
        if (selected) { setConfig(selected); setConfigId(selected.id); setName(selected.name); setParameters(selected.parameters); setSimulationContext(selected.initial_context); setConfigContextConfirmed(selected.initial_context); const selectedPool = selected.pool_ref.available ? selected.pool_ref.id ?? "" : ""; setPoolId(selectedPool); setSimulationPoolId(selectedPool); }
      }).catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [user?.id, sessionGeneration, requestedConfig]);

  const configPools = config && user?.role === "admin" && config.owner_id !== user.id && !config.owner_is_admin
    ? pools.filter((pool) => pool.kind === "public" || pool.visibility === "public" || pool.owner_id === config.owner_id) : pools;
  const managingOtherConfig = Boolean(config && user?.role === "admin" && config.owner_id !== user.id);
  const chosenConfigPool = configPools.find((pool) => pool.id === poolId) ?? null;
  const chosenSimulationPool = pools.find((pool) => pool.id === (managingOtherConfig ? simulationPoolId : poolId)) ?? null;
  const currentContext = rule && chosenSimulationPool ? currentInitialContext(rule.document, chosenSimulationPool.document) : null;
  const configContext = configRule && chosenConfigPool ? currentInitialContext(configRule.document, chosenConfigPool.document) : null;
  const previewPayload = rule && chosenSimulationPool && currentContext ? {
    pool_id: chosenSimulationPool.id, expected_pool_revision: chosenSimulationPool.revision,
    expected_rule_revision: chosenSimulationPool.rule_ref.revision,
    parameters, initial_context: simulationContext ?? (nonzero(parameters) ? null : currentContext),
  } : null;
  const currentPreviewKey = previewPayload ? JSON.stringify(previewPayload) : "";
  const previewReady = Boolean(preview && previewKey === currentPreviewKey);

  useEffect(() => {
    if (!chosenSimulationPool) { setRule(null); return; }
    let live = true;
    setRule(null); setPreview(null); setPreviewKey("");
    void apiRequest<Rule>(`rules/${chosenSimulationPool.rule_ref.id}/`).then((loaded) => { if (live) setRule(loaded); })
      .catch((cause) => { if (live) setError(errorMessage(cause)); });
    return () => { live = false; };
  }, [chosenSimulationPool?.id, chosenSimulationPool?.rule_ref.id, chosenSimulationPool?.rule_ref.revision]);

  useEffect(() => {
    if (!chosenConfigPool || chosenConfigPool.id === chosenSimulationPool?.id) { setConfigRule(rule); return; }
    let live = true;
    setConfigRule(null);
    void apiRequest<Rule>(`rules/${chosenConfigPool.rule_ref.id}/`).then((loaded) => { if (live) setConfigRule(loaded); })
      .catch((cause) => { if (live) setError(errorMessage(cause)); });
    return () => { live = false; };
  }, [chosenConfigPool?.id, chosenConfigPool?.rule_ref.id, chosenConfigPool?.rule_ref.revision, chosenSimulationPool?.id, rule]);

  function updateParameters(next: ExperimentParameters) { setParameters(next); setPreview(null); setPreviewKey(""); }
  function chooseConfig(id: string) {
    setConfigId(id); setError(""); setMessage(""); setImportResult(null); setPreview(null); setSimulationContext(null); setConfigContextConfirmed(null);
    const selected = configs.find((item) => item.id === id) ?? null;
    setConfig(selected);
    if (!selected) { setName("新实验"); setPoolId(""); setSimulationPoolId(""); updateParameters(initialParameters); return; }
    setName(selected.name); updateParameters(selected.parameters); setSimulationContext(selected.initial_context); setConfigContextConfirmed(selected.initial_context);
    const idForPool = selected.pool_ref.available ? selected.pool_ref.id ?? "" : "";
    setPoolId(idForPool); setSimulationPoolId(idForPool);
  }
  async function refreshConfigs() { setConfigs(await loadAll<ExperimentConfig>("experiment-configs/")); }
  async function saveConfig() {
    const validation = validateParameters(parameters);
    if (validation) { setError(validation); return; }
    if (!name.trim() || !chosenConfigPool || !configRule || busy) { setError("请填写实验名称并选择配置可用的角色池"); return; }
    const context = configContext!;
    if ((nonzero(parameters) || configContextConfirmed !== null) && !sameContext(configContextConfirmed, context)) { setError("配置绑定池的初始条件上下文未确认，请先确认当前目标和规则上下文"); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const payload = { name, pool_ref: { id: chosenConfigPool.id, name: chosenConfigPool.name }, parameters,
        initial_context: configContextConfirmed ?? (nonzero(parameters) ? null : context),
        expected_pool_revision: chosenConfigPool.revision, expected_rule_revision: chosenConfigPool.rule_ref.revision };
      const saved = await apiRequest<ExperimentConfig>(config ? `experiment-configs/${config.id}/` : "experiment-configs/",
        { method: config ? "PATCH" : "POST", body: JSON.stringify(config ? { ...payload, expected_revision: config.revision } : payload) });
      setConfig(saved); setConfigId(saved.id); setName(saved.name); setParameters(saved.parameters); setSimulationContext(saved.initial_context); setConfigContextConfirmed(saved.initial_context);
      setMessage("实验配置已保存；没有开始模拟"); await refreshConfigs();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  async function importConfig(raw: string) {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await apiRequest<ImportResult>("experiment-configs/import/preview/", { method: "POST", body: `{"document":${raw}}` });
      setImportResult(result); setConfig(null); setConfigId(""); setName(result.document.name); updateParameters(result.document.parameters);
      setSimulationContext(result.document.initial_context); setConfigContextConfirmed(result.document.initial_context);
      const match = result.resolution.status === "matched" || result.resolution.status === "confirm" ? result.resolution.candidates[0] : null;
      if (match) { setImportPoolId(match.id); setPoolId(match.id); }
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  async function confirmImport() {
    const pool = pools.find((item) => item.id === importPoolId);
    if (!importResult || !pool || busy) return;
    setBusy(true); setError("");
    try {
      const saved = await apiRequest<ExperimentConfig>("experiment-configs/import/confirm/", { method: "POST", body: JSON.stringify({
        document: { ...importResult.document, parameters, initial_context: configContextConfirmed }, pool_id: pool.id,
        pool_revision: pool.revision, rule_revision: pool.rule_ref.revision,
      }) });
      setImportResult(null); setConfig(saved); setConfigId(saved.id); setName(saved.name); setParameters(saved.parameters); setSimulationContext(saved.initial_context); setConfigContextConfirmed(saved.initial_context);
      setMessage("配置已导入并保存"); await refreshConfigs();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  async function lookupJobs() {
    try { setJobs(await apiRequest<Page<JobSummary>>("jobs/mine/?page=1&page_size=50")); }
    catch (cause) { setError(errorMessage(cause)); }
  }
  async function start() {
    const validation = validateParameters(parameters);
    if (validation) { setError(validation); return; }
    if (!previewPayload || !rule || busy || uncertain) { setError(uncertain ? "请先查询并人工核对上次提交；核对后才能显式开始新任务。" : "请先选择当前有权使用且规则有效的角色池"); return; }
    if ((nonzero(parameters) || simulationContext !== null) && !sameContext(simulationContext, currentContext!)) {
      setError("初始条件的规则、稀有度顺序或目标已变化，请确认使用当前上下文后再预览"); return;
    }
    setBusy(true); setError(""); setMessage(""); setJobs(null); setChosenJobId("");
    const requestKey = currentPreviewKey;
    try {
      if (!previewReady) {
        const result = await apiRequest<PreviewResult>("jobs/preview/", { method: "POST", body: JSON.stringify(previewPayload) });
        setPreview(result); setPreviewKey(requestKey); setMessage("预览已更新。核对计数后，再次点击“开始模拟”接受任务。"); setBusy(false); return;
      }
    } catch (cause) { setError(errorMessage(cause)); setPreview(null); setPreviewKey(""); setBusy(false); return; }
    try {
      const job = await apiRequest<JobDetail>("jobs/", { method: "POST", body: JSON.stringify(previewPayload) });
      setMessage(`任务已接受（${job.job_id}）。可在实验结果页查看。`); navigate(`/results/?job=${job.job_id}`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status < 500) setError(errorMessage(cause));
      else { setUncertain(true); setMessage("提交结果未确认。系统没有自动重试；请查询本人任务并按时间和参数人工核对。"); await lookupJobs(); }
    } finally { setBusy(false); }
  }

  return <div className="page-stack">
    <section className="panel"><div className="section-heading"><div><h2>实验配置</h2><p className="muted">明确保存后才写入配置；保存配置不会开始模拟。</p></div><ImportDialog label="导入JSON" onImport={importConfig} disabled={busy} />
      {config && <a className="secondary-button" href={`/api/v1/experiment-configs/${config.id}/export/?expected_revision=${config.revision}`} download="experiment.json">导出JSON</a>}</div>
      <div className="field-grid"><label>已保存配置<select disabled={busy} value={configId} onChange={(event) => chooseConfig(event.target.value)}><option value="">新建配置</option>{configs.map((item) => <option key={item.id} value={item.id}>{item.name}{item.owner_id !== user?.id ? `（${item.owner_name}）` : ""}</option>)}</select></label><label>实验名称<input disabled={busy} value={name} maxLength={255} onChange={(event) => setName(event.target.value)} /></label></div>
      <div className="button-row"><button className="primary-button" disabled={busy || !chosenConfigPool || !configRule} onClick={() => void saveConfig()}>{config ? "保存修改" : "保存配置"}</button>{config && <button disabled={busy} onClick={() => { setConfig(null); setConfigId(""); setName(`${name}副本`); }}>另存为</button>}</div>
      {importResult && <div className="import-preview"><h3>导入配置</h3><p>{importResult.resolution.status === "matched" ? "角色池ID匹配。" : "请从当前可用池中选择配置使用的角色池。"}</p><label>角色池<select value={importPoolId} onChange={(event) => setImportPoolId(event.target.value)}><option value="">选择角色池</option>{pools.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button disabled={busy || !importPoolId} onClick={() => void confirmImport()}>确认导入并保存</button></div>}
    </section>
    <section className="panel"><div className="section-heading"><div><h2>本次模拟</h2><p className="muted">这里决定运行参数与初始状态；共享规则在角色池中管理。</p></div></div>
      <div className="field-grid"><label>{managingOtherConfig ? "配置绑定角色池" : "角色池"}<select disabled={busy || uncertain} value={poolId} onChange={(event) => { setPoolId(event.target.value); if (managingOtherConfig) setSimulationPoolId(event.target.value); setConfigContextConfirmed(null); setSimulationContext(null); setPreview(null); }}><option value="">选择池</option>{configPools.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {managingOtherConfig && <label>本次模拟角色池<select disabled={busy || uncertain} value={simulationPoolId} onChange={(event) => { setSimulationPoolId(event.target.value); setSimulationContext(null); setPreview(null); }}><option value="">选择当前有权使用的池</option>{pools.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.kind === "public" ? "公共池" : item.owner_name ?? "私有池"}</option>)}</select></label>}
        <div className="readonly-summary"><span>绑定规则</span><strong>{chosenSimulationPool?.rule_ref.name ?? "—"}</strong><span>规则 / 池修订</span><strong>{chosenSimulationPool ? `${chosenSimulationPool.rule_ref.revision} / ${chosenSimulationPool.revision}` : "—"}</strong></div></div>
      {managingOtherConfig && <p className="muted">管理员代管的配置仍按所有者筛选绑定池；本次模拟池只用于管理员本人新建任务。</p>}
      {chosenSimulationPool && <p className="muted">角色名单与机制目标来自当前池。<Link to="/pools/">前往角色池管理</Link></p>}
      <fieldset disabled={busy || uncertain} className="plain-fieldset">
        <ExperimentForm value={parameters} onChange={updateParameters} />
        {rule && chosenSimulationPool && <InitialConditions rule={rule.document} pool={chosenSimulationPool.document} value={parameters} savedContext={simulationContext} onChange={updateParameters} onConfirm={(context) => { setSimulationContext(context); if (!managingOtherConfig || chosenConfigPool?.id === chosenSimulationPool.id) setConfigContextConfirmed(context); setPreview(null); setPreviewKey(""); setError(""); }} />}
      </fieldset>
      {configContext && (nonzero(parameters) || configContextConfirmed !== null) && !sameContext(configContextConfirmed, configContext) && <p className="muted">配置绑定池的规则上下文与已保存上下文不同。保存配置前请单独确认配置池上下文。<button type="button" disabled={busy} onClick={() => { setConfigContextConfirmed(configContext); setPreview(null); setPreviewKey(""); }}>确认配置池上下文</button></p>}
      <SimulationPreview value={previewReady ? preview : null} />
      <button className="primary-button" disabled={busy || !rule || uncertain} onClick={() => void start()}>{busy ? "正在处理…" : previewReady ? "开始模拟" : "开始模拟"}</button>
    </section>
    {uncertain && <section className="panel"><h2>提交结果未确认</h2><p className="muted">请按接受时间、池名称和参数人工核对。系统不会自动选择任务，也不会重发上次请求。</p><button disabled={busy} onClick={() => void lookupJobs()}>查询本人任务</button>{jobs && <div className="table-wrap"><table><thead><tr><th>接受时间</th><th>状态</th><th>角色池</th><th>主抽数 / 轮数</th><th>任务ID</th></tr></thead><tbody>{jobs.items.map((job) => <tr key={job.job_id} aria-selected={chosenJobId === job.job_id} onClick={() => setChosenJobId(job.job_id)}><td>{new Date(job.accepted_at).toLocaleString()}</td><td>{job.status}</td><td>{job.pool_name_snapshot}</td><td>{job.draws} / {job.trials}</td><td>{job.job_id}</td></tr>)}</tbody></table></div>}<button disabled={busy} onClick={() => { setUncertain(false); setJobs(null); setChosenJobId(""); setPreview(null); setPreviewKey(""); setMessage("已人工核对。再次点击“开始模拟”将创建新任务。"); }}>已核对，开始新任务</button></section>}
    {error && <p className="form-error" role="alert">{error}</p>}{message && <p className="success-note" role="status">{message}</p>}
  </div>;
}
