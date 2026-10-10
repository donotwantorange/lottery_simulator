import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { ExperimentConfig, ExperimentParameters, InitialContext, JobDetail, JobSummary, Page, Pool, Rule, SimulationPreview as PreviewResult } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ExperimentForm, initialParameters, validateParameters } from "../components/ExperimentForm";
import { InitialConditions, currentInitialContext } from "../components/InitialConditions";
import { SimulationPreview } from "../components/SimulationPreview";
import { ImportDialog } from "../components/ImportDialog";
import { apiFieldIssues, FormFeedback, type FieldIssue } from "../components/FormFeedback";
import { confirmDiscard, useEditorDraft, useUnsavedNavigation } from "../hooks/useEditorDraft";
import { formatCount, jobStatusLabel } from "../formatters";

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

function unresolvedInitialState(parameters: ExperimentParameters, rule: Rule): boolean {
  const known = new Set(rule.document.rarities.map((rarity) => rarity.id));
  const tracked = new Set(rule.document.rarities.filter((rarity) => rarity.soft_enabled || rarity.hard_enabled).map((rarity) => rarity.id));
  return Object.entries(parameters.initial_small_pity).some(([id, count]) => !known.has(id) || (!tracked.has(id) && count !== "0"))
    || (!rule.document.big_pity.enabled && (parameters.initial_big_pity.target_obtained || parameters.initial_big_pity.misses !== "0"))
    || (rule.document.big_pity.enabled && rule.document.big_pity.after_obtain === "reset_after_obtain" && parameters.initial_big_pity.target_obtained)
    || (rule.document.big_pity.enabled && rule.document.big_pity.after_obtain === "disable_after_obtain" && parameters.initial_big_pity.misses !== "0");
}

function experimentFieldIssues(fields: Record<string, string>, pool: Pool | null, rule: Rule | null): FieldIssue[] {
  const labels: Record<string, [string, string]> = {
    name: ["实验名称", "experiment-name"], pool_id: ["角色池", "experiment-pool"],
    pool_ref: ["角色池", "experiment-pool"], parameters: ["实验参数", "experiment-form-feedback"],
    draws: ["每轮主池抽数", "experiment-draws"], trials: ["实验轮数", "experiment-trials"],
    seed: ["随机种子", "experiment-seed"], initial_main_draws: ["历史累计主抽数", "experiment-initial-main-draws"],
    target_obtained: ["历史已获得大保底目标", "experiment-big-obtained"], misses: ["大保底连续未命中数", "experiment-big-misses"],
    initial_context: ["初始条件与当前规则", "experiment-initial-details"],
  };
  return Object.entries(fields).map(([path, message]) => {
    const parts = path.split(".");
    const key = parts.at(-1) ?? path;
    const smallIndex = parts.indexOf("initial_small_pity");
    const smallId = smallIndex >= 0 ? parts[smallIndex + 1] : null;
    const initial = path.includes("initial_") || path.includes("initial_context");
    const rarity = smallId ? rule?.document.rarities.find((item) => item.id === smallId) : null;
    const rarityName = smallId ? (pool?.document.rarity_labels[smallId] || rarity?.name) : null;
    const [label, id] = smallId ? [rarityName ? `${rarityName}小保底初始计数` : `已移除档位的初始计数（ID：${smallId}）`, rarity && (rarity.soft_enabled || rarity.hard_enabled) ? `experiment-small-${smallId}` : "experiment-initial-details"]
      : path.startsWith("pool_ref.") ? labels.pool_ref
      : labels[key] ?? [initial ? "初始条件" : `配置字段 ${path}`, initial ? "experiment-initial-details" : "experiment-form-feedback"];
    return { id, label, message, reveal: initial ? () => { const details = document.getElementById("experiment-initial-details") as HTMLDetailsElement | null; if (details) details.open = true; } : undefined };
  });
}

export function NewExperiment() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedConfig = searchParams.get("config");
  const { user, sessionGeneration } = useAuth();
  const sessionIdentity = `${user?.id ?? ""}:${sessionGeneration}`;
  const currentSessionIdentityRef = useRef(sessionIdentity);
  currentSessionIdentityRef.current = sessionIdentity;
  const isCurrentSession = (identity: string) => identity === currentSessionIdentityRef.current;
  const [pools, setPools] = useState<Pool[]>([]);
  const [configs, setConfigs] = useState<ExperimentConfig[]>([]);
  const { value: draft, setValue: setDraft, reset: resetDraft, markSaved, dirty } = useEditorDraft({
    poolId: "", simulationPoolId: "", name: "新实验", parameters: initialParameters,
    simulationContext: null as InitialContext | null, configContextConfirmed: null as InitialContext | null,
  });
  const { poolId, simulationPoolId, name, parameters, simulationContext, configContextConfirmed } = draft;
  const setPoolId = (next: string) => setDraft((old) => ({ ...old, poolId: next }));
  const setSimulationPoolId = (next: string) => setDraft((old) => ({ ...old, simulationPoolId: next }));
  const setName = (next: string) => setDraft((old) => ({ ...old, name: next }));
  const setParameters = (next: ExperimentParameters) => setDraft((old) => ({ ...old, parameters: next }));
  const setSimulationContext = (next: InitialContext | null) => setDraft((old) => ({ ...old, simulationContext: next }));
  const setConfigContextConfirmed = (next: InitialContext | null) => setDraft((old) => ({ ...old, configContextConfirmed: next }));
  const [navigatingAfterSubmit, setNavigatingAfterSubmit] = useState(false);
  useUnsavedNavigation(dirty && !navigatingAfterSubmit && Boolean(user));
  const [rule, setRule] = useState<Rule | null>(null);
  const [configRule, setConfigRule] = useState<Rule | null>(null);
  const [config, setConfig] = useState<ExperimentConfig | null>(null);
  const [configId, setConfigId] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [previewInvalidated, setPreviewInvalidated] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importPoolId, setImportPoolId] = useState("");
  const [busy, setBusy] = useState(false);
  const [runStage, setRunStage] = useState<"preview" | "submit" | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [configUncertain, setConfigUncertain] = useState(false);
  const [configChecked, setConfigChecked] = useState(false);
  const [sourceWarning, setSourceWarning] = useState<"conflict" | "permission" | null>(null);
  const [jobs, setJobs] = useState<Page<JobSummary> | null>(null);
  const [chosenJobId, setChosenJobId] = useState("");
  const [error, setError] = useState("");
  const [serverFields, setServerFields] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const importEpoch = useRef(0);
  const runEpoch = useRef(0);
  const currentPreviewKeyRef = useRef("");
  const previousPreviewInputRef = useRef("");

  useEffect(() => {
    const controller = new AbortController();
    importEpoch.current += 1;
    runEpoch.current += 1;
    setPools([]); setConfigs([]); setConfig(null); setConfigId(""); resetDraft({ poolId: "", simulationPoolId: "", name: "新实验", parameters: initialParameters, simulationContext: null, configContextConfirmed: null });
    setRule(null); setConfigRule(null); setPreview(null); setPreviewKey(""); setPreviewInvalidated(false); setImportResult(null); setUncertain(false); setConfigUncertain(false); setConfigChecked(false); setSourceWarning(null); setJobs(null); setError(""); setServerFields({}); setMessage(""); setBusy(false); setRunStage(null);
    void Promise.all([loadAll<Pool>("pools/", controller.signal), loadAll<ExperimentConfig>("experiment-configs/", controller.signal)])
      .then(([availablePools, savedConfigs]) => {
        if (controller.signal.aborted) return;
        setPools(availablePools); setConfigs(savedConfigs);
        const selected = requestedConfig ? savedConfigs.find((item) => item.id === requestedConfig) : null;
        if (selected) { setConfig(selected); setConfigId(selected.id); const selectedPool = selected.pool_ref.available ? selected.pool_ref.id ?? "" : "";
          resetDraft({ name: selected.name, parameters: selected.parameters, poolId: selectedPool, simulationPoolId: selectedPool, simulationContext: selected.initial_context, configContextConfirmed: selected.initial_context }); }
      }).catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [user?.id, sessionGeneration, requestedConfig, resetDraft]);

  const configPools = config && user?.role === "admin" && config.owner_id !== user.id && !config.owner_is_admin
    ? pools.filter((pool) => pool.kind === "public" || pool.visibility === "public" || pool.owner_id === config.owner_id) : pools;
  const managingOtherConfig = Boolean(config && user?.role === "admin" && config.owner_id !== user.id);
  const chosenConfigPool = configPools.find((pool) => pool.id === poolId) ?? null;
  const chosenSimulationPool = pools.find((pool) => pool.id === (managingOtherConfig ? simulationPoolId : poolId)) ?? null;
  const activeRule = rule && chosenSimulationPool && rule.id === chosenSimulationPool.rule_ref.id && rule.revision === chosenSimulationPool.rule_ref.revision ? rule : null;
  const activeConfigRule = configRule && chosenConfigPool && configRule.id === chosenConfigPool.rule_ref.id && configRule.revision === chosenConfigPool.rule_ref.revision ? configRule : null;
  const currentContext = activeRule && chosenSimulationPool ? currentInitialContext(activeRule.document, chosenSimulationPool.document) : null;
  const configContext = activeConfigRule && chosenConfigPool ? currentInitialContext(activeConfigRule.document, chosenConfigPool.document) : null;
  const configWriteOwnerId = config?.owner_id ?? user?.id;
  const previewPayload = activeRule && chosenSimulationPool && currentContext ? {
    pool_id: chosenSimulationPool.id, expected_pool_revision: chosenSimulationPool.revision,
    expected_rule_revision: chosenSimulationPool.rule_ref.revision,
    parameters, initial_context: simulationContext ?? (nonzero(parameters) ? null : currentContext),
  } : null;
  const currentPreviewKey = previewPayload ? JSON.stringify(previewPayload) : "";
  currentPreviewKeyRef.current = currentPreviewKey;
  const previewReady = Boolean(preview && !previewInvalidated && previewKey === currentPreviewKey);

  useLayoutEffect(() => {
    if (previousPreviewInputRef.current === currentPreviewKey) return;
    previousPreviewInputRef.current = currentPreviewKey;
    runEpoch.current += 1;
    if (preview || previewKey) setPreviewInvalidated(true);
    setPreview(null);
    setPreviewKey("");
  }, [currentPreviewKey]);

  useEffect(() => {
    if (!chosenSimulationPool) { setRule(null); return; }
    let live = true;
    setRule(null);
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

  function updateParameters(next: ExperimentParameters) { setParameters(next); setError(""); setServerFields({}); }
  function chooseConfig(id: string) {
    if (!confirmDiscard(dirty)) return;
    importEpoch.current += 1;
    runEpoch.current += 1;
    setConfigId(id); setError(""); setServerFields({}); setSourceWarning(null); setMessage(""); setImportResult(null); setPreview(null); setPreviewKey("");
    const selected = configs.find((item) => item.id === id) ?? null;
    setConfig(selected);
    if (!selected) { resetDraft({ name: "新实验", parameters: initialParameters, poolId: "", simulationPoolId: "", simulationContext: null, configContextConfirmed: null }); return; }
    const idForPool = selected.pool_ref.available ? selected.pool_ref.id ?? "" : "";
    resetDraft({ name: selected.name, parameters: selected.parameters, poolId: idForPool, simulationPoolId: idForPool,
      simulationContext: selected.initial_context, configContextConfirmed: selected.initial_context });
  }
  async function refreshConfigs() {
    const identity = sessionIdentity;
    const latest = await loadAll<ExperimentConfig>("experiment-configs/");
    if (isCurrentSession(identity)) setConfigs(latest);
  }
  async function refreshSources() {
    const identity = sessionIdentity;
    setBusy(true); setError("");
    try {
      const [availablePools, savedConfigs] = await Promise.all([loadAll<Pool>("pools/"), loadAll<ExperimentConfig>("experiment-configs/")]);
      if (!isCurrentSession(identity)) return;
      setPools(availablePools); setConfigs(savedConfigs); setPreview(null); setPreviewKey("");
      if (config && !savedConfigs.some((item) => item.id === config.id)) {
        setConfig(null); setConfigId(""); resetDraft({ poolId: "", simulationPoolId: "", name: "新实验", parameters: initialParameters, simulationContext: null, configContextConfirmed: null });
        setError("原配置已不可查看；页面已清除其详情。请选择仍可访问的配置或新建。");
      } else if (poolId && !availablePools.some((item) => item.id === poolId)) {
        setPoolId(""); setSimulationPoolId(""); setError("原角色池已不可使用；请重新选择可用池并核对初始条件。");
      } else setMessage("来源已重新读取。若配置修订变化，重新载入前请处理本页草稿。");
      setSourceWarning(null);
    } catch (cause) { if (isCurrentSession(identity)) setError(`重新读取来源失败：${errorMessage(cause)}`); }
    finally { if (isCurrentSession(identity)) setBusy(false); }
  }
  async function checkConfigWrite() {
    const identity = sessionIdentity;
    setConfigChecked(false); setError("");
    try { await refreshConfigs(); if (isCurrentSession(identity)) setConfigChecked(true); }
    catch (cause) { if (isCurrentSession(identity)) setError(`配置列表读取失败：${errorMessage(cause)}。请重试查询。`); }
  }
  async function saveConfig() {
    const validation = validateParameters(parameters);
    if (validation) { setError(validation); return; }
    if (!name.trim() || !chosenConfigPool || !activeConfigRule || busy || configUncertain) { setError(configUncertain ? "请先查询并核对上次配置写入结果" : "请填写实验名称并选择配置可用的角色池"); return; }
    if (unresolvedInitialState(parameters, activeConfigRule)) { setError("有待处理的旧初始状态。请按提示修正或清除后再保存配置。"); return; }
    const context = configContext!;
    if ((nonzero(parameters) || configContextConfirmed !== null) && !sameContext(configContextConfirmed, context)) { setError("配置绑定池的初始条件上下文未确认，请先确认当前目标和规则上下文"); return; }
    const identity = sessionIdentity;
    setBusy(true); setError(""); setServerFields({}); setMessage("");
    try {
      const payload = { name, pool_ref: { id: chosenConfigPool.id, name: chosenConfigPool.name }, parameters,
        initial_context: configContextConfirmed ?? (nonzero(parameters) ? null : context),
        expected_pool_revision: chosenConfigPool.revision, expected_rule_revision: chosenConfigPool.rule_ref.revision };
      const saved = await apiRequest<ExperimentConfig>(config ? `experiment-configs/${config.id}/` : "experiment-configs/",
        { method: config ? "PATCH" : "POST", body: JSON.stringify(config ? { ...payload, expected_revision: config.revision } : payload) });
      if (!isCurrentSession(identity)) return;
      setConfig(saved); setConfigId(saved.id);
      markSaved({ name: saved.name, parameters: saved.parameters, poolId: chosenConfigPool.id,
        simulationPoolId: managingOtherConfig ? simulationPoolId : chosenConfigPool.id,
        simulationContext: saved.initial_context, configContextConfirmed: saved.initial_context });
      setMessage("实验配置已保存；没有开始模拟");
      await refreshConfigs().catch((cause) => { if (isCurrentSession(identity)) setError(`配置已保存，但列表刷新失败：${errorMessage(cause)}`); });
    } catch (cause) {
      if (!isCurrentSession(identity)) return;
      if (cause instanceof ApiError && cause.status < 500) {
        if (cause.status === 409) setSourceWarning("conflict");
        if (cause.status === 403) setSourceWarning("permission");
        setError(cause.status === 409 ? "该配置已在别处修改；本页草稿已保留。请核对最新版本后再决定是否重新载入。" : errorMessage(cause)); setServerFields(apiFieldIssues(cause));
      } else { setConfigUncertain(true); setConfigChecked(false); setMessage("配置保存结果未确认；请查询配置列表并人工核对。系统不会自动重发写请求。"); await checkConfigWrite(); }
    }
    finally { if (isCurrentSession(identity)) setBusy(false); }
  }
  async function importConfig(raw: string) {
    if (!confirmDiscard(dirty)) return;
    const identity = sessionIdentity;
    const epoch = ++importEpoch.current;
    setBusy(true); setError(""); setServerFields({}); setMessage("");
    try {
      const result = await apiRequest<ImportResult>("experiment-configs/import/preview/", { method: "POST", body: `{"document":${raw}}` });
      if (epoch !== importEpoch.current || !isCurrentSession(identity)) return;
      setImportResult(result); setConfig(null); setConfigId(""); setPreview(null); setPreviewKey("");
      const match = result.resolution.status === "matched" && result.resolution.candidates.length === 1 ? result.resolution.candidates[0] : null;
      const selectedPool = match?.id ?? "";
      setImportPoolId(selectedPool);
      setDraft({ name: result.document.name, parameters: result.document.parameters, poolId: selectedPool, simulationPoolId: selectedPool,
        simulationContext: result.document.initial_context, configContextConfirmed: result.document.initial_context });
    } catch (cause) { if (epoch === importEpoch.current && isCurrentSession(identity)) { setError(errorMessage(cause)); setServerFields(apiFieldIssues(cause)); } }
    finally { if (epoch === importEpoch.current && isCurrentSession(identity)) setBusy(false); }
  }
  async function confirmImport() {
    const pool = pools.find((item) => item.id === importPoolId);
    if (!importResult || !pool || !activeConfigRule || !configContext || busy || configUncertain) return;
    if (unresolvedInitialState(parameters, activeConfigRule)) { setError("有待处理的旧初始状态。请按提示修正或清除后再确认导入。"); return; }
    if ((nonzero(parameters) || configContextConfirmed !== null) && !sameContext(configContextConfirmed, configContext)) {
      setError("导入池的初始条件上下文未确认，请先核对目标与当前规则"); return;
    }
    const identity = sessionIdentity;
    setBusy(true); setError(""); setServerFields({});
    try {
      const saved = await apiRequest<ExperimentConfig>("experiment-configs/import/confirm/", { method: "POST", body: JSON.stringify({
        document: { ...importResult.document, parameters, initial_context: configContextConfirmed }, pool_id: pool.id,
        pool_revision: pool.revision, rule_revision: pool.rule_ref.revision,
      }) });
      if (!isCurrentSession(identity)) return;
      setImportResult(null); setConfig(saved); setConfigId(saved.id);
      markSaved({ name: saved.name, parameters: saved.parameters, poolId: pool.id, simulationPoolId: pool.id,
        simulationContext: saved.initial_context, configContextConfirmed: saved.initial_context });
      setMessage("配置已导入并保存");
      await refreshConfigs().catch((cause) => { if (isCurrentSession(identity)) setError(`导入已保存，但列表刷新失败：${errorMessage(cause)}`); });
    } catch (cause) {
      if (!isCurrentSession(identity)) return;
      if (cause instanceof ApiError && cause.status < 500) { if (cause.status === 409) setSourceWarning("conflict"); if (cause.status === 403) setSourceWarning("permission"); setError(errorMessage(cause)); setServerFields(apiFieldIssues(cause)); }
      else { setConfigUncertain(true); setConfigChecked(false); setMessage("导入保存结果未确认；请查询配置列表并人工核对。系统不会自动重发写请求。"); await checkConfigWrite(); }
    }
    finally { if (isCurrentSession(identity)) setBusy(false); }
  }
  async function lookupJobs() {
    const identity = sessionIdentity;
    try { const found = await apiRequest<Page<JobSummary>>("jobs/mine/?page=1&page_size=50"); if (isCurrentSession(identity)) setJobs(found); }
    catch (cause) { if (isCurrentSession(identity)) setError(errorMessage(cause)); }
  }
  async function start() {
    const validation = validateParameters(parameters);
    if (validation) { setError(validation); return; }
    if (!previewPayload || !activeRule || busy || uncertain) { setError(uncertain ? "请先查询并人工核对上次提交；核对后才能显式开始新任务。" : "请先选择当前有权使用且规则有效的角色池"); return; }
    if (unresolvedInitialState(parameters, activeRule)) { setError("有待处理的旧初始状态。请按提示修正或清除后再预览。"); return; }
    if ((nonzero(parameters) || simulationContext !== null) && !sameContext(simulationContext, currentContext!)) {
      setError("初始条件的规则、稀有度顺序或目标已变化，请确认使用当前上下文后再预览"); return;
    }
    const identity = sessionIdentity;
    setBusy(true); setRunStage(previewReady ? "submit" : "preview"); setError(""); setServerFields({}); setMessage(""); setJobs(null); setChosenJobId("");
    const requestKey = currentPreviewKey;
    const requestEpoch = runEpoch.current;
    try {
      if (!previewReady) {
        const result = await apiRequest<PreviewResult>("jobs/preview/", { method: "POST", body: JSON.stringify(previewPayload) });
        if (!isCurrentSession(identity)) return;
        if (requestEpoch === runEpoch.current && requestKey === currentPreviewKeyRef.current) { setPreview(result); setPreviewKey(requestKey); setPreviewInvalidated(false); setMessage("预览已更新。核对计数后，确认并开始模拟。"); }
        setBusy(false); setRunStage(null); return;
      }
    } catch (cause) { if (isCurrentSession(identity) && requestEpoch === runEpoch.current) { if (cause instanceof ApiError && cause.status === 409) setSourceWarning("conflict"); if (cause instanceof ApiError && cause.status === 403) setSourceWarning("permission"); setError(errorMessage(cause)); setServerFields(apiFieldIssues(cause)); setPreview(null); setPreviewKey(""); setBusy(false); setRunStage(null); } return; }
    try {
      const job = await apiRequest<JobDetail>("jobs/", { method: "POST", body: JSON.stringify(previewPayload) });
      if (!isCurrentSession(identity)) return;
      setMessage(`任务已接受（${job.job_id}）。可在实验结果页查看。`);
      flushSync(() => setNavigatingAfterSubmit(true));
      navigate(`/results/?job=${job.job_id}`);
    } catch (cause) {
      if (!isCurrentSession(identity)) return;
      if (cause instanceof ApiError && cause.status < 500) { if (cause.status === 409) setSourceWarning("conflict"); if (cause.status === 403) setSourceWarning("permission"); setError(errorMessage(cause)); setServerFields(apiFieldIssues(cause)); setPreview(null); setPreviewKey(""); }
      else { setUncertain(true); setMessage("提交结果未确认。系统没有自动重试；请查询本人任务并按时间和参数人工核对。"); await lookupJobs(); }
    } finally { if (isCurrentSession(identity)) { setBusy(false); setRunStage(null); } }
  }

  return <div className="page-stack">
    <section className="panel"><div className="section-heading"><div><h2>实验配置</h2><p className="muted">明确保存后才写入配置；保存配置不会开始模拟。</p></div><ImportDialog label="导入JSON" onImport={importConfig} disabled={busy || configUncertain} />
      {config && <a className="secondary-button" href={`/api/v1/experiment-configs/${config.id}/export/?expected_revision=${config.revision}`} download="experiment.json">导出JSON</a>}</div>
      <div className="field-grid"><label>已保存配置<select disabled={busy || configUncertain} value={configId} onChange={(event) => chooseConfig(event.target.value)}><option value="">新建配置</option>{configs.map((item) => <option key={item.id} value={item.id}>{item.name}{item.owner_id !== user?.id ? `（${item.owner_name}）` : ""}</option>)}</select></label><label>实验名称<input id="experiment-name" disabled={busy} value={name} maxLength={255} onChange={(event) => setName(event.target.value)} /></label></div>
      <div className="button-row"><button className="primary-button" disabled={busy || configUncertain || Boolean(importResult) || !chosenConfigPool || !activeConfigRule} onClick={() => void saveConfig()}>{config ? "保存修改" : "保存配置"}</button>{config && <button disabled={busy || configUncertain} onClick={() => { setConfig(null); setConfigId(""); setName(`${name}副本`); }}>另存为</button>}</div>
      {importResult && <div className="import-preview"><h3>导入配置</h3><p>{importResult.resolution.status === "matched" ? "角色池ID匹配。" : "请从服务端候选中选择配置使用的角色池。"}</p>
        {importResult.resolution.candidates.length === 0 ? <p>没有可用候选。请返回角色池页确认权限或创建合适的池，再重新导入文件。</p> :
          <label>导入角色池<select disabled={busy} value={importPoolId} onChange={(event) => { const id = event.target.value; setImportPoolId(id); setPoolId(id); setSimulationPoolId(id); setPreview(null); setPreviewKey(""); }}><option value="">选择角色池</option>{importResult.resolution.candidates.filter((candidate) => pools.some((pool) => pool.id === candidate.id)).map((item) => <option key={item.id} value={item.id}>{item.name} · 修订 {item.revision}</option>)}</select></label>}
        <button disabled={busy || configUncertain || !importPoolId || !activeConfigRule} onClick={() => void confirmImport()}>确认导入并保存</button></div>}
      {configUncertain && <div className="import-preview"><h3>配置写入结果未确认</h3><p>请核对最近的配置名称、ID和修改时间。核对前不能再次保存或确认导入。</p>
        <button type="button" disabled={busy} onClick={() => void checkConfigWrite()}>查询配置列表</button>
        {configChecked && <><ul>{configs.filter((item) => item.owner_id === configWriteOwnerId).map((item) => <li key={item.id}>{item.name} · {item.id} · {item.updated_at}</li>)}</ul>
          <button type="button" onClick={() => { setConfigUncertain(false); setConfigChecked(false); setMessage("已人工核对。再次保存会发起新的写请求。"); }}>已核对配置列表</button></>}
      </div>}
    </section>
    {sourceWarning && <section className="panel"><h2>{sourceWarning === "conflict" ? "来源修订已变化" : "访问权限已变化"}</h2>
      <p className="muted">本页草稿仍在。重新读取规则、角色池和配置后，再核对当前来源与初始条件；重新载入配置会提示放弃本页修改。</p>
      <button type="button" disabled={busy} onClick={() => void refreshSources()}>重新检查来源与访问权</button>
    </section>}
    <section className="panel"><div className="section-heading"><div><h2>本次模拟</h2><p className="muted">这里决定运行参数与初始状态；共享规则在角色池中管理。</p></div></div>
      <div className="field-grid"><label>{managingOtherConfig ? "配置绑定角色池" : "角色池"}<select id="experiment-pool" disabled={busy || uncertain || Boolean(importResult)} value={poolId} onChange={(event) => { setPoolId(event.target.value); if (managingOtherConfig) setSimulationPoolId(event.target.value); }}><option value="">选择池</option>{configPools.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {managingOtherConfig && <label>本次模拟角色池<select disabled={busy || uncertain || Boolean(importResult)} value={simulationPoolId} onChange={(event) => setSimulationPoolId(event.target.value)}><option value="">选择当前有权使用的池</option>{pools.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.kind === "public" ? "公共池" : item.owner_name ?? "私有池"}</option>)}</select></label>}
        <div className="readonly-summary"><span>绑定规则</span><strong>{chosenSimulationPool?.rule_ref.name ?? "—"}</strong><span>修订详情</span><strong>{chosenSimulationPool ? `规则 ${chosenSimulationPool.rule_ref.revision} / 池 ${chosenSimulationPool.revision}` : "—"}</strong></div></div>
      {managingOtherConfig && <p className="muted">管理员代管的配置仍按所有者筛选绑定池；本次模拟池只用于管理员本人新建任务。</p>}
      {chosenSimulationPool && <p className="muted">概率与保底在<Link to="/rules/">规则页</Link>修改，角色与奖励在<Link to="/pools/">角色池页</Link>修改。</p>}
      <fieldset disabled={busy || uncertain} className="plain-fieldset">
        <ExperimentForm value={parameters} onChange={updateParameters} />
        {activeRule && chosenSimulationPool && <InitialConditions rule={activeRule.document} pool={chosenSimulationPool.document} value={parameters} savedContext={simulationContext} onChange={updateParameters} onConfirm={(context) => { setSimulationContext(context); if (!managingOtherConfig || chosenConfigPool?.id === chosenSimulationPool.id) setConfigContextConfirmed(context); setError(""); }} />}
      </fieldset>
      {configContext && (nonzero(parameters) || configContextConfirmed !== null) && !sameContext(configContextConfirmed, configContext) && <p className="muted">配置绑定池的规则上下文与已保存上下文不同。保存配置前请单独确认配置池上下文。<button type="button" disabled={busy} onClick={() => setConfigContextConfirmed(configContext)}>确认配置池上下文</button></p>}
      <SimulationPreview value={previewReady ? preview : null} />
      {previewInvalidated && <p role="status">参数、池、规则或初始确认已变化，请重新预览。</p>}
      {previewReady && <p className="muted">{user?.role === "admin" ? "管理员预览按当前参数计数；提交时仍执行服务器校验。" : `预计明细事件数：${formatCount(preview!.counts.total.trace_events)}；普通用户的业务上限以服务器当前配置为准。`}</p>}
      <button className="primary-button" disabled={busy || !activeRule || uncertain} onClick={() => void start()}>{runStage === "preview" ? "正在生成预览…" : runStage === "submit" ? "正在提交…" : previewReady ? "确认并开始模拟" : "预览本次实验"}</button>
    </section>
    {uncertain && <section className="panel"><h2>提交结果未确认</h2><p className="muted">请按接受时间、池名称和参数人工核对。系统不会自动选择任务，也不会重发上次请求。</p><button disabled={busy} onClick={() => void lookupJobs()}>查询本人任务</button>{jobs && <div className="table-wrap"><table><thead><tr><th>接受时间</th><th>状态</th><th>角色池</th><th>主抽数 / 轮数</th><th>任务ID</th></tr></thead><tbody>{jobs.items.map((job) => <tr key={job.job_id} aria-selected={chosenJobId === job.job_id} onClick={() => setChosenJobId(job.job_id)}><td>{new Date(job.accepted_at).toLocaleString()}</td><td>{jobStatusLabel(job.status)}</td><td>{job.pool_name_snapshot}</td><td>{job.draws} / {job.trials}</td><td>{job.job_id}</td></tr>)}</tbody></table></div>}<button disabled={busy} onClick={() => { setUncertain(false); setJobs(null); setChosenJobId(""); setPreview(null); setPreviewKey(""); setMessage("已人工核对。再次预览并确认会创建新任务。"); }}>已核对，准备新任务</button></section>}
    <div id="experiment-form-feedback" tabIndex={-1}><FormFeedback error={error} issues={experimentFieldIssues(serverFields, chosenSimulationPool, activeRule)} /></div>{message && <p className="success-note" role="status">{message}</p>}
  </div>;
}
