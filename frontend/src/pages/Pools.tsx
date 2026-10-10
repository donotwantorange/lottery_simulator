import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import defaultPool from "../../../configs/pools/default.json";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { Page, Pool, PoolDocument, Rule } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ImportDialog } from "../components/ImportDialog";
import { FormFeedback, apiFieldIssues } from "../components/FormFeedback";
import { PoolEditor } from "../components/PoolEditor";
import { RarityMapping } from "../components/RarityMapping";
import { confirmDiscard, useEditorDraft, useUnsavedNavigation } from "../hooks/useEditorDraft";

type Filter = "all" | "public" | "mine" | "shared" | "private-all";
interface ImportPreview { document: PoolDocument; resolution: RuleResolution; body: string }
type RuleResolution =
  | { status: "matched"; rule: { id: string; name: string; revision: number } }
  | { status: "confirm" | "select" | "unavailable"; candidates: Array<{ id: string; name: string; original_author: string; kind: string; visibility: string; revision: number }> };

function freshPool(templateRule?: Rule): PoolDocument {
  const value = structuredClone(defaultPool) as PoolDocument;
  value.id = crypto.randomUUID(); value.name = "新角色池"; value.original_author = null;
  const ruleIds = templateRule?.document.rarities.map((rarity) => rarity.id) ?? [];
  const rosterIds = value.rarity_pools.map((roster) => roster.rarity_id);
  const matchingStructure = !!templateRule && ruleIds.length === rosterIds.length &&
    new Set(rosterIds).size === rosterIds.length && ruleIds.every((id) => rosterIds.includes(id)) &&
    value.rarity_pools.every((roster) => roster.characters.every((character) => character.rarity_id === roster.rarity_id)) &&
    Object.keys(value.rarity_labels).every((id) => ruleIds.includes(id)) &&
    value.rewards.every((reward) => Object.keys(reward.amounts).every((id) => ruleIds.includes(id)));
  const characters = value.rarity_pools.flatMap((roster) => roster.characters);
  const targetId = value.mechanism_targets.periodic_grant;
  const highest = templateRule?.document.rarities.reduce((best, rarity) => !best || rarity.rank > best.rank ? rarity : best,
    undefined as Rule["document"]["rarities"][number] | undefined);
  const validTargets = (!targetId || characters.some((character) => character.id === targetId)) &&
    (!templateRule?.document.big_pity.enabled || value.rarity_pools.find((roster) => roster.rarity_id === highest?.id)?.characters.some((character) => character.is_up)) &&
    (!templateRule?.document.grant.enabled || (templateRule.document.grant.target === "first_up"
      ? characters.some((character) => character.is_up) : !!targetId));
  value.rule_ref = templateRule ? { id: templateRule.id, name: templateRule.name } : { id: "", name: "" };
  if (!matchingStructure || !validTargets) {
    value.rarity_pools = templateRule?.document.rarities.map((rarity) => ({
      rarity_id: rarity.id, characters: [], up_enabled: false, up_share: 0,
    })) ?? [];
    value.rarity_labels = {};
    value.rewards = [];
    value.mechanism_targets = {};
  }
  return value;
}

function ruleCanBeUsed(rule: Rule, ownerId: string, poolKind: "public" | "private", poolVisibility: "public" | "hidden", ownerIsAdmin = false) {
  if (poolKind === "public") return rule.kind === "public";
  if (rule.kind === "public") return true;
  if (poolVisibility === "public") return rule.visibility === "public";
  return rule.owner_id === ownerId || rule.visibility === "public" || ownerIsAdmin;
}

function poolFieldIssues(fields: Record<string, string>, draft: PoolDocument | null, context: "pool" | "copy" | "other") {
  const issues: Array<{ id: string; label: string; message: string }> = [];
  const general: string[] = [];
  for (const [path, message] of Object.entries(fields)) {
    if (/^(?:document\.)?name$/.test(path) && context !== "other") {
      issues.push({ id: context === "copy" ? "pool-copy-name" : "pool-name",
        label: context === "copy" ? "副本名称" : "角色池名称", message });
      continue;
    }
    const match = /^(?:document\.)?(?:rosters|rarity_pools)\.(\d+)\.characters\.(\d+)\.(name|weight)$/.exec(path);
    const character = match && draft?.rarity_pools[Number(match[1])]?.characters[Number(match[2])];
    if (character && context === "pool") {
      issues.push({ id: `pool-character-${match![3]}-${character.id}`,
        label: `${character.name || "未命名角色"}的${match![3] === "name" ? "名称" : "权重"}`, message });
    } else general.push(message);
  }
  return { issues, general };
}

export function Pools() {
  const { user, sessionGeneration } = useAuth();
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<Pool[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Pool | null>(null);
  const poolDraft = useEditorDraft<PoolDocument | null>(null);
  const { value: draft, setValue: setDraft, dirty: documentDirty } = poolDraft;
  const [kind, setKind] = useState<"public" | "private">("private");
  const [visibility, setVisibility] = useState<"public" | "hidden">("hidden");
  const [baseMeta, setBaseMeta] = useState<{ kind: "public" | "private"; visibility: "public" | "hidden" }>({
    kind: "private", visibility: "hidden",
  });
  const [copyPreparing, setCopyPreparing] = useState(false);
  const [copyName, setCopyName] = useState("");
  const [copyKind, setCopyKind] = useState<"public" | "private">("private");
  const [copyRuleId, setCopyRuleId] = useState("");
  const [copyMapping, setCopyMapping] = useState<Record<string, string | null>>({});
  const [copyClear, setCopyClear] = useState(false);
  const [copyError, setCopyError] = useState("");
  const [ruleMapping, setRuleMapping] = useState<Record<string, string | null>>({});
  const [ruleClearUnmapped, setRuleClearUnmapped] = useState(false);
  const [editorValid, setEditorValid] = useState(true);
  const [editorVersion, setEditorVersion] = useState(0);
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [importRuleId, setImportRuleId] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [serverFields, setServerFields] = useState<Record<string, string>>({});
  const [fieldContext, setFieldContext] = useState<"pool" | "copy" | "other">("other");
  const [forcedReadOnly, setForcedReadOnly] = useState(false);
  const [deniedPoolId, setDeniedPoolId] = useState<string | null>(null);
  const serverFieldSource = useRef<PoolDocument | null>(null);
  const sessionEpoch = useRef(0);
  const loadEpoch = useRef(0);
  const sessionIdentity = `${user?.id ?? ""}:${sessionGeneration}`;
  const sessionIdentityRef = useRef(sessionIdentity);
  sessionIdentityRef.current = sessionIdentity;
  const dirty = documentDirty || (!!draft && (kind !== baseMeta.kind || visibility !== baseMeta.visibility));
  useUnsavedNavigation(dirty);

  async function load(signal?: AbortSignal) {
    const requestEpoch = ++loadEpoch.current;
    const requestSession = sessionIdentity;
    const [poolFirst, ruleFirst] = await Promise.all([
      apiRequest<Page<Pool>>("pools/?page=1&page_size=200", {}, signal),
      apiRequest<Page<Rule>>("rules/?page=1&page_size=200", {}, signal),
    ]);
    const poolRest = await Promise.all(Array.from({ length: Math.ceil(poolFirst.total / 200) - 1 }, (_, index) =>
      apiRequest<Page<Pool>>(`pools/?page=${index + 2}&page_size=200`, {}, signal)));
    const ruleRest = await Promise.all(Array.from({ length: Math.ceil(ruleFirst.total / 200) - 1 }, (_, index) =>
      apiRequest<Page<Rule>>(`rules/?page=${index + 2}&page_size=200`, {}, signal)));
    if (!signal?.aborted && requestEpoch === loadEpoch.current && requestSession === sessionIdentityRef.current) {
      setItems([...poolFirst.items, ...poolRest.flatMap((result) => result.items)]);
      setRules([...ruleFirst.items, ...ruleRest.flatMap((result) => result.items)]);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    const currentSession = ++sessionEpoch.current;
    setLoading(true); setBusy(false); setItems([]); setRules([]); setSelected(null); poolDraft.reset(null); setImportPreview(null);
    setCopyPreparing(false); setError(""); setMessage(""); setServerFields({}); setForcedReadOnly(false); setDeniedPoolId(null); setBaseMeta({ kind: "private", visibility: "hidden" });
    void load(controller.signal).catch((cause) => {
      if (!controller.signal.aborted && currentSession === sessionEpoch.current && sessionIdentity === sessionIdentityRef.current) setError(errorMessage(cause));
    }).finally(() => { if (!controller.signal.aborted && currentSession === sessionEpoch.current && sessionIdentity === sessionIdentityRef.current) setLoading(false); });
    return () => { controller.abort(); loadEpoch.current += 1; };
  }, [user?.id, sessionGeneration]);

  function select(pool: Pool, discardConfirmed = false): boolean {
    if (!discardConfirmed && !confirmDiscard(dirty)) return false;
    setEditorVersion((current) => current + 1);
    setSelected(pool); setForcedReadOnly(pool.id === deniedPoolId); poolDraft.reset(structuredClone(pool.document)); setKind(pool.kind); setVisibility(pool.visibility);
    setBaseMeta({ kind: pool.kind, visibility: pool.visibility });
    setCopyName(`${pool.name}副本`); setCopyKind("private"); setCopyRuleId(pool.rule_ref.id);
    setCopyPreparing(false); setCopyMapping({}); setCopyClear(false); setCopyError(""); setImportPreview(null); setError(""); setMessage(""); setServerFields({}); serverFieldSource.current = null;
    setRuleMapping({}); setRuleClearUnmapped(false); setEditorValid(true);
    return true;
  }

  function create() {
    if (!confirmDiscard(dirty)) return;
    const ownerId = user?.id ?? "";
    const ownerIsAdmin = user?.role === "admin";
    const templateRule = rules.find((item) => item.id === (defaultPool as PoolDocument).rule_ref.id &&
      ruleCanBeUsed(item, ownerId, "private", "hidden", ownerIsAdmin));
    const fresh = freshPool(templateRule);
    setEditorVersion((current) => current + 1);
    setSelected(null); setForcedReadOnly(false); setDeniedPoolId(null); poolDraft.reset(fresh); setKind("private"); setVisibility("hidden");
    setBaseMeta({ kind: "private", visibility: "hidden" });
    setImportPreview(null); setError(""); setMessage("");
    setCopyPreparing(false); setServerFields({}); serverFieldSource.current = null;
    setRuleMapping({}); setRuleClearUnmapped(false); setEditorValid(true);
  }

  function changeDraft(next: PoolDocument) {
    const source = serverFieldSource.current;
    if (source) setServerFields((current) => Object.fromEntries(Object.entries(current).filter(([path]) => {
      if (/^(?:document\.)?name$/.test(path)) return next.name === source.name;
      const match = /^(?:document\.)?(?:rosters|rarity_pools)\.(\d+)\.characters\.(\d+)\.(name|weight)$/.exec(path);
      if (match) {
        const before = source.rarity_pools[Number(match[1])]?.characters[Number(match[2])];
        const after = next.rarity_pools.flatMap((roster) => roster.characters).find((character) => character.id === before?.id);
        return !!before && !!after && before[match[3] as "name" | "weight"] === after[match[3] as "name" | "weight"];
      }
      const rewardMatch = /^(?:document\.)?rewards\.(\d+)\.amounts\.([^.]*)$/.exec(path);
      if (rewardMatch) {
        const before = source.rewards[Number(rewardMatch[1])];
        return !!before && next.rewards.some((reward) => reward.id === before.id && rewardMatch[2] in reward.amounts);
      }
      return true;
    })));
    setDraft(next);
  }

  async function recheckAfterDeniedWrite(cause: unknown, resource: Pool | null, requestSession: string) {
    if (!(cause instanceof ApiError) || ![403, 404].includes(cause.status) || !resource) return;
    try {
      const accessible = await apiRequest<Pool>(`pools/${resource.id}/`);
      if (requestSession !== sessionIdentityRef.current) return;
      setItems((current) => current.map((item) => item.id === resource.id ? accessible : item));
      setSelected(accessible); poolDraft.reset(structuredClone(accessible.document));
      setKind(accessible.kind); setVisibility(accessible.visibility);
      setBaseMeta({ kind: accessible.kind, visibility: accessible.visibility });
      setForcedReadOnly(true); setDeniedPoolId(resource.id); setCopyPreparing(false);
      setError("写入权限已失效；已重新读取角色池，当前以只读方式显示。");
      setServerFields({});
    } catch (readCause) {
      if (requestSession !== sessionIdentityRef.current) return;
      setItems((current) => current.filter((item) => item.id !== resource.id));
      setSelected(null); poolDraft.reset(null); setCopyPreparing(false); setForcedReadOnly(false); setDeniedPoolId(null);
      setError(readCause instanceof ApiError && [403, 404].includes(readCause.status)
        ? "角色池已不存在或当前账号无权查看，详情已清除。"
        : `写入被拒绝且无法确认当前访问权限，详情已清除：${errorMessage(readCause)}`);
      setServerFields({});
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || busy || loading) return;
    if (!event.currentTarget.reportValidity() || !editorValid) return;
    const currentSession = sessionIdentity;
    const rule = rules.find((item) => item.id === draft.rule_ref.id);
    if (!rule) { setError("请绑定一个当前可用规则。"); return; }
    const poolOwnerId = kind === "public" ? "" : selected?.owner_id ?? user!.id;
    const ownerIsAdmin = poolOwnerId === user?.id && user?.role === "admin";
    if (!ruleCanBeUsed(rule, poolOwnerId, kind, visibility, ownerIsAdmin)) {
      setError("所选规则不符合此池所有者及可见性的使用权限。"); return;
    }
    if (kind === "public" && user?.role !== "admin") { setError("仅管理员可创建公共池。"); return; }
    if (selected && selected.kind !== kind) {
      setError("现有池类型不能原位改变，请复制为新池。"); return;
    }
    setBusy(true); setError(""); setMessage(""); setServerFields({});
    try {
      const payload = { ...draft, kind, visibility,
        expected_rule_revision: rule.revision,
        ...(selected && selected.rule_ref.id !== draft.rule_ref.id
          ? { rarity_mapping: ruleMapping, clear_unmapped: ruleClearUnmapped } : {}),
        ...(selected ? { expected_revision: selected.revision } : {}) };
      const saved = await apiRequest<Pool>(selected ? `pools/${selected.id}/` : "pools/", {
        method: selected ? "PATCH" : "POST", body: JSON.stringify(payload),
      });
      if (currentSession !== sessionIdentityRef.current) return;
      setSelected(saved); poolDraft.markSaved(structuredClone(saved.document)); setKind(saved.kind); setVisibility(saved.visibility);
      setBaseMeta({ kind: saved.kind, visibility: saved.visibility });
      setEditorVersion((current) => current + 1);
      setRuleMapping({}); setRuleClearUnmapped(false); setEditorValid(true);
      setMessage("角色池已保存。"); await load();
    } catch (cause) {
      if (currentSession !== sessionIdentityRef.current) return;
      if (cause instanceof ApiError && cause.code === "revision_conflict") setError("角色池或规则已变化；你的草稿仍保留，请重新加载最新版本后再保存。");
      else { setError(errorMessage(cause)); serverFieldSource.current = structuredClone(draft); setFieldContext("pool"); setServerFields(apiFieldIssues(cause)); }
      await recheckAfterDeniedWrite(cause, selected, currentSession);
    } finally { if (currentSession === sessionIdentityRef.current) setBusy(false); }
  }

  async function copy() {
    if (!selected || !copyPreparing || !copyName.trim() || busy || loading) return;
    const currentSession = sessionIdentity;
    const targetRule = rules.find((item) => item.id === copyRuleId);
    if (!targetRule) { setCopyError("请选择一个规则。"); return; }
    const ownerId = copyKind === "public" ? "" : user!.id;
    if (!ruleCanBeUsed(targetRule, ownerId, copyKind, copyKind === "public" ? "public" : "hidden",
      copyKind === "private" && user?.role === "admin")) {
      setCopyError("此账号或池类型不能使用该规则。"); return;
    }
    const sourceRule = rules.find((item) => item.id === selected.rule_ref.id);
    if (!sourceRule) { setCopyError("源规则不可用，请刷新列表。"); return; }
    const removed = sourceRule.document.rarities.filter((rarity) =>
      !targetRule.document.rarities.some((next) => next.id === rarity.id));
    if (removed.some((rarity) => copyMapping[rarity.id] === undefined)) {
      setCopyError("请先映射或清空每个已删除的旧档。"); return;
    }
    if (removed.some((rarity) => copyMapping[rarity.id] === null) && !copyClear) {
      setCopyError("清空未映射档位需要勾选确认。"); return;
    }
    const mapped = removed.map((rarity) => copyMapping[rarity.id]).filter(Boolean);
    const preserved = sourceRule.document.rarities.map((rarity) => rarity.id).filter((id) =>
      targetRule.document.rarities.some((next) => next.id === id));
    if (new Set([...mapped, ...preserved]).size !== mapped.length + preserved.length) {
      setCopyError("多个旧档不能映射到同一个新档。"); return;
    }
    if (!confirmDiscard(dirty)) return;
    setBusy(true); setCopyError(""); setError(""); setServerFields({});
    try {
      const copied = await apiRequest<Pool>(`pools/${selected.id}/copy/`, { method: "POST", body: JSON.stringify({
        name: copyName.trim(), kind: copyKind, expected_revision: selected.revision,
        expected_source_rule_revision: sourceRule.revision,
        rule_ref: { id: targetRule.id, name: targetRule.name }, expected_rule_revision: targetRule.revision,
        rarity_mapping: copyMapping, clear_unmapped: copyClear,
      }) });
      if (currentSession !== sessionIdentityRef.current) return;
      select(copied, true); setMessage("角色池已复制为新资源；最初作者署名已保留。"); await load();
    } catch (cause) {
      if (currentSession !== sessionIdentityRef.current) return;
      setCopyError(errorMessage(cause));
      if (cause instanceof ApiError && cause.code === "revision_conflict") setError("池或规则修订已变化，请刷新并重新确认。");
      else { setFieldContext("copy"); setServerFields(apiFieldIssues(cause)); }
      await recheckAfterDeniedWrite(cause, selected, currentSession);
    } finally { if (currentSession === sessionIdentityRef.current) setBusy(false); }
  }

  async function remove() {
    if (!selected || busy || loading || !confirmDiscard(dirty) || !window.confirm(`确认删除“${selected.name}”？引用它的实验配置将失去池关联。`)) return;
    const currentSession = sessionIdentity;
    setBusy(true); setError(""); setMessage("");
    try {
      await apiRequest<void>(`pools/${selected.id}/`, { method: "DELETE", body: JSON.stringify({ expected_revision: selected.revision }) });
      if (currentSession !== sessionIdentityRef.current) return;
      setSelected(null); poolDraft.reset(null); setCopyPreparing(false); setMessage("角色池已删除。"); await load();
    } catch (cause) { if (currentSession === sessionIdentityRef.current) { setError(errorMessage(cause)); setFieldContext("other"); setServerFields(apiFieldIssues(cause)); await recheckAfterDeniedWrite(cause, selected, currentSession); } }
    finally { if (currentSession === sessionIdentityRef.current) setBusy(false); }
  }

  function exportSelected() {
    if (!selected || busy || loading) return;
    const link = document.createElement("a");
    link.href = `/api/v1/pools/${encodeURIComponent(selected.id)}/export/?expected_revision=${selected.revision}`;
    link.download = "pool.json"; link.click();
  }

  async function previewImport(raw: string) {
    if (busy || loading) return;
    const currentSession = sessionIdentity;
    setBusy(true); setError(""); setMessage(""); setImportPreview(null);
    try {
      const preview = await apiRequest<{ document: PoolDocument; resolution: RuleResolution }>("pools/import/preview/", {
        method: "POST", body: raw,
      });
      if (currentSession !== sessionIdentityRef.current) return;
      setImportPreview({ ...preview, body: raw });
      setImportRuleId(preview.resolution.status === "matched" ? preview.resolution.rule.id : "");
    } catch (cause) { if (currentSession === sessionIdentityRef.current) { setError(errorMessage(cause)); setFieldContext("other"); setServerFields(apiFieldIssues(cause)); } throw cause; }
    finally { if (currentSession === sessionIdentityRef.current) setBusy(false); }
  }

  async function confirmImport() {
    if (!importPreview || busy || loading) return;
    const currentSession = sessionIdentity;
    const rule = rules.find((item) => item.id === importRuleId);
    if (!rule) { setError("请选择文件匹配或名称候选中的一个当前可用规则。"); return; }
    if (!confirmDiscard(dirty)) return;
    setBusy(true); setError("");
    try {
      const imported = await apiRequest<Pool>("pools/import/confirm/", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: `{"document":${importPreview.body.trim()},"rule_id":"${rule.id}","rule_revision":${rule.revision}}` });
      if (currentSession !== sessionIdentityRef.current) return;
      setImportPreview(null); select(imported, true); setMessage("池已导入为当前账号的隐藏私有池。"); await load();
    } catch (cause) { if (currentSession === sessionIdentityRef.current) { setError(errorMessage(cause)); setFieldContext("other"); setServerFields(apiFieldIssues(cause)); } }
    finally { if (currentSession === sessionIdentityRef.current) setBusy(false); }
  }

  const filtered = useMemo(() => items.filter((pool) => filter === "all" ||
    (filter === "public" && pool.kind === "public") ||
    (filter === "mine" && pool.owner_id === user?.id) ||
    (filter === "shared" && pool.kind === "private" && pool.visibility === "public" && pool.owner_id !== user?.id) ||
    (filter === "private-all" && pool.kind === "private")), [items, filter, user?.id]);
  const visible = filtered.slice((page - 1) * 100, page * 100);
  const pageCount = Math.max(1, Math.ceil(filtered.length / 100));
  const canEdit = !!user && !!selected && !forcedReadOnly && (user.role === "admin" || selected.owner_id === user.id);
  const fieldFeedback = poolFieldIssues(serverFields, serverFieldSource.current ?? draft, fieldContext);
  const sourceRule = selected && rules.find((item) => item.id === selected.rule_ref.id);
  const copyTargetRule = rules.find((item) => item.id === copyRuleId);
  const currentRule = draft ? rules.find((item) => item.id === draft.rule_ref.id) : undefined;
  const availableRules = rules.filter((candidate) => ruleCanBeUsed(candidate, kind === "public" ? "" : selected?.owner_id ?? user?.id ?? "",
    kind, visibility, !!user && (!selected || selected.owner_id === user.id) && user.role === "admin"));

  return <div className="page-stack">
    <section className="panel">
      <div className="section-heading"><div><h2>角色池</h2><p className="muted">池绑定规则并配置角色、奖励和目标。规则控制概率及保底。</p></div>
        <div className="button-row"><button className="primary-button" disabled={busy || loading} onClick={create}>新建角色池</button>
          <ImportDialog label="导入池JSON" disabled={busy || loading} onImport={previewImport} /></div></div>
      <label className="compact-field">筛选<select disabled={busy || loading} value={filter} onChange={(event) => { setFilter(event.target.value as Filter); setPage(1); }}>
        <option value="all">全部可见</option><option value="public">公共池</option><option value="mine">我的私有池</option>
        <option value="shared">他人公开池</option>{user?.role === "admin" && <option value="private-all">全部私有池</option>}
      </select></label>
      <div className="table-wrap"><table><thead><tr><th>名称</th><th>类型 / 可见性</th><th>所有者</th><th>最初作者</th><th>绑定规则</th><th>修订</th><th>操作</th></tr></thead><tbody>
        {visible.map((pool) => <tr key={pool.id}><td>{pool.name}</td>
          <td>{pool.kind === "public" ? "公共池" : pool.visibility === "public" ? "公开私有池" : "隐藏私有池"}</td>
          <td>{pool.owner_name ?? "—"}</td><td>{pool.original_author}</td><td>{pool.rule_ref.name} · {pool.rule_ref.revision}</td><td>{pool.revision}</td>
          <td><button className="link-button" disabled={busy || loading} onClick={() => select(pool)}>{user?.role === "admin" || pool.owner_id === user?.id ? "编辑" : "查看 / 复制"}</button></td></tr>)}
      </tbody></table></div>
      {loading ? <p className="muted" role="status">正在加载角色池和规则…</p> : visible.length === 0 && <p className="muted">当前筛选没有角色池。</p>}
      <div className="button-row"><button disabled={busy || loading || page === 1} onClick={() => setPage(page - 1)}>上一页</button>
        <span>第 {page} / {pageCount} 页 · 当前筛选 {filtered.length} 个</span>
        <button disabled={busy || loading || page >= pageCount} onClick={() => setPage(page + 1)}>下一页</button></div>
    </section>

    {importPreview && <section className="panel import-preview" aria-labelledby="pool-import-title">
      <h2 id="pool-import-title">确认导入角色池</h2>
      <p>文件池“{importPreview.document.name}”不会携带数据库所有权；确认后新建为隐藏私有池。</p>
      <p className="muted">{importPreview.resolution.status === "matched" ? `规则ID已匹配：${importPreview.resolution.rule.name}`
        : importPreview.resolution.status === "confirm" ? "未找到规则ID，按名称找到候选；请选择并确认。"
          : importPreview.resolution.status === "select" ? "规则名称有多个候选，请选择一个。"
            : "没有可用的规则候选；请取消后先准备可访问的规则。"}</p>
      {importPreview.resolution.status !== "unavailable" && <label className="compact-field">绑定规则
        <select disabled={busy || loading} value={importRuleId} onChange={(event) => setImportRuleId(event.target.value)}>
          <option value="">选择规则</option>
          {(importPreview.resolution.status === "matched" ? [importPreview.resolution.rule]
            : importPreview.resolution.candidates).map((candidate) => {
              const current = rules.find((item) => item.id === candidate.id);
              return current && <option key={candidate.id} value={candidate.id}>{candidate.name} · {current.revision}</option>;
            })}
        </select></label>}
      <div className="button-row"><button className="primary-button" disabled={busy || loading || importPreview.resolution.status === "unavailable" || !importRuleId}
        onClick={() => void confirmImport()}>确认导入</button><button disabled={busy || loading} onClick={() => setImportPreview(null)}>取消</button></div>
    </section>}

    {draft && <section className="panel"><div className="section-heading"><div><h2>{selected ? canEdit ? "编辑角色池" : "角色池详情" : "新建角色池"}</h2>
      <p className="muted">池会保存所选规则修订和角色数据；规则更改不在这里编辑。</p></div>
      {selected && <div className="button-row"><button disabled={busy || loading} onClick={exportSelected}>导出JSON</button>
        <button type="button" disabled={busy || loading} onClick={() => { setCopyPreparing((value) => !value); setCopyError(""); }}>
          {copyPreparing ? "关闭副本准备" : "准备副本"}</button>
        {canEdit && <button className="danger-button" disabled={busy || loading} onClick={() => void remove()}>删除池</button>}</div>}</div>
      <form className="pool-save-form" onSubmit={(event) => void save(event)}>
        <PoolEditor key={`${selected?.id ?? "new"}:${selected?.rule_ref.id ?? draft.rule_ref.id}:${editorVersion}`} value={draft} rule={currentRule}
          rules={availableRules}
          kind={kind} visibility={visibility} canEdit={!selected || canEdit}
          busy={busy} canCreatePublic={user?.role === "admin"} ownerIsAdmin={!!user && (!selected || selected.owner_id === user.id) && user.role === "admin"}
          poolOwnerId={kind === "public" ? null : selected?.owner_id ?? user?.id ?? null}
          editing={!!selected} savedRuleId={selected?.rule_ref.id} onChange={changeDraft} onKind={setKind} onVisibility={setVisibility}
          onRuleMapping={(map, clear) => { setRuleMapping(map); setRuleClearUnmapped(clear); }}
          onCancelRuleMapping={() => { if (selected) { poolDraft.reset(structuredClone(selected.document)); setRuleMapping({}); setRuleClearUnmapped(false); setEditorValid(true); setEditorVersion((v) => v + 1); } }}
          onValidityChange={setEditorValid} onUnfinishedChange={poolDraft.setUnfinished} />
        {(!selected || canEdit) && <button className="primary-button" type="submit"
          disabled={busy || loading || !editorValid || !draft.name.trim() || !currentRule}>
          {busy ? "处理中…" : selected ? "保存修改" : "创建角色池"}</button>}
      </form>
      {selected && copyPreparing && <div className="editor-section"><h3>准备复制已保存版本</h3>
        <p className="muted">来源：{selected.name} · 修订 {selected.revision}。当前未保存修改不会带入副本。</p>
        <div className="field-grid"><label>新名称<input id="pool-copy-name" disabled={busy || loading} value={copyName} onChange={(event) => setCopyName(event.target.value)} /></label>
          <label>类型<select disabled={busy || loading} value={copyKind} onChange={(event) => {
            const nextKind = event.target.value as "public" | "private"; setCopyKind(nextKind);
            const allowed = rules.find((rule) => ruleCanBeUsed(rule, nextKind === "public" ? "" : user?.id ?? "", nextKind,
              nextKind === "public" ? "public" : "hidden", nextKind === "private" && user?.role === "admin"));
            if (allowed) setCopyRuleId(allowed.id);
            setCopyMapping({}); setCopyClear(false); setCopyError("");
          }}><option value="private">隐藏私有池</option>{user?.role === "admin" && <option value="public">公共池</option>}</select></label>
          <label>绑定规则<select disabled={busy || loading} value={copyRuleId} onChange={(event) => { setCopyRuleId(event.target.value); setCopyMapping({}); setCopyClear(false); setCopyError(""); }}>
            <option value="">选择规则</option>{rules.filter((rule) => ruleCanBeUsed(rule, copyKind === "public" ? "" : user?.id ?? "", copyKind,
              copyKind === "public" ? "public" : "hidden", copyKind === "private" && user?.role === "admin"))
              .map((rule) => <option key={rule.id} value={rule.id}>{rule.name} · {rule.revision}</option>)}
          </select></label>
        </div>
        {sourceRule && copyTargetRule && sourceRule.id !== copyTargetRule.id && <RarityMapping previous={sourceRule} next={copyTargetRule}
          mapping={copyMapping} onChange={setCopyMapping} clearUnmapped={copyClear} onClearUnmapped={setCopyClear} />}
        {copyPreparing && !rules.some((rule) => ruleCanBeUsed(rule, copyKind === "public" ? "" : user?.id ?? "", copyKind,
          copyKind === "public" ? "public" : "hidden", copyKind === "private" && user?.role === "admin")) &&
          <p className="muted">没有可用于此副本类型的规则。<Link to="/rules/">前往规则页查看或创建规则</Link>。</p>}
        {copyError && <p className="form-error" role="alert">{copyError}</p>}
        <div className="button-row"><button type="button" className="primary-button" disabled={busy || loading || !copyName.trim() || !copyRuleId}
          onClick={() => void copy()}>保存副本</button>
          <button type="button" disabled={busy || loading} onClick={() => { setCopyPreparing(false); setCopyError(""); }}>取消复制</button></div>
      </div>}
    </section>}
    {(error || Object.keys(serverFields).length > 0) && <FormFeedback
      error={[error, ...fieldFeedback.general].filter(Boolean).join("；")}
      issues={fieldFeedback.issues} />}
    {message && <p className="success-note" role="status">{message}</p>}
  </div>;
}
