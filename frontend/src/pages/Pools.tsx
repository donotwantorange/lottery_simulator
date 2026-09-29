import { useEffect, useMemo, useState } from "react";
import defaultPool from "../../../configs/pools/default.json";
import { apiRequest, errorMessage } from "../api/client";
import { saveSmallJson } from "../api/files";
import type { Page, Pool, PoolDocument } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ImportDialog } from "../components/ImportDialog";
import { PoolEditor } from "../components/PoolEditor";

function documentFrom(pool: Pool): PoolDocument {
  return { format_version: 2, id: pool.id, name: pool.name, original_author: pool.original_author,
    rule_name: "rule1", rarity_labels: structuredClone(pool.rarity_labels),
    pool_config: structuredClone(pool.pool_config) };
}

function validNumbers(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(validNumbers);
  if (value && typeof value === "object") return Object.values(value).every(validNumbers);
  return true;
}

export function Pools() {
  const { user, sessionGeneration } = useAuth();
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<Pool[]>([]);
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<Pool | null>(null);
  const [draft, setDraft] = useState<PoolDocument | null>(null);
  const [kind, setKind] = useState<"public" | "private">("private");
  const [visibility, setVisibility] = useState<"public" | "hidden">("hidden");
  const [copyName, setCopyName] = useState("");
  const [copyKind, setCopyKind] = useState<"public" | "private">("private");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load(signal?: AbortSignal) {
    const first = await apiRequest<Page<Pool>>("pools/?page=1&page_size=200", {}, signal);
    const rest = await Promise.all(Array.from({ length: Math.ceil(first.total / 200) - 1 }, (_, index) =>
      apiRequest<Page<Pool>>(`pools/?page=${index + 2}&page_size=200`, {}, signal)));
    setItems([...first.items, ...rest.flatMap((result) => result.items)]);
  }

  useEffect(() => {
    const controller = new AbortController();
    setItems([]);
    setSelected(null);
    setDraft(null);
    void load(controller.signal).catch((cause) => {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    });
    return () => controller.abort();
    // Session generation invalidates old-page results even if this route stays mounted.
  }, [user?.id, sessionGeneration]);

  function select(pool: Pool) {
    setSelected(pool);
    setDraft(documentFrom(pool));
    setKind(pool.kind);
    setVisibility(pool.visibility);
    setCopyName(`${pool.name}副本`);
    setError("");
    setMessage("");
  }

  function create() {
    const next = structuredClone(defaultPool) as PoolDocument;
    next.name = "新角色池";
    next.original_author = null;
    setSelected(null);
    setDraft(next);
    setKind("private");
    setVisibility("hidden");
    setError("");
    setMessage("");
  }

  async function save() {
    if (!draft || busy) return;
    if (!validNumbers(draft)) { setError("数值必须是有限数字"); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const payload = { ...draft, kind, visibility,
        ...(selected ? { expected_revision: selected.revision } : {}) };
      const saved = await apiRequest<Pool>(selected ? `pools/${selected.id}/` : "pools/",
        { method: selected ? "PATCH" : "POST", body: JSON.stringify(payload) });
      setSelected(saved);
      setDraft(documentFrom(saved));
      setKind(saved.kind);
      setVisibility(saved.visibility);
      setMessage("角色池已保存");
      await load();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function copy() {
    if (!selected || !copyName.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const result = await apiRequest<Pool>(`pools/${selected.id}/copy/`,
        { method: "POST", body: JSON.stringify({ name: copyName, kind: copyKind }) });
      select(result);
      setMessage("角色池已复制；新副本拥有独立ID和修订号");
      await load();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!selected || busy || !window.confirm(`确认删除“${selected.name}”？引用它的实验配置将失去池关联。`)) return;
    setBusy(true); setError("");
    try {
      await apiRequest<void>(`pools/${selected.id}/`,
        { method: "DELETE", body: JSON.stringify({ expected_revision: selected.revision }) });
      setSelected(null); setDraft(null); setMessage("角色池已删除");
      await load();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function exportSelected() {
    if (!selected) return;
    try {
      const document = await apiRequest<PoolDocument>(`pools/${selected.id}/export/?expected_revision=${selected.revision}`);
      saveSmallJson(document, "pool.json");
    } catch (cause) { setError(errorMessage(cause)); }
  }

  const filtered = useMemo(() => items.filter((pool) => filter === "all" ||
    (filter === "public" && pool.kind === "public") ||
    (filter === "mine" && pool.owner_id === user?.id) ||
    (filter === "shared" && pool.kind === "private" && pool.visibility === "public" && pool.owner_id !== user?.id) ||
    (filter === "private-all" && pool.kind === "private")), [items, filter, user?.id]);
  const visible = filtered.slice((page - 1) * 100, page * 100);
  const pageCount = Math.max(1, Math.ceil(filtered.length / 100));
  const canEdit = !!user && !!selected && (user.role === "admin" || selected.owner_id === user.id);

  return <div className="page-stack">
    <section className="panel">
      <div className="section-heading"><div><h2>角色池</h2><p className="muted">公共池、我的池及他人公开的私有池。列表为当前页，权限由服务端再次校验。</p></div>
        <div className="button-row"><button className="primary-button" onClick={create}>新建角色池</button>
          <ImportDialog label="导入池JSON" onImport={async (raw) => {
            const imported = await apiRequest<Pool>("pools/import/", { method: "POST", body: raw });
            select(imported); setMessage("已导入为当前账号的隐藏私有池"); await load();
          }} /></div></div>
      <label className="compact-field">筛选
        <select value={filter} onChange={(event) => { setFilter(event.target.value); setPage(1); }}>
          <option value="all">全部可见</option><option value="public">公共池</option><option value="mine">我的私有池</option>
          <option value="shared">他人公开池</option>{user?.role === "admin" && <option value="private-all">全部私有池</option>}
        </select></label>
      <div className="table-wrap"><table><thead><tr><th>名称</th><th>类型 / 可见性</th><th>所有者</th><th>最初作者</th><th>修订</th><th>操作</th></tr></thead><tbody>
        {visible.map((pool) => <tr key={pool.id}><td>{pool.name}</td><td>{pool.kind === "public" ? "公共池" : pool.visibility === "public" ? "公开私有池" : "隐藏私有池"}</td>
          <td>{pool.owner_name ?? "—"}</td><td>{pool.original_author}</td><td>{pool.revision}</td>
          <td><button className="link-button" onClick={() => select(pool)}>{user?.role === "admin" || pool.owner_id === user?.id ? "编辑" : "查看 / 复制"}</button></td></tr>)}
      </tbody></table></div>
      {visible.length === 0 && <p className="muted">当前筛选没有角色池。</p>}
      <div className="button-row"><button disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} / {pageCount} 页 · 当前筛选 {filtered.length} 个</span><button disabled={page >= pageCount} onClick={() => setPage(page + 1)}>下一页</button></div>
    </section>
    {draft && <section className="panel"><div className="section-heading"><div><h2>{selected ? "角色池详情" : "新建角色池"}</h2><p className="muted">规则与名单只在点击保存时持久化。</p></div>
      {selected && <div className="button-row"><button onClick={() => void exportSelected()}>导出JSON</button>{canEdit && <button className="danger-button" disabled={busy} onClick={() => void remove()}>删除池</button>}</div>}</div>
      <fieldset disabled={!!selected && !canEdit} className="plain-fieldset"><PoolEditor value={draft} kind={kind} visibility={visibility} canCreatePublic={user?.role === "admin"} editing={!!selected}
        onChange={setDraft} onKind={setKind} onVisibility={setVisibility} /></fieldset>
      {(!selected || canEdit) && <button className="primary-button" disabled={busy} onClick={() => void save()}>{busy ? "处理中…" : selected ? "保存修改" : "创建角色池"}</button>}
      {selected && <div className="editor-section"><h3>复制为新池</h3><div className="field-grid"><label>新名称<input value={copyName} onChange={(event) => setCopyName(event.target.value)} /></label>
        <label>类型<select value={copyKind} onChange={(event) => setCopyKind(event.target.value as "private" | "public")}><option value="private">隐藏私有池</option>{user?.role === "admin" && <option value="public">公共池</option>}</select></label></div>
        <button disabled={busy || !copyName.trim()} onClick={() => void copy()}>复制</button></div>}
    </section>}
    {error && <p className="form-error" role="alert">{error}。若提示修订冲突，请重新选择角色池后再修改。</p>}
    {message && <p className="success-note" role="status">{message}</p>}
  </div>;
}
