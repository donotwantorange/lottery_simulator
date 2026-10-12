import { useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import defaultRule from "../../../configs/rules/zmd.json";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { Page, Rule, RuleDocument } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ImportDialog } from "../components/ImportDialog";
import { RuleEditor, RuleReadOnly } from "../components/RuleEditor";
import { FormFeedback, apiFieldIssues, type FieldIssue } from "../components/FormFeedback";
import { confirmDiscard, useEditorDraft, useUnsavedNavigation } from "../hooks/useEditorDraft";

type Scope = "all" | "public" | "mine" | "others_public" | "all_private";
type Mode = "view" | "edit";
interface ImportPreview { document: RuleDocument; requestBody: string }

function newDocument(): RuleDocument {
  const document = structuredClone(defaultRule) as RuleDocument;
  document.name = "新规则";
  document.original_author = null;
  return document;
}

function wrappedDocument(raw: string): string {
  return `{"document":${raw.trim()}}`;
}

function canEdit(rule: Rule, user: { id: string; role: string } | null): boolean {
  return !!user && (user.role === "admin" ||
    (rule.kind === "private" && rule.owner_id === user.id));
}

function ruleServerIssues(fields: Record<string, string>, document: RuleDocument | null): { issues: FieldIssue[]; other: string[] } {
  const issues: FieldIssue[] = [];
  const other: string[] = [];
  const fieldNames: Record<string, string> = { base_probability: "基础概率", soft_start: "连续未获得次数", soft_step: "每抽增幅", hard_pity: "硬保底抽数" };
  const fieldSuffix: Record<string, string> = { base_probability: "probability", soft_start: "soft-start", soft_step: "soft-step", hard_pity: "hard-pity" };
  const simple: Record<string, [string, string]> = {
    name: ["rule-name", "规则名称"], "big_pity.hard_pity": ["big-pity:count", "大保底抽数"],
    "bonus.at_main_draw": ["bonus:at", "触发主抽位置"], "bonus.draws": ["bonus:draws", "赠送抽数"],
    "grant.period": ["grant:period", "触发周期"], "grant.quantity": ["grant:quantity", "直接赠送数量"],
  };
  for (const [rawPath, message] of Object.entries(fields)) {
    const path = rawPath.replace(/^document\./, "");
    let target = simple[path];
    const match = /^(rarities|bonus\.rarities)\.(\d+)\.(base_probability|soft_start|soft_step|hard_pity)$/.exec(path);
    if (match && document) {
      const bonus = match[1] === "bonus.rarities";
      const rarity = (bonus ? document.bonus.rarities : document.rarities)[Number(match[2])];
      if (rarity) {
        const name = document.rarities.find((item) => item.id === rarity.id)?.name ?? rarity.name;
        target = [`${bonus ? "bonus" : "main"}:${rarity.id}:${fieldSuffix[match[3]]}`, `${name}${bonus ? "赠送池" : ""}${fieldNames[match[3]]}`];
      }
    }
    if (target) issues.push({ id: target[0], label: target[1], message });
    else other.push(message);
  }
  return { issues, other };
}

export function Rules() {
  const { user, sessionGeneration } = useAuth();
  const { ruleId } = useParams();
  const [scope, setScope] = useState<Scope>("all");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<Page<Rule>>({ items: [], total: 0, page: 1, page_size: 50 });
  const [selected, setSelected] = useState<Rule | null>(null);
  const { value: draft, setValue: setDraft, dirty: documentDirty, reset: resetDraft, setUnfinished } = useEditorDraft<RuleDocument | null>(null);
  const [savedMeta, setSavedMeta] = useState({ name: "", visibility: "hidden", kind: "private" });
  const [name, setName] = useState("");
  const [visibility, setVisibility] = useState<"hidden" | "public">("hidden");
  const [kind, setKind] = useState<"private" | "public">("private");
  const [mode, setMode] = useState<Mode>("view");
  const [editorValid, setEditorValid] = useState(true);
  const [copyName, setCopyName] = useState("");
  const [copyKind, setCopyKind] = useState<"private" | "public">("private");
  const [copyPreparing, setCopyPreparing] = useState(false);
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [editorInstance, setEditorInstance] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [serverFields, setServerFields] = useState<Record<string, string>>({});
  const [revealServerField, setRevealServerField] = useState<string | null>(null);
  const [listError, setListError] = useState("");
  const [message, setMessage] = useState("");
  const actionEpoch = useRef(0);
  const dirty = mode === "edit" && (documentDirty || name !== savedMeta.name || visibility !== savedMeta.visibility || kind !== savedMeta.kind);
  useUnsavedNavigation(dirty);

  async function load(signal?: AbortSignal) {
    const query = new URLSearchParams({ scope, page: String(page), page_size: "50" });
    const response = await apiRequest<Page<Rule>>(`rules/?${query}`, {}, signal);
    if (!signal?.aborted) { setResult(response); setListError(""); }
  }

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setResult({ items: [], total: 0, page, page_size: 50 });
    void load(controller.signal).catch((cause) => {
      if (!controller.signal.aborted) setListError(errorMessage(cause));
    }).finally(() => { if (!controller.signal.aborted) setIsLoading(false); });
    return () => controller.abort();
    // API requests also fence on session generation; this route can remain mounted across account changes.
  }, [scope, page, user?.id, sessionGeneration]);

  useEffect(() => {
    actionEpoch.current += 1;
    setSelected(null); resetDraft(null); setImportPreview(null); setError("");
  }, [user?.id, sessionGeneration, resetDraft]);

  useEffect(() => {
    if (!ruleId) return;
    const controller = new AbortController();
    const epoch = ++actionEpoch.current;
    setError("");
    setIsLoading(true);
    void apiRequest<Rule>(`rules/${encodeURIComponent(ruleId)}/`, {}, controller.signal).then((rule) => {
      if (!controller.signal.aborted && epoch === actionEpoch.current) { setIsLoading(false); applyRule(rule, "view"); }
    }).catch((cause) => {
      if (!controller.signal.aborted && epoch === actionEpoch.current) {
        setSelected(null); resetDraft(null);
        setError(cause instanceof ApiError && cause.status === 403 ? "无权查看这条规则。" : cause instanceof ApiError && cause.status === 404 ? "这条规则不存在或已删除。" : errorMessage(cause));
      }
    }).finally(() => { if (!controller.signal.aborted && epoch === actionEpoch.current) setIsLoading(false); });
    return () => controller.abort();
  }, [ruleId, user?.id, sessionGeneration, resetDraft]);

  function applyRule(rule: Rule, nextMode: Mode) {
    actionEpoch.current += 1;
    setEditorInstance((value) => value + 1);
    setSelected(rule);
    resetDraft(structuredClone(rule.document));
    setName(rule.name);
    setVisibility(rule.visibility);
    setKind(rule.kind);
    setSavedMeta({ name: rule.name, visibility: rule.visibility, kind: rule.kind });
    setMode(nextMode);
    setEditorValid(true);
    setCopyName(`${rule.name}副本`);
    setCopyKind("private");
    setCopyPreparing(false);
    setImportPreview(null);
    setError("");
    setServerFields({});
    setRevealServerField(null);
    setMessage("");
  }

  function open(rule: Rule, nextMode: Mode) {
    if (!confirmDiscard(dirty)) return;
    applyRule(rule, nextMode);
  }

  function create() {
    if (!confirmDiscard(dirty)) return;
    actionEpoch.current += 1;
    setEditorInstance((value) => value + 1);
    setSelected(null);
    resetDraft(newDocument());
    setName("新规则");
    setVisibility("hidden");
    setKind("private");
    setSavedMeta({ name: "新规则", visibility: "hidden", kind: "private" });
    setMode("edit");
    setEditorValid(true);
    setError("");
    setServerFields({});
    setRevealServerField(null);
    setMessage("");
    setImportPreview(null);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || busy || !event.currentTarget.reportValidity() || !editorValid) return;
    const epoch = actionEpoch.current;
    setBusy(true); setError(""); setServerFields({}); setRevealServerField(null); setMessage("");
    const document = { ...draft, name: name.trim() };
    try {
      const saved = await apiRequest<Rule>(selected ? `rules/${selected.id}/` : "rules/", {
        method: selected ? "PATCH" : "POST",
        body: JSON.stringify(selected
          ? { document, name: name.trim(), visibility, expected_revision: selected.revision }
          : { ...document, kind, visibility }),
      });
      if (epoch !== actionEpoch.current) return;
      applyRule(saved, "edit");
      setMessage("规则已保存。引用它的角色池会在下一次模拟使用新设置。");
      await load();
    } catch (cause) {
      if (epoch !== actionEpoch.current) return;
      setServerFields(apiFieldIssues(cause));
      if (cause instanceof ApiError && cause.status === 403) {
        setMode("view");
        if (selected) {
          try {
            const readable = await apiRequest<Rule>(`rules/${selected.id}/`);
            if (epoch === actionEpoch.current) { applyRule(readable, "view"); setError("编辑权限已撤销，已切换为只读详情。"); }
          } catch {
            if (epoch === actionEpoch.current) { setSelected(null); resetDraft(null); setError("无权继续查看这条规则。"); }
          }
        }
      } else if (cause instanceof ApiError && cause.code === "revision_conflict") {
        setError("规则已被其他操作修改。你的草稿仍保留；可继续编辑，或手动重新加载最新版本。");
      } else setError(errorMessage(cause));
    } finally { setBusy(false); }
  }

  async function reloadLatest() {
    if (!selected || busy || !confirmDiscard(dirty)) return;
    setBusy(true); setError("");
    try { applyRule(await apiRequest<Rule>(`rules/${selected.id}/`), "edit"); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function copy() {
    if (!selected || !copyName.trim() || busy || !confirmDiscard(dirty)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const copied = await apiRequest<Rule>(`rules/${selected.id}/copy/`, {
        method: "POST", body: JSON.stringify({ name: copyName.trim(), kind: copyKind }),
      });
      applyRule(copied, "edit");
      setMessage("规则已复制；最初作者署名已保留。");
      await load();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!selected || busy || !confirmDiscard(dirty) || !window.confirm(`确认删除规则“${selected.name}”？`)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await apiRequest<void>(`rules/${selected.id}/`, {
        method: "DELETE", body: JSON.stringify({ expected_revision: selected.revision }),
      });
      setSelected(null); resetDraft(null); setMessage("规则已删除。"); await load();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function exportSelected() {
    if (!selected || busy || isLoading) return;
    setBusy(true); setError("");
    try {
      const latest = await apiRequest<Rule>(`rules/${selected.id}/`);
      if (latest.revision !== selected.revision) {
        setError("规则已发生变化，请重新加载后再导出。");
        return;
      }
      const link = document.createElement("a");
      link.href = `/api/v1/rules/${encodeURIComponent(selected.id)}/export/?expected_revision=${selected.revision}`;
      link.download = "rule.json";
      link.click();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function previewImport(raw: string) {
    if (busy || !confirmDiscard(dirty)) return;
    setBusy(true); setError(""); setMessage(""); setImportPreview(null);
    const requestBody = wrappedDocument(raw);
    try {
      const preview = await apiRequest<{ document: RuleDocument }>("rules/import/preview/", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: requestBody,
      });
      setImportPreview({ document: preview.document, requestBody });
    } catch (cause) { setError(errorMessage(cause)); throw cause; }
    finally { setBusy(false); }
  }

  async function confirmImport() {
    if (!importPreview || busy) return;
    setBusy(true); setError("");
    try {
      const imported = await apiRequest<Rule>("rules/import/confirm/", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: importPreview.requestBody,
      });
      setImportPreview(null); applyRule(imported, "edit");
      setMessage("已导入为当前账号的隐藏私有规则。"); await load();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  const editable = selected ? canEdit(selected, user) : true;
  const supported = !draft || (draft.format_version === 1 && draft.algorithm === "dynamic_probability" &&
    draft.big_pity?.target === "first_up" && ["disable_after_obtain", "reset_after_obtain"].includes(draft.big_pity.after_obtain) &&
    ["first_up", "pool_selected"].includes(draft.grant?.target));
  const pageCount = Math.max(1, Math.ceil(result.total / result.page_size));
  const serverIssues = ruleServerIssues(serverFields, draft);

  return <div className="page-stack">
    <section className="panel">
      <div className="section-heading"><div><h2>规则</h2>
        <p className="muted">这里决定怎么抽。修改共享规则后，引用它的池在下一次模拟使用新设置；本页不开始模拟。</p></div>
        <div className="button-row"><button className="primary-button" disabled={busy || isLoading} onClick={create}>新建规则</button>
          <ImportDialog label="导入规则JSON" disabled={busy || isLoading} onImport={previewImport} /></div>
      </div>
      <label className="compact-field">筛选
        <select disabled={busy || isLoading} value={scope} onChange={(event) => { setScope(event.target.value as Scope); setPage(1); }}>
          <option value="all">全部可见规则</option><option value="public">公共规则</option>
          <option value="mine">我的私有规则</option><option value="others_public">他人公开规则</option>
          {user?.role === "admin" && <option value="all_private">全部私有规则</option>}
        </select>
      </label>
      {listError && <FormFeedback error={`读取规则列表失败：${listError}`}><button type="button" onClick={() => { setIsLoading(true); void load().catch((cause) => setListError(errorMessage(cause))).finally(() => setIsLoading(false)); }}>重试读取</button></FormFeedback>}
      <div className="table-wrap"><table><thead><tr><th>名称</th><th>类型 / 可见性</th><th>作者</th><th>修订</th><th>引用池</th><th>操作</th></tr></thead><tbody>
        {result.items.map((rule) => <tr key={rule.id}>
          <td>{rule.name}</td><td>{rule.kind === "public" ? "公共规则" : rule.visibility === "public" ? "公开私有规则" : "隐藏私有规则"}</td>
          <td>{rule.original_author}</td><td>{rule.revision}</td><td>{rule.reference_count}</td>
          <td><div className="rule-table-actions"><button className="link-button" disabled={busy || isLoading} onClick={() => open(rule, "view")}>查看</button>
            {canEdit(rule, user) && <button className="link-button" disabled={busy || isLoading} onClick={() => open(rule, "edit")}>编辑</button>}
          </div></td></tr>)}
      </tbody></table></div>
      {isLoading ? <p className="muted" role="status">正在加载规则…</p> : !listError && result.items.length === 0 && <p className="muted">当前筛选没有规则。</p>}
      <div className="button-row"><button disabled={busy || isLoading || page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
        <span>第 {page} / {pageCount} 页 · 共 {result.total} 条</span>
        <button disabled={busy || isLoading || page >= pageCount} onClick={() => setPage(page + 1)}>下一页</button></div>
    </section>

    {importPreview && <section className="panel import-preview" aria-labelledby="rule-import-title">
      <h2 id="rule-import-title">确认导入规则</h2>
      <p>将“{importPreview.document.name}”导入为你的隐藏私有规则。原文件作者署名会保留。</p>
      <p className="muted">包含 {importPreview.document.rarities.length} 个稀有度；确认后才会保存。</p>
      <div className="button-row"><button className="primary-button" disabled={busy} onClick={() => void confirmImport()}>确认导入</button>
        <button disabled={busy || isLoading} onClick={() => setImportPreview(null)}>取消</button></div>
    </section>}

    {draft && <section className="panel">
      <div className="section-heading"><div><h2>{selected ? (mode === "edit" ? "编辑规则" : "规则详情") : "新建规则"}</h2>
        {selected && <p className="muted">修订 {selected.revision} · {selected.reference_count} 个可见引用池 · 最初作者：{selected.original_author}</p>}</div>
        {selected && <div className="button-row"><button disabled={busy || isLoading} onClick={() => void exportSelected()}>导出JSON</button>
          {editable && <button disabled={busy || isLoading || selected.structure_locked} title={selected.structure_locked ? "规则仍被角色池引用，不能删除" : undefined}
            className="danger-button" onClick={() => void remove()}>删除规则</button>}</div>}
      </div>
      {selected?.structure_locked && <p className="notice-note">此规则已有角色池引用，稀有度结构不能修改；如需调整结构，请复制为新规则。</p>}
      {!supported && <FormFeedback error="当前规则包含不支持的机制或版本，暂不能编辑保存。请刷新完整版本或导出原始详情。" />}
      {Object.keys(serverFields).length > 0 && <FormFeedback issues={serverIssues.issues.map((issue) => ({ ...issue, reveal: () => setRevealServerField(issue.id) }))}
        error={serverIssues.other.join("；")} />}
      {mode === "view" ? <div className="stack-form"><section className="editor-section"><h3>基本信息与权限</h3>
        <p className="muted">公共规则由管理员维护；私有规则设为公开后，其他用户可查看、绑定和复制，但不能编辑。</p>
        <p>规则名称：{name} · {kind === "public" ? "公共规则" : visibility === "public" ? "公开私有规则" : "隐藏私有规则"}</p>
        {editable && supported && <button type="button" onClick={() => setMode("edit")}>编辑此规则</button>}
      </section><RuleReadOnly value={draft} /></div> : <form className="stack-form" onSubmit={(event) => void save(event)}>
        <fieldset disabled={!editable || busy || !supported} className="plain-fieldset">
          <section className="editor-section"><h3>基本信息与权限</h3>
            <p className="muted">名称便于识别。公共规则由管理员维护；私有规则归创建者所有。私有规则设为公开后，其他用户可查看、绑定和复制，但不能编辑。</p>
          </section>
          <div className="field-grid">
            <label>规则名称<input id="rule-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={255} required /></label>
            {!selected && <label>规则类型<select value={kind} onChange={(event) => setKind(event.target.value as "private" | "public")}>
              <option value="private">私有</option>{user?.role === "admin" && <option value="public">公共</option>}
            </select></label>}
            {kind === "private" && <label>可见性<select value={visibility} onChange={(event) => setVisibility(event.target.value as "hidden" | "public")}>
              <option value="hidden">隐藏</option><option value="public">公开可见</option>
            </select></label>}
          </div>
          <RuleEditor key={editorInstance} value={draft} onChange={setDraft} structureLocked={!!selected?.structure_locked}
            disabled={!editable || busy || !supported} onValidityChange={setEditorValid} onPendingChange={setUnfinished} revealField={revealServerField} />
        </fieldset>
        {editable && mode === "edit" && <button className="primary-button" type="submit" disabled={busy || !editorValid || !supported}>
          {busy ? "处理中…" : selected ? "保存修改" : "创建规则"}
        </button>}
      </form>}
      {selected && <div className="editor-section"><h3>{copyPreparing ? `准备“${selected.name}”的副本` : "复制为新规则"}</h3><p className="muted">来源为已保存的第{selected.revision}版。保存副本时才创建新规则，最初作者署名保留。</p>
        {!copyPreparing ? <button type="button" disabled={busy} onClick={() => setCopyPreparing(true)}>准备副本</button> : <><div className="field-grid"><label>新名称<input disabled={busy || isLoading} value={copyName} onChange={(event) => setCopyName(event.target.value)} /></label>
          <label>类型<select disabled={busy || isLoading} value={copyKind} onChange={(event) => setCopyKind(event.target.value as "private" | "public")}>
            <option value="private">私有</option>{user?.role === "admin" && <option value="public">公共</option>}
          </select></label></div>
        <button type="button" disabled={busy || isLoading || !copyName.trim()} onClick={() => void copy()}>保存副本</button>
        <button type="button" disabled={busy} onClick={() => setCopyPreparing(false)}>取消准备</button></>}
      </div>}
    </section>}
    {error && <p className="form-error" role="alert">{error}{error.includes("草稿仍保留") && selected &&
      <> <button className="link-button" disabled={busy} onClick={() => void reloadLatest()}>重新加载最新版本</button></>}</p>}
    {message && <p className="success-note" role="status">{message}</p>}
  </div>;
}
