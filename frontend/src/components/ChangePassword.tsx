import { useState, type FormEvent } from "react";
import { ApiError, errorMessage } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

export function ChangePassword({ onClose }: { onClose: () => void }) {
  const { changePassword } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    try { await changePassword(current, next); }
    catch (cause) {
      setError(cause instanceof ApiError && cause.status === 401 ? "会话已失效，请重新登录。" : errorMessage(cause));
    } finally { setBusy(false); }
  }

  return <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="change-password-title">
    <h2 id="change-password-title">修改密码</h2>
    <p>保存后当前会话会退出，请使用新密码重新登录。</p>
    <form className="stack-form" onSubmit={(event) => void submit(event)}>
      <label>当前密码<input type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} required /></label>
      <label>新密码（至少6字符）<input type="password" autoComplete="new-password" minLength={6} value={next} onChange={(event) => setNext(event.target.value)} required /></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="button-row"><button className="primary-button" disabled={busy}>{busy ? "正在保存…" : "修改并退出"}</button><button type="button" disabled={busy} onClick={onClose}>取消</button></div>
    </form>
  </section>;
}
