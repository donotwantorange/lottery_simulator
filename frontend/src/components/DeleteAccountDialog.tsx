import { useEffect, useState } from "react";
import { apiRequest, errorMessage } from "../api/client";
import type { ManagedAccount } from "./AccountEditor";

interface DeleteImpact {
  private_pools: string;
  experiment_configs: string;
  runs: string;
  job_directories: string;
  export_files: string;
  other_users_pool_references: string;
  public_pools_preserved: string;
}

export function DeleteAccountDialog({ account, onClose, onDeleted }: {
  account: ManagedAccount;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [impact, setImpact] = useState<DeleteImpact | null>(null);
  const [previewFor, setPreviewFor] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setImpact(null);
    setPreviewFor(null);
    setConfirmed(false);
    setError("");
    void apiRequest<{ delete_impact: DeleteImpact }>(`management/users/${account.id}/`, {}, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setImpact(value.delete_impact);
          setPreviewFor(account.id);
        }
      })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [account.id]);

  async function remove() {
    if (!confirmed || !impact || previewFor !== account.id || busy) return;
    setBusy(true); setError("");
    try {
      await apiRequest<void>(`management/users/${account.id}/`, { method: "DELETE", body: JSON.stringify({ confirm: true }) });
      onDeleted();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  return <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-account-title">
    <h2 id="delete-account-title">删除账号“{account.username}”</h2>
    <p>将停止该账号的活动任务，并清理其个人数据。若任务、文件或数据库清理未完成，账号会保持阻止状态，可重新尝试删除。</p>
    {impact && previewFor === account.id ? <dl className="impact-list">
      <dt>私有角色池（含公开的私有池）</dt><dd>{impact.private_pools}</dd>
      <dt>实验配置</dt><dd>{impact.experiment_configs}</dd>
      <dt>历史记录</dt><dd>{impact.runs}</dd>
      <dt>任务目录</dt><dd>{impact.job_directories}</dd>
      <dt>导出临时文件</dt><dd>{impact.export_files}</dd>
      <dt>其他用户受影响的池引用</dt><dd>{impact.other_users_pool_references}</dd>
      <dt>保留的系统公共池</dt><dd>{impact.public_pools_preserved}</dd>
    </dl> : <p className="muted">正在读取删除范围…</p>}
    <label className="inline-check"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />我已核对范围，并确认删除账号及其个人数据</label>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="button-row"><button className="danger-button" disabled={!impact || previewFor !== account.id || !confirmed || busy} onClick={() => void remove()}>{busy ? "正在删除…" : "确认删除"}</button><button disabled={busy} onClick={onClose}>取消</button></div>
  </section>;
}
