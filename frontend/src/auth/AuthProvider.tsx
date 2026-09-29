import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  apiRequest,
  clearPrivateSession,
  currentSessionGeneration,
  invalidateSessionRequests,
  refreshCsrfToken,
  subscribeToAuthExpiry,
} from "../api/client";
import type { AuthUser } from "../api/types";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  sessionGeneration: number;
  notice: string;
  logoutPending: boolean;
  login(username: string, password: string): Promise<AuthUser>;
  logout(): Promise<void>;
  changePassword(currentPassword: string, newPassword: string): Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [logoutPending, setLogoutPending] = useState(false);
  const [sessionGeneration, setSessionGeneration] = useState(currentSessionGeneration);
  const logoutInFlight = useRef(false);

  const clearUser = useCallback(() => {
    setUser(null);
    setSessionGeneration(currentSessionGeneration());
  }, []);

  useEffect(() => subscribeToAuthExpiry(clearUser), [clearUser]);

  useEffect(() => () => {
    invalidateSessionRequests();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const generation = currentSessionGeneration();
    void (async () => {
      try {
        await refreshCsrfToken(controller.signal);
        const me = await apiRequest<AuthUser>("auth/me/", {}, controller.signal);
        if (generation === currentSessionGeneration()) setUser(me);
      } catch (error) {
        if (
          !(error instanceof ApiError && error.status === 401) &&
          !controller.signal.aborted &&
          generation === currentSessionGeneration()
        ) {
          setUser(null);
        }
      } finally {
        if (!controller.signal.aborted) {
          setSessionGeneration(currentSessionGeneration());
          setLoading(false);
        }
      }
    })();
    return () => controller.abort();
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    if (logoutInFlight.current) throw new Error("正在退出登录，请稍后再试");
    const generation = invalidateSessionRequests();
    setUser(null);
    setNotice("");
    setSessionGeneration(generation);
    const loggedIn = await apiRequest<AuthUser>("auth/login/", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    await refreshCsrfToken();
    if (generation !== currentSessionGeneration()) throw new Error("登录状态已变化，请重试");
    setUser(loggedIn);
    setLoading(false);
    return loggedIn;
  }, []);

  const logout = useCallback(async () => {
    if (logoutInFlight.current) return;
    logoutInFlight.current = true;
    setLogoutPending(true);
    const generation = invalidateSessionRequests();
    setUser(null);
    setNotice("");
    setSessionGeneration(generation);
    try {
      await apiRequest<void>("auth/logout/", { method: "POST" });
    } catch (error) {
      setNotice("本页登录状态已清除，但服务端未确认退出。请关闭此页面，或重新登录后再试。");
      throw error;
    } finally {
      if (generation === currentSessionGeneration()) clearUser();
      logoutInFlight.current = false;
      setLogoutPending(false);
    }
  }, [clearUser]);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    await apiRequest<void>("auth/change-password/", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    clearPrivateSession();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, sessionGeneration, notice, logoutPending, login, logout, changePassword }),
    [user, loading, sessionGeneration, notice, logoutPending, login, logout, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return context;
}
