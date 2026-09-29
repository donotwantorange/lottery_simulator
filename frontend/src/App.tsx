import { useState, type FormEvent, type MouseEvent } from "react";
import { Link, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { ApiError, recordUserActivity } from "./api/client";
import { useAuth } from "./auth/AuthProvider";
import { Login } from "./pages/Login";
import { Pools } from "./pages/Pools";
import { NewExperiment } from "./pages/NewExperiment";
import { Results } from "./pages/Results";
import { History } from "./pages/History";
import { Management } from "./pages/Management";
import { ChangePassword } from "./components/ChangePassword";

const pageInfo = {
  "/experiments/new/": { title: "新建实验", description: "选择角色池并设置本次模拟参数。" },
  "/pools/": { title: "角色池", description: "管理可用角色池和来源信息。" },
  "/results/": { title: "实验结果", description: "查看当前任务状态与模拟结果。" },
  "/history/": { title: "历史记录", description: "查找并管理已完成的实验。" },
  "/management/": { title: "管理员", description: "管理账号、实验配置和任务。" },
} as const;

function ChangePasswordForm() {
  const { changePassword } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      await changePassword(current, next);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "修改失败，请稍后重试");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="panel narrow-panel">
      <p className="eyebrow">首次登录</p><h1>请先修改密码</h1>
      <p className="muted">修改成功后需要重新登录。</p>
      <form className="stack-form" onSubmit={submit}>
        <label>当前密码<input type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} required /></label>
        <label>新密码（至少 6 个字符）<input type="password" autoComplete="new-password" minLength={6} value={next} onChange={(event) => setNext(event.target.value)} required /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button" disabled={pending}>{pending ? "正在保存…" : "修改密码"}</button>
      </form>
    </section>
  );
}

function ProtectedLayout() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <main className="loading-state">正在恢复登录状态…</main>;
  if (!user) return <Navigate to="/accounts/login/" replace state={{ from: location.pathname }} />;
  if (user.must_change_password) return <main className="app-frame"><ChangePasswordForm /></main>;
  return <Outlet />;
}

function AppShell() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [passwordOpen, setPasswordOpen] = useState(false);
  const activePage = pageInfo[location.pathname as keyof typeof pageInfo];
  function noteClick(event: MouseEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest("button[aria-label='退出登录']")) return;
    recordUserActivity();
  }
  return (
    <div className="app-frame" onClickCapture={noteClick} onChangeCapture={recordUserActivity}>
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">L</span><span>抽卡模拟器</span></div>
        <nav aria-label="主导航">
          <Link to="/experiments/new/">新建实验</Link><Link to="/pools/">角色池</Link>
          <Link to="/results/">实验结果</Link><Link to="/history/">历史记录</Link>
          {user?.role === "admin" && <Link to="/management/">管理员</Link>}
        </nav>
        <div className="account-card">
          <span className="avatar">{user?.username.slice(0, 1).toUpperCase()}</span>
          <span className="account-copy"><strong>{user?.username}</strong><small>{user?.role === "admin" ? "管理员" : "普通用户"}</small></span>
          <button className="quiet-button" onClick={() => setPasswordOpen(true)} aria-label="修改密码" title="修改密码">⚿</button>
          <button className="quiet-button" onClick={() => void logout().catch(() => undefined)} aria-label="退出登录" title="退出登录">↗</button>
        </div>
      </aside>
      <main className="workspace">
        <header className="page-heading"><div><p className="eyebrow">工作台</p><h1>{activePage?.title ?? "抽卡模拟器"}</h1><p className="muted">{activePage?.description}</p></div></header>
        <Outlet />
      </main>
      {passwordOpen && <div className="dialog-backdrop"><ChangePassword onClose={() => setPasswordOpen(false)} /></div>}
    </div>
  );
}

function LoginRoute() {
  const { user, loading } = useAuth();
  if (loading) return <main className="loading-state">正在恢复登录状态…</main>;
  if (user) return <Navigate to="/experiments/new/" replace />;
  return <Login />;
}

function ManagementRoute() {
  const { user } = useAuth();
  return user?.role === "admin" ? <Management /> : <Navigate to="/" replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/accounts/login/" element={<LoginRoute />} />
      <Route element={<ProtectedLayout />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/experiments/new/" replace />} />
          <Route path="/experiments/new/" element={<NewExperiment />} />
          <Route path="/pools/" element={<Pools />} />
          <Route path="/results/" element={<Results />} />
          <Route path="/history/" element={<History />} />
          <Route path="/management/" element={<ManagementRoute />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
