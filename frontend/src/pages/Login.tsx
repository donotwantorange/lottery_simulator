import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

export function Login() {
  const { login, notice, logoutPending } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (logoutPending) {
      setError("正在退出登录，请稍后再试");
      return;
    }
    setPending(true);
    setError("");
    try {
      await login(username, password);
      navigate("/experiments/new/", { replace: true });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "登录失败，请稍后重试");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <p className="eyebrow">LOTTERY SIMULATOR</p>
        <h1>登录</h1>
        {notice && <p className="form-error" role="alert">{notice}</p>}
        {logoutPending && <p className="muted" role="status">正在退出登录…</p>}
        <label>用户名<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
        <label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={pending || logoutPending}>
          {logoutPending ? "正在退出…" : pending ? "正在登录…" : "登录"}
        </button>
      </form>
    </main>
  );
}
