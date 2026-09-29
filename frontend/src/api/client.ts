import type { ApiErrorPayload } from "./types";

const API_BASE = "/api/v1/";
const unsafeMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);
let csrfToken: string | null = null;
let sessionGeneration = 0;
let lastActivityAt = 0;
const activeControllers = new Set<AbortController>();
const authExpiryListeners = new Set<() => void>();

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields?: Record<string, string[]>;

  constructor(status: number, code: string, message: string, fields?: Record<string, string[]>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

export class StaleSessionError extends Error {
  constructor() {
    super("会话已切换，请重新加载当前页面");
    this.name = "StaleSessionError";
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "请求未完成，请检查网络后重试";
}

export function currentSessionGeneration(): number {
  return sessionGeneration;
}

export function subscribeToAuthExpiry(listener: () => void): () => void {
  authExpiryListeners.add(listener);
  return () => authExpiryListeners.delete(listener);
}

export function invalidateSessionRequests(): number {
  sessionGeneration += 1;
  for (const controller of activeControllers) controller.abort();
  activeControllers.clear();
  csrfToken = null;
  lastActivityAt = 0;
  return sessionGeneration;
}

export function clearPrivateSession(): number {
  const generation = invalidateSessionRequests();
  for (const listener of authExpiryListeners) listener();
  return generation;
}

function requestPath(path: string): string {
  if (/^(?:[a-z]+:)?\/\//i.test(path) || path.startsWith("/")) {
    throw new TypeError("API路径必须是相对 /api/v1/ 的路径");
  }
  return `${API_BASE}${path.replace(/^\/+/, "")}`;
}

function isJsonResponse(response: Response): boolean {
  return response.headers.get("content-type")?.includes("application/json") ?? false;
}

async function responseError(response: Response): Promise<ApiError> {
  let payload: Partial<ApiErrorPayload> = {};
  if (isJsonResponse(response)) {
    try {
      payload = (await response.json()) as Partial<ApiErrorPayload>;
    } catch {
      // Fall through to the generic status message.
    }
  }
  const error = payload.error;
  return new ApiError(
    response.status,
    error?.code ?? "request_failed",
    error?.message ?? `请求失败（${response.status}）`,
    error?.fields,
  );
}

export async function refreshCsrfToken(signal?: AbortSignal): Promise<string> {
  const generation = sessionGeneration;
  const controller = new AbortController();
  activeControllers.add(controller);
  const abortFromCaller = () => controller.abort();
  signal?.addEventListener("abort", abortFromCaller, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    const response = await fetch(`${API_BASE}auth/csrf/`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
    if (generation !== sessionGeneration) throw new StaleSessionError();
    if (!response.ok) throw await responseError(response);
    const payload = (await response.json()) as { csrf_token?: unknown };
    if (generation !== sessionGeneration) throw new StaleSessionError();
    if (typeof payload.csrf_token !== "string" || payload.csrf_token.length === 0) {
      throw new ApiError(response.status, "invalid_response", "无法取得安全验证令牌");
    }
    csrfToken = payload.csrf_token;
    return csrfToken;
  } catch (error) {
    if (generation !== sessionGeneration && !(error instanceof StaleSessionError)) {
      throw new StaleSessionError();
    }
    throw error;
  } finally {
    signal?.removeEventListener("abort", abortFromCaller);
    activeControllers.delete(controller);
  }
}

export async function currentCsrfToken(signal?: AbortSignal): Promise<string> {
  return csrfToken ?? refreshCsrfToken(signal);
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  const generation = sessionGeneration;
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  let body = options.body;

  if (body && typeof body === "object" && !(body instanceof FormData) && !(body instanceof Blob)) {
    body = JSON.stringify(body);
    if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  }
  if (unsafeMethods.has(method)) {
    if (!csrfToken) await refreshCsrfToken(signal);
    if (generation !== sessionGeneration) throw new StaleSessionError();
    headers.set("X-CSRFToken", csrfToken!);
  }

  const controller = new AbortController();
  activeControllers.add(controller);
  const abortFromCaller = () => controller.abort();
  signal?.addEventListener("abort", abortFromCaller, { once: true });
  if (signal?.aborted) controller.abort();
  const requestOptions: RequestInit = {
    ...options,
    method,
    headers,
    body,
    credentials: "same-origin",
    cache: "no-store",
    signal: controller.signal,
  };

  try {
    const response = await fetch(requestPath(path), requestOptions);
    if (generation !== sessionGeneration) throw new StaleSessionError();
    if (response.status === 401) {
      const error = await responseError(response);
      if (generation !== sessionGeneration) throw new StaleSessionError();
      clearPrivateSession();
      throw error;
    }
    if (!response.ok) throw await responseError(response);
    if (generation !== sessionGeneration) throw new StaleSessionError();
    if (response.status === 204) return undefined as T;
    const payload = (await response.json()) as T;
    if (generation !== sessionGeneration) throw new StaleSessionError();
    return payload;
  } catch (error) {
    if (
      generation !== sessionGeneration &&
      !(error instanceof StaleSessionError) &&
      !(error instanceof ApiError && error.status === 401)
    ) {
      throw new StaleSessionError();
    }
    throw error;
  } finally {
    signal?.removeEventListener("abort", abortFromCaller);
    activeControllers.delete(controller);
  }
}

export function recordUserActivity(): void {
  const now = Date.now();
  if (now - lastActivityAt < 60_000) return;
  lastActivityAt = now;
  void apiRequest<void>("auth/activity/", { method: "POST" }).catch(() => {
    // The server remains authoritative; the next protected request handles expiry.
  });
}
