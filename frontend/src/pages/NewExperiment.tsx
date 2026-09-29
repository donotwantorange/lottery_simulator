import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { ExperimentConfig, ExperimentParameters, JobDetail, JobSummary, Page, Pool } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ExperimentForm, initialParameters, validateParameters } from "../components/ExperimentForm";
import { ImportDialog } from "../components/ImportDialog";

interface ExperimentDocument {
  format_version: 1;
  name: string;
  pool_ref: { id: string; name: string };
  parameters: ExperimentParameters;
}

interface PoolCandidate {
  id: string;
  name: string;
  revision: number;
  kind: "public" | "private";
  visibility: "public" | "hidden";
  owner_id: string | null;
  owner_name: string | null;
  original_author: string;
}

interface ImportPreview {
  document: ExperimentDocument;
  resolution: { status: "matched" | "confirm" | "select" | "unavailable"; candidates: PoolCandidate[] };
}

async function loadAll<T>(path: string, signal?: AbortSignal): Promise<T[]> {
  const first = await apiRequest<Page<T>>(`${path}?page=1&page_size=200`, {}, signal);
  const rest = await Promise.all(Array.from({ length: Math.ceil(first.total / 200) - 1 }, (_, index) =>
    apiRequest<Page<T>>(`${path}?page=${index + 2}&page_size=200`, {}, signal)));
  return [ ...first.items, ...rest.flatMap((page) => page.items) ];
}

function parametersFromConfig(parameters: ExperimentParameters): ExperimentParameters {
  return { ...parameters, seed: parameters.seed === null ? null : String(parameters.seed) };
}

export function NewExperiment() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedConfigId = searchParams.get("config");
  const { user, sessionGeneration } = useAuth();
  const [pools, setPools] = useState<Pool[]>([]);
  const [configs, setConfigs] = useState<ExperimentConfig[]>([]);
  const [configId, setConfigId] = useState("");
  const [activeConfig, setActiveConfig] = useState<ExperimentConfig | null>(null);
  const [name, setName] = useState("新实验");
  const [poolId, setPoolId] = useState("");
  const [simulationPoolId, setSimulationPoolId] = useState("");
  const [parameters, setParameters] = useState<ExperimentParameters>(initialParameters);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [importPoolId, setImportPoolId] = useState("");
  const [jobs, setJobs] = useState<Page<JobSummary> | null>(null);
  const [chosenJobId, setChosenJobId] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setPools([]); setConfigs([]); setActiveConfig(null); setConfigId(""); setPoolId(""); setSimulationPoolId("");
    void Promise.all([loadAll<Pool>("pools/", controller.signal), loadAll<ExperimentConfig>("experiment-configs/", controller.signal)])
      .then(([nextPools, nextConfigs]) => {
        if (controller.signal.aborted) return;
        setPools(nextPools); setConfigs(nextConfigs);
        const selected = requestedConfigId ? nextConfigs.find((config) => config.id === requestedConfigId) : null;
        if (selected) {
          setActiveConfig(selected); setConfigId(selected.id); setName(selected.name);
          setParameters(parametersFromConfig(selected.parameters));
          const selectedPoolId = selected.pool_ref.available ? selected.pool_ref.id ?? "" : "";
          setPoolId(selectedPoolId); setSimulationPoolId(selectedPoolId);
        }
      })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [user?.id, sessionGeneration, requestedConfigId]);

  const configurationPools = activeConfig && user?.role === "admin" && activeConfig.owner_id !== user.id && !activeConfig.owner_is_admin
    ? pools.filter((pool) => pool.kind === "public" || pool.visibility === "public" || pool.owner_id === activeConfig.owner_id)
    : pools;
  const managingOtherConfig = Boolean(activeConfig && user?.role === "admin" && activeConfig.owner_id !== user.id);
  const chosenPool = configurationPools.find((pool) => pool.id === poolId) ?? null;
  const chosenSimulationPool = pools.find((pool) => pool.id === (managingOtherConfig ? simulationPoolId : poolId)) ?? null;

  function chooseConfig(id: string) {
    setConfigId(id); setPreview(null); setUncertain(false); setJobs(null); setError(""); setMessage("");
    const config = configs.find((item) => item.id === id) ?? null;
    setActiveConfig(config);
    if (!config) {
      setName("新实验"); setPoolId(""); setSimulationPoolId(""); setParameters(initialParameters);
      return;
    }
    setName(config.name);
    setParameters(parametersFromConfig(config.parameters));
    const selectedPoolId = config.pool_ref.available ? config.pool_ref.id ?? "" : "";
    setPoolId(selectedPoolId); setSimulationPoolId(selectedPoolId);
  }

  async function refreshConfigs() {
    const next = await loadAll<ExperimentConfig>("experiment-configs/");
    setConfigs(next);
  }

  async function saveConfig() {
    const validation = validateParameters(parameters);
    if (validation) { setError(validation); return; }
    if (!name.trim() || !chosenPool || busy) { setError("请填写实验名称并选择可用角色池"); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const payload = { name, pool_ref: { id: chosenPool.id, name: chosenPool.name }, parameters,
        ...(activeConfig ? { expected_revision: activeConfig.revision } : {}) };
      const saved = await apiRequest<ExperimentConfig>(activeConfig ? `experiment-configs/${activeConfig.id}/` : "experiment-configs/",
        { method: activeConfig ? "PATCH" : "POST", body: JSON.stringify(payload) });
      setActiveConfig(saved); setConfigId(saved.id); setName(saved.name); setParameters(parametersFromConfig(saved.parameters));
      setMessage("实验配置已保存"); await refreshConfigs();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function exportConfig() {
    if (!activeConfig) return;
    // The API endpoint is an attachment: letting the browser download it preserves large JSON integers exactly.
    const link = document.createElement("a");
    link.href = `/api/v1/experiment-configs/${activeConfig.id}/export/?expected_revision=${activeConfig.revision}`;
    link.download = "experiment.json"; link.rel = "noreferrer"; link.click();
  }

  async function importConfig(raw: string) {
    setError(""); setMessage(""); setPreview(null); setImportPoolId(""); setActiveConfig(null); setConfigId("");
    const result = await apiRequest<ImportPreview>("experiment-configs/import/preview/", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: `{"document":${raw}}`,
    });
    setPreview(result);
    setName(result.document.name);
    const config = result.document.parameters;
    setParameters({
      draws: String(config.draws), trials: String(config.trials),
      initial_pity: String(config.initial_pity), initial_five_star_pity: String(config.initial_five_star_pity),
      seed: config.seed === null ? null : String(config.seed), trace: config.trace === true,
    });
    const candidate = result.resolution.status === "matched" ? result.resolution.candidates[0] : null;
    if (candidate) { setImportPoolId(candidate.id); setPoolId(candidate.id); }
    else setPoolId("");
  }

  async function confirmImport() {
    if (!preview || !importPoolId || busy) return;
    const pool = pools.find((item) => item.id === importPoolId);
    if (!pool) { setError("请选择当前有权使用的角色池"); return; }
    const validation = validateParameters(parameters);
    if (validation) { setError(validation); return; }
    setBusy(true); setError("");
    try {
      const document: ExperimentDocument = { ...preview.document,
        pool_ref: { id: preview.document.pool_ref.id, name: preview.document.pool_ref.name },
        parameters };
      const saved = await apiRequest<ExperimentConfig>("experiment-configs/import/confirm/", {
        method: "POST", body: JSON.stringify({ document, pool_id: pool.id, pool_revision: pool.revision }),
      });
      setPreview(null); setActiveConfig(saved); setConfigId(saved.id); setPoolId(pool.id);
      setParameters(parametersFromConfig(saved.parameters)); setName(saved.name); setMessage("实验配置已导入并保存");
      await refreshConfigs();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function lookupJobs() {
    setError("");
    try {
      const result = await apiRequest<Page<JobSummary>>("jobs/mine/?page=1&page_size=50");
      setJobs(result);
      if (result.items.length === 0) setMessage("暂未找到本人任务。提交可能仍在处理，可再次查询；请勿因空列表自动重发。 ");
    } catch (cause) { setError(errorMessage(cause)); }
  }

  async function submit() {
    const validation = validateParameters(parameters);
    if (validation) { setError(validation); return; }
    if (!chosenSimulationPool || busy) { setError("请先选择当前有权使用的角色池"); return; }
    setBusy(true); setError(""); setMessage(""); setUncertain(false); setJobs(null); setChosenJobId("");
    try {
      const job = await apiRequest<JobDetail>("jobs/", {
        method: "POST", body: JSON.stringify({ pool_id: chosenSimulationPool.id, expected_revision: chosenSimulationPool.revision, parameters }),
      });
      setMessage(`任务已接受（${job.job_id}）。可在实验结果页查看。`);
      navigate(`/results/?job=${job.job_id}`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status < 500) setError(errorMessage(cause));
      else {
        setUncertain(true);
        setMessage("提交结果未确认。系统没有自动重试；下面列出本人最近任务供人工按时间和参数核对。");
        await lookupJobs();
      }
    } finally { setBusy(false); }
  }

  async function queryAgain() { await lookupJobs(); }

  return <div className="page-stack">
    <section className="panel">
      <div className="section-heading"><div><h2>实验配置</h2><p className="muted">明确保存后才会写入配置；种子和数量按十进制文本保留精度。</p></div>
        <div className="button-row"><ImportDialog label="导入JSON" onImport={importConfig} />
          {activeConfig && <button onClick={() => void exportConfig()}>导出JSON</button>}</div></div>
      <div className="field-grid">
        <label>已保存配置<select value={configId} onChange={(event) => chooseConfig(event.target.value)}><option value="">新建配置</option>
          {configs.map((config) => <option key={config.id} value={config.id}>{config.name}{user?.role === "admin" && config.owner_id !== user.id ? `（${config.owner_name}）` : ""}</option>)}</select></label>
        <label>实验名称<input maxLength={255} value={name} onChange={(event) => setName(event.target.value)} /></label>
      </div>
      <div className="button-row"><button className="primary-button" disabled={busy} onClick={() => void saveConfig()}>{activeConfig ? "保存修改" : "保存配置"}</button>
        {activeConfig && <button disabled={busy} onClick={() => { setActiveConfig(null); setConfigId(""); setName(`${name}副本`); setMessage("另存为新配置；点击保存配置后才会创建"); }}>另存为</button>}</div>
      {preview && <div className="import-preview"><h3>导入池匹配</h3><p>{preview.resolution.status === "matched" ? `已按池ID匹配：${preview.resolution.candidates[0]?.name ?? ""}` : preview.resolution.status === "confirm" ? "按池名称找到一个候选，请确认后保存。" : preview.resolution.status === "select" ? "找到多个同名候选，请选择一个。" : "没有可直接匹配的池，请手动选择当前可用池。"}</p>
        <label>角色池<select value={importPoolId} onChange={(event) => { setImportPoolId(event.target.value); setPoolId(event.target.value); }}><option value="">选择有权使用的池</option>
          {preview.resolution.candidates.map((pool) => <option key={`candidate-${pool.id}`} value={pool.id}>{pool.name} · {pool.kind === "public" ? "公共池" : pool.owner_name ?? "私有池"}</option>)}
          {pools.filter((pool) => !preview.resolution.candidates.some((candidate) => candidate.id === pool.id)).map((pool) => <option key={pool.id} value={pool.id}>{pool.name} · {pool.kind === "public" ? "公共池" : pool.owner_name ?? "私有池"}</option>)}
        </select></label><button disabled={busy || !importPoolId} onClick={() => void confirmImport()}>确认导入并保存</button>
      </div>}
    </section>

    <section className="panel">
      <div className="section-heading"><div><h2>本次模拟</h2><p className="muted">实验只选择角色池，不在实验中覆盖规则或池配置。</p></div></div>
      <div className="field-grid">
        <label>{managingOtherConfig ? "配置绑定角色池" : "角色池"}<select value={poolId} onChange={(event) => { setPoolId(event.target.value); if (managingOtherConfig) setSimulationPoolId(event.target.value); }}><option value="">选择配置可用池</option>{configurationPools.map((pool) => <option key={pool.id} value={pool.id}>{pool.name} · {pool.kind === "public" ? "公共池" : pool.owner_id === user?.id ? "我的私有池" : pool.owner_name ?? "私有池"}</option>)}</select></label>
        {managingOtherConfig && <label>本次模拟角色池<select value={simulationPoolId} onChange={(event) => setSimulationPoolId(event.target.value)}><option value="">选择当前有权使用的池</option>{pools.map((pool) => <option key={pool.id} value={pool.id}>{pool.name} · {pool.kind === "public" ? "公共池" : pool.owner_id === user?.id ? "我的私有池" : pool.owner_name ?? "私有池"}</option>)}</select></label>}
        <div className="readonly-summary"><span>绑定规则</span><strong>{chosenSimulationPool?.rule_name ?? "—"}</strong><span>最初作者</span><strong>{chosenSimulationPool?.original_author || "—"}</strong><span>修订版本</span><strong>{chosenSimulationPool?.revision ?? "—"}</strong></div>
      </div>
      {managingOtherConfig && <p className="muted">本次模拟池只用于管理员本人新建任务，不会修改所有者的实验配置。</p>}
      {chosenSimulationPool && <p className="muted">角色摘要：{chosenSimulationPool.pool_config.six_star_characters.map((character) => character.name).join("、") || "未配置六星角色"}；四星 {chosenSimulationPool.pool_config.four_star_characters.length} 人，五星 {chosenSimulationPool.pool_config.five_star_characters.length} 人，奖励 {chosenSimulationPool.pool_config.rewards.length} 项。<Link to="/pools/">前往角色池管理</Link></p>}
      <ExperimentForm value={parameters} onChange={setParameters} />
      <button className="primary-button" disabled={busy} onClick={() => void submit()}>{busy ? "正在提交…" : "开始模拟"}</button>
    </section>

    {uncertain && <section className="panel"><h2>提交结果未确认</h2><p className="muted">请按接受时间、池名称及参数人工核对。此列表可能包含其他标签页提交的任务，不能自动认定某项就是本次任务。</p>
      <button disabled={busy} onClick={() => void queryAgain()}>再次查询本人任务</button>
      {jobs && <><p>{jobs.total === 0 ? "本人任务列表为空。" : `最近任务共 ${jobs.total} 项（显示 ${jobs.items.length} 项）。`}</p>
        <div className="table-wrap"><table><thead><tr><th>接受时间</th><th>状态</th><th>角色池</th><th>主抽数 / 轮数</th><th>Trace</th><th>任务ID</th></tr></thead><tbody>
          {jobs.items.map((job) => <tr key={job.job_id} aria-selected={chosenJobId === job.job_id} onClick={() => setChosenJobId(job.job_id)}><td>{new Date(job.accepted_at).toLocaleString()}</td><td>{job.status} · {job.phase}</td><td>{job.pool_name_snapshot}</td><td>{job.draws} / {job.trials}</td><td>{job.trace ? "是" : "否"}</td><td><code>{job.job_id}</code></td></tr>)}
        </tbody></table></div>{chosenJobId && <p role="status">人工核对项：{chosenJobId}。尚未自动判定为本次提交。</p>}</>}
    </section>}
    {error && <p className="form-error" role="alert">{error}{error.includes("修订冲突") || error.includes("已变化") ? " 请重新加载对象并核对后再保存。" : ""}</p>}
    {message && <p className="success-note" role="status">{message}</p>}
  </div>;
}
