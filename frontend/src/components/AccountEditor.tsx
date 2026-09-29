import { useEffect, useState, type FormEvent } from "react";
import type { UserRole } from "../api/types";

export interface ManagedAccount {
  id: string;
  username: string;
  role: UserRole;
  enabled: boolean;
  deleting: boolean;
  must_change_password: boolean;
}

export interface AccountValues {
  username: string;
  role: UserRole;
  enabled: boolean;
  password: string;
}

export function AccountEditor({ account, onSave, onCancel, busy }: {
  account: ManagedAccount | null;
  onSave: (values: AccountValues) => Promise<void>;
  onCancel: () => void;
  busy: boolean;
}) {
  const [username, setUsername] = useState(account?.username ?? "");
  const [role, setRole] = useState<UserRole>(account?.role ?? "user");
  const [enabled, setEnabled] = useState(account?.enabled ?? true);
  const [password, setPassword] = useState("");

  useEffect(() => {
    setUsername(account?.username ?? "");
    setRole(account?.role ?? "user");
    setEnabled(account?.enabled ?? true);
    setPassword("");
  }, [account]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSave({ username, role, enabled, password });
  }

  return <form className="management-editor" onSubmit={(event) => void submit(event)}>
    <h3>{account ? `编辑账号：${account.username}` : "创建账号"}</h3>
    <div className="field-grid">
      <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} required maxLength={64} /></label>
      <label>角色<select value={role} onChange={(event) => setRole(event.target.value as UserRole)}><option value="user">普通用户</option><option value="admin">管理员</option></select></label>
      {account ? <label className="inline-check"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />账号已启用</label>
        : <label>初始密码（至少6字符）<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" minLength={6} required /></label>}
    </div>
    <p className="muted">管理员设置或重置的密码会要求用户首次登录时修改。</p>
    <div className="button-row"><button className="primary-button" disabled={busy}>{busy ? "正在保存…" : account ? "保存账号" : "创建账号"}</button><button type="button" disabled={busy} onClick={onCancel}>取消</button></div>
  </form>;
}
