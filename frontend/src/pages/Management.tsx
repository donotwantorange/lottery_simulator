import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest, errorMessage } from "../api/client";
import type { ExperimentConfig, JobSummary, Page } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { AccountEditor, type AccountValues, type ManagedAccount } from "../components/AccountEditor";
import { DeleteAccountDialog } from "../components/DeleteAccountDialog";

interface ManagedJob extends JobSummary { owner_id: string; owner_name: string }
interface JobPage<T> { items: T[]; total: number; page: number; page_size: number }

function PageButtons<T>({ data, onPage }: { data: Page<T> | JobPage<T> | null; onPage: (page: number) => void }) {
  if (!data) return null;
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  return <div className="button-row"><button disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}>上一页</button><span className="muted">第 {data.page}/{pages} 页</span><button disabled={data.page >= pages} onClick={() => onPage(data.page + 1)}>下一页</button></div>;
}

export function Management() {
  const { user, sessionGeneration } = useAuth();
  const [users, setUsers] = useState<Page<ManagedAccount> | null>(null);
  const [configs, setConfigs] = useState<Page<ExperimentConfig> | null>(null);
  const [jobs, setJobs] = useState<JobPage<ManagedJob> | null>(null);
  const [userPage, setUserPage] = useState(1);
  const [configPage, setConfigPage] = useState(1);
  const [jobPage, setJobPage] = useState(1);
  const [editing, setEditing] = useState<ManagedAccount | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<ManagedAccount | null>(null);
  const [resetting, setResetting] = useState("");
  const [password, setPassword] = useState("");
  const [confirmConfig, setConfirmConfig] = useState<ExperimentConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (user?.role !== "admin") return;
    const controller = new AbortController();
    setUsers(null); setConfigs(null); setJobs(null); setError("");
    const query = (page: number) => `page=${page}&page_size=50`;
    void Promise.all([
      apiRequest<Page<ManagedAccount>>(`management/users/?${query(userPage)}`, {}, controller.signal),
      apiRequest<Page<ExperimentConfig>>(`experiment-configs/?${query(configPage)}`, {}, controller.signal),
      apiRequest<JobPage<ManagedJob>>(`management/jobs/?${query(jobPage)}`, {}, controller.signal),
    ]).then(([nextUsers, nextConfigs, nextJobs]) => {
      if (controller.signal.aborted) return;
      setUsers(nextUsers); setConfigs(nextConfigs); setJobs(nextJobs);
    }).catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [user?.role, user?.id, sessionGeneration, userPage, configPage, jobPage, reload]);

  async function saveAccount(values: AccountValues) {
    setBusy(true); setError(""); setNotice("");
    try {
      if (editing) {
        // This explicit business-field allowlist must never grow into framework fields.
        const payload = { username: values.username, role: values.role, enabled: values.enabled };
        await apiRequest<ManagedAccount>(`management/users/${editing.id}/`, { method: "PATCH", body: JSON.stringify(payload) });
        setNotice("账号已更新。用户名、角色或启用状态变化会使原会话失效；已启动任务继续运行。");
      } else {
        await apiRequest<ManagedAccount>("management/users/", { method: "POST", body: JSON.stringify({ username: values.username, password: values.password, role: values.role }) });
        setNotice("账号已创建，首次登录需要修改密码。");
      }
      setEditing(undefined); setReload((value) => value + 1);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function resetPassword(account: ManagedAccount) {
    if (!password || busy) return;
    setBusy(true); setError("");
    try {
      await apiRequest<void>(`management/users/${account.id}/reset-password/`, { method: "POST", body: JSON.stringify({ password }) });
      setResetting(""); setPassword(""); setNotice(`已重置 ${account.username} 的密码；该账号所有旧会话已失效。`);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function unlock(account: ManagedAccount) {
    if (busy || !window.confirm(`解除“${account.username}”的登录失败锁定？这不会启用被禁用的账号。`)) return;
    setBusy(true); setError("");
    try {
      await apiRequest<void>(`management/users/${account.id}/unlock-login/`, { method: "POST", body: JSON.stringify({}) });
      setNotice(`已解除 ${account.username} 的登录锁定；账号启用状态未改变。`);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function deleteConfig(config: ExperimentConfig) {
    if (busy || !confirmConfig || confirmConfig.id !== config.id) return;
    setBusy(true); setError("");
    try {
      await apiRequest<void>(`experiment-configs/${config.id}/`, { method: "DELETE", body: JSON.stringify({ expected_revision: config.revision }) });
      setConfirmConfig(null); setNotice(`已删除“${config.name}”实验配置。`); setReload((value) => value + 1);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function cancelJob(job: ManagedJob) {
    if (busy || !window.confirm(`向任务 ${job.job_id}（${job.owner_name}）发送停止请求？`)) return;
    setBusy(true); setError("");
    try {
      await apiRequest<void>(`jobs/${job.job_id}/cancel/`, { method: "POST", body: JSON.stringify({}) });
      setNotice("已向任务发送停止请求。"); setReload((value) => value + 1);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  if (user?.role !== "admin") return null;
  return <div className="page-stack">
    <section className="panel"><div className="section-heading"><div><h2>账号管理</h2><p className="muted">可用角色仅为普通用户和管理员。改名、改角色、禁用及改密会撤销旧会话。</p></div><button className="primary-button" onClick={() => setEditing(null)}>创建账号</button></div>
      {editing !== undefined && <AccountEditor account={editing} busy={busy} onSave={saveAccount} onCancel={() => setEditing(undefined)} />}
      {users ? <><div className="table-wrap"><table><thead><tr><th>用户名</th><th>角色</th><th>启用</th><th>状态</th><th>操作</th></tr></thead><tbody>{users.items.map((account) => <tr key={account.id}>
        <td>{account.username}</td><td>{account.role === "admin" ? "管理员" : "普通用户"}</td><td>{account.enabled ? "是" : "否"}</td><td>{account.deleting ? "删除待重试" : account.must_change_password ? "首次登录需改密" : "正常"}</td>
        <td className="management-actions"><button disabled={busy || account.deleting} onClick={() => setEditing(account)}>编辑</button><button disabled={busy} onClick={() => { setResetting(resetting === account.id ? "" : account.id); setPassword(""); }}>重置密码</button><button disabled={busy} onClick={() => void unlock(account)}>解锁登录</button><button className="danger-button" disabled={busy || account.id === user.id} onClick={() => setDeleting(account)}>删除</button></td>
      </tr>)}</tbody></table></div><PageButtons data={users} onPage={setUserPage} /></> : <p className="muted">正在加载账号…</p>}
      {resetting && users?.items.find((item) => item.id === resetting) && <form className="management-editor" onSubmit={(event) => { event.preventDefault(); const target = users.items.find((item) => item.id === resetting); if (target) void resetPassword(target); }}>
        <h3>重置密码：{users.items.find((item) => item.id === resetting)?.username}</h3><div className="field-grid"><label>新密码（至少6字符）<input type="password" autoComplete="new-password" minLength={6} value={password} onChange={(event) => setPassword(event.target.value)} required /></label></div><div className="button-row"><button className="primary-button" disabled={busy}>确认重置</button><button type="button" onClick={() => setResetting("")}>取消</button></div>
      </form>}
    </section>

    <section className="panel"><h2>实验配置管理</h2><p className="muted">展示所有用户的配置。删除需再次确认并按当前revision提交。</p>
      {configs ? <><div className="table-wrap"><table><thead><tr><th>名称</th><th>所有者</th><th>角色池</th><th>主抽 / 轮数</th><th>操作</th></tr></thead><tbody>{configs.items.map((config) => <tr key={config.id}><td>{config.name}</td><td>{config.owner_name}</td><td>{config.pool_ref.name}</td><td>{config.parameters.draws} / {config.parameters.trials}</td><td className="management-actions">{confirmConfig?.id === config.id ? <><span>确定删除？ </span><button className="danger-button" disabled={busy} onClick={() => void deleteConfig(config)}>确认删除</button><button disabled={busy} onClick={() => setConfirmConfig(null)}>取消</button></> : <><Link className="secondary-button" to={`/experiments/new/?config=${encodeURIComponent(config.id)}`}>编辑配置</Link><button className="danger-button" disabled={busy} onClick={() => setConfirmConfig(config)}>删除</button></>}</td></tr>)}</tbody></table></div><PageButtons data={configs} onPage={setConfigPage} /></> : <p className="muted">正在加载实验配置…</p>}
    </section>

    <section className="panel"><h2>任务管理</h2><p className="muted">任务列表由管理员专用接口分页返回；管理员可向活动任务发送停止请求。没有显示文件路径或跨用户任务数据给普通用户。</p>
      {jobs ? <><div className="table-wrap"><table><thead><tr><th>接受时间</th><th>用户</th><th>角色池</th><th>抽数 / 轮数</th><th>状态</th><th>操作</th></tr></thead><tbody>{jobs.items.map((job) => <tr key={job.job_id}><td>{new Date(job.accepted_at).toLocaleString()}</td><td>{job.owner_name}</td><td>{job.pool_name_snapshot}</td><td>{job.draws} / {job.trials}</td><td>{job.status} · {job.phase}</td><td>{["queued", "running"].includes(job.status) ? <button disabled={busy} onClick={() => void cancelJob(job)}>停止任务</button> : "—"}</td></tr>)}</tbody></table></div><PageButtons data={jobs} onPage={setJobPage} /></> : <p className="muted">正在加载任务…</p>}
    </section>
    {notice && <p className="success-note" role="status">{notice}</p>}{error && <p className="form-error" role="alert">{error}</p>}
    {deleting && <div className="dialog-backdrop"><DeleteAccountDialog key={deleting.id} account={deleting} onClose={() => setDeleting(null)} onDeleted={() => { setDeleting(null); setNotice("账号及其个人数据已删除。"); setReload((value) => value + 1); }} /></div>}
  </div>;
}
