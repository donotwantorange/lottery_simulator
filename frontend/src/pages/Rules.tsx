import { useEffect, useState, type FormEvent } from "react";
import defaultRule from "../../../configs/rules/zmd.json";
import { ApiError, apiRequest, errorMessage } from "../api/client";
import type { Page, Rule, RuleDocument } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ImportDialog } from "../components/ImportDialog";
import { RuleEditor } from "../components/RuleEditor";

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

export function Rules() {
  const { user, sessionGeneration } = useAuth();
  const [scope, setScope] = useState<Scope>("all");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<Page<Rule>>({ items: [], total: 0, page: 1, page_size: 50 });
  const [selected, setSelected] = useState<Rule | null>(null);
  const [draft, setDraft] = useState<RuleDocument | null>(null);
  const [name, setName] = useState("");
  const [visibility, setVisibility] = useState<"hidden" | "public">("hidden");
  const [kind, setKind] = useState<"private" | "public">("private");
  const [mode, setMode] = useState<Mode>("view");
  const [editorValid, setEditorValid] = useState(true);
  const [copyName, setCopyName] = useState("");
  const [copyKind, setCopyKind] = useState<"private" | "public">("private");
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [editorInstance, setEditorInstance] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load(signal?: AbortSignal) {
    const query = new URLSearchParams({ scope, page: String(page), page_size: "50" });
    const response = await apiRequest<Page<Rule>>(`rules/?${query}`, {}, signal);
    if (!signal?.aborted) setResult(response);
  }

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setResult({ items: [], total: 0, page, page_size: 50 });
    setSelected(null);
    setDraft(null);
    setImportPreview(null);
    void load(controller.signal).catch((cause) => {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    }).finally(() => { if (!controller.signal.aborted) setIsLoading(false); });
    return () => controller.abort();
    // API requests also fence on session generation; this route can remain mounted across account changes.
  }, [scope, page, user?.id, sessionGeneration]);

  function open(rule: Rule, nextMode: Mode) {
    setEditorInstance((value) => value + 1);
    setSelected(rule);
    setDraft(structuredClone(rule.document));
    setName(rule.name);
    setVisibility(rule.visibility);
    setKind(rule.kind);
    setMode(nextMode);
    setEditorValid(true);
    setCopyName(`${rule.name}副本`);
    setCopyKind("private");
    setImportPreview(null);
    setError("");
    setMessage("");
  }

  function create() {
    setEditorInstance((value) => value + 1);
    setSelected(null);
    setDraft(newDocument());
    setName("新规则");
    setVisibility("hidden");
    setKind("private");
    setMode("edit");
    setEditorValid(true);
    setError("");
    setMessage("");
    setImportPreview(null);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || busy || !event.currentTarget.reportValidity() || !editorValid) return;
    setBusy(true); setError(""); setMessage("");
    const document = { ...draft, name: name.trim() };
    try {
      const saved = await apiRequest<Rule>(selected ? `rules/${selected.id}/` : "rules/", {
        method: selected ? "PATCH" : "POST",
        body: JSON.stringify(selected
          ? { document, name: name.trim(), visibility, expected_revision: selected.revision }
          : { ...document, kind, visibility }),
      });
      open(saved, "edit");
      setMessage("规则已保存。引用它的角色池会在下一次模拟使用新设置。");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === "revision_conflict") {
        setError("规则已被其他操作修改。你的草稿仍保留；可继续编辑，或手动重新加载最新版本。");
      } else setError(errorMessage(cause));
    } finally { setBusy(false); }
  }

  async function reloadLatest() {
    if (!selected || busy) return;
    setBusy(true); setError("");
    try { open(await apiRequest<Rule>(`rules/${selected.id}/`), "edit"); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function copy() {
    if (!selected || !copyName.trim() || busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const copied = await apiRequest<Rule>(`rules/${selected.id}/copy/`, {
        method: "POST", body: JSON.stringify({ name: copyName.trim(), kind: copyKind }),
      });
      open(copied, "edit");
      setMessage("规则已复制；最初作者署名已保留。");
      await load();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!selected || busy || !window.confirm(`确认删除规则“${selected.name}”？`)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await apiRequest<void>(`rules/${selected.id}/`, {
        method: "DELETE", body: JSON.stringify({ expected_revision: selected.revision }),
      });
      setSelected(null); setDraft(null); setMessage("规则已删除。"); await load();
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
    if (busy) return;
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
      setImportPreview(null); open(imported, "edit");
      setMessage("已导入为当前账号的隐藏私有规则。"); await load();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  const editable = selected ? canEdit(selected, user) : true;
  const pageCount = Math.max(1, Math.ceil(result.total / result.page_size));

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
      <div className="table-wrap"><table><thead><tr><th>名称</th><th>类型 / 可见性</th><th>作者</th><th>修订</th><th>引用池</th><th>操作</th></tr></thead><tbody>
        {result.items.map((rule) => <tr key={rule.id}>
          <td>{rule.name}</td><td>{rule.kind === "public" ? "公共规则" : rule.visibility === "public" ? "公开私有规则" : "隐藏私有规则"}</td>
          <td>{rule.original_author}</td><td>{rule.revision}</td><td>{rule.reference_count}</td>
          <td><div className="rule-table-actions"><button className="link-button" disabled={busy || isLoading} onClick={() => open(rule, "view")}>查看</button>
            {canEdit(rule, user) && <button className="link-button" disabled={busy || isLoading} onClick={() => open(rule, "edit")}>编辑</button>}
          </div></td></tr>)}
      </tbody></table></div>
      {isLoading ? <p className="muted" role="status">正在加载规则…</p> : result.items.length === 0 && <p className="muted">当前筛选没有规则。</p>}
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
      <form className="stack-form" onSubmit={(event) => void save(event)}>
        <fieldset disabled={!editable || busy || mode === "view"} className="plain-fieldset">
          <div className="field-grid">
            <label>规则名称<input value={name} onChange={(event) => setName(event.target.value)} maxLength={255} required /></label>
            {!selected && <label>规则类型<select value={kind} onChange={(event) => setKind(event.target.value as "private" | "public")}>
              <option value="private">私有</option>{user?.role === "admin" && <option value="public">公共</option>}
            </select></label>}
            {kind === "private" && <label>可见性<select value={visibility} onChange={(event) => setVisibility(event.target.value as "hidden" | "public")}>
              <option value="hidden">隐藏</option><option value="public">公开可见</option>
            </select></label>}
          </div>
          <RuleEditor key={editorInstance} value={draft} onChange={setDraft} structureLocked={!!selected?.structure_locked}
            disabled={!editable || busy || mode === "view"} onValidityChange={setEditorValid} />
        </fieldset>
        {editable && mode === "edit" && <button className="primary-button" type="submit" disabled={busy || !editorValid}>
          {busy ? "处理中…" : selected ? "保存修改" : "创建规则"}
        </button>}
      </form>
      {selected && <div className="editor-section"><h3>复制为新规则</h3><p className="muted">复制会新建独立规则，并保留最初作者署名。</p>
        <div className="field-grid"><label>新名称<input disabled={busy || isLoading} value={copyName} onChange={(event) => setCopyName(event.target.value)} /></label>
          <label>类型<select disabled={busy || isLoading} value={copyKind} onChange={(event) => setCopyKind(event.target.value as "private" | "public")}>
            <option value="private">私有</option>{user?.role === "admin" && <option value="public">公共</option>}
          </select></label></div>
        <button disabled={busy || isLoading || !copyName.trim()} onClick={() => void copy()}>复制规则</button>
      </div>}
    </section>}
    {error && <p className="form-error" role="alert">{error}{error.includes("草稿仍保留") && selected &&
      <> <button className="link-button" disabled={busy} onClick={() => void reloadLatest()}>重新加载最新版本</button></>}</p>}
    {message && <p className="success-note" role="status">{message}</p>}
  </div>;
}
