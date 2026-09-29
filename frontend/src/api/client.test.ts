import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  StaleSessionError,
  apiRequest,
  currentSessionGeneration,
  invalidateSessionRequests,
  refreshCsrfToken,
  subscribeToAuthExpiry,
} from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("API client session boundaries", () => {
  beforeEach(() => {
    invalidateSessionRequests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("gets a CSRF token and sends it with a same-origin login POST", async () => {
    const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push([input, init]);
      return String(input).endsWith("auth/csrf/")
        ? jsonResponse(200, { csrf_token: "csrf-one" })
        : jsonResponse(200, { id: "u-1" });
    }));

    await apiRequest("auth/login/", { method: "POST", body: JSON.stringify({ username: "a", password: "secret" }) });

    expect(calls.map(([url]) => String(url))).toEqual(["/api/v1/auth/csrf/", "/api/v1/auth/login/"]);
    expect(new Headers(calls[1][1]?.headers).get("X-CSRFToken")).toBe("csrf-one");
    expect(calls[1][1]?.credentials).toBe("same-origin");
  });

  it("keeps 403 as an error without clearing session state, and preserves 401 detail while clearing it", async () => {
    const expired = vi.fn();
    const unsubscribe = subscribeToAuthExpiry(expired);
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(jsonResponse(403, { error: { code: "forbidden", message: "禁止访问" } }))
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: "unauthenticated", message: "请重新登录" } })));

    await expect(apiRequest("pools/")).rejects.toMatchObject({ status: 403, message: "禁止访问" });
    expect(expired).not.toHaveBeenCalled();
    await expect(apiRequest("auth/me/")).rejects.toMatchObject({ status: 401, message: "请重新登录" });
    expect(expired).toHaveBeenCalledOnce();
    unsubscribe();
  });

  it("discards an older account response and a late CSRF response after session change", async () => {
    let finishRequest!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finishRequest = resolve; })));
    const pending = apiRequest<{ owner: string }>("runs/");
    invalidateSessionRequests();
    finishRequest(jsonResponse(200, { owner: "account-a" }));
    await expect(pending).rejects.toBeInstanceOf(StaleSessionError);

    let finishCsrf!: (response: Response) => void;
    let csrfSignal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve) => {
      finishCsrf = resolve;
      csrfSignal = init?.signal ?? undefined;
    })));
    const csrf = refreshCsrfToken();
    invalidateSessionRequests();
    expect(csrfSignal?.aborted).toBe(true);
    finishCsrf(jsonResponse(200, { csrf_token: "old-account-token" }));
    await expect(csrf).rejects.toBeInstanceOf(StaleSessionError);
  });

  it("does not let an old delayed 401 body clear the session after a new login", async () => {
    let finishBody!: (value: unknown) => void;
    let bodyStarted!: () => void;
    const bodyParsing = new Promise<void>((resolve) => { bodyStarted = resolve; });
    const response = jsonResponse(401, {});
    vi.spyOn(response, "json").mockImplementation(() => {
      bodyStarted();
      return new Promise((resolve) => { finishBody = resolve; });
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const expired = vi.fn();
    const unsubscribe = subscribeToAuthExpiry(expired);

    const oldRequest = apiRequest("auth/me/");
    await bodyParsing;
    invalidateSessionRequests();
    const accountBGeneration = currentSessionGeneration();
    finishBody({ error: { code: "unauthenticated", message: "A已退出" } });

    await expect(oldRequest).rejects.toBeInstanceOf(StaleSessionError);
    expect(currentSessionGeneration()).toBe(accountBGeneration);
    expect(expired).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("propagates caller abort to the tracked CSRF request", async () => {
    let csrfSignal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      csrfSignal = init?.signal ?? undefined;
      return new Promise<Response>((_resolve, reject) => {
        csrfSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      });
    }));
    const caller = new AbortController();
    const csrf = refreshCsrfToken(caller.signal);
    caller.abort();

    expect(csrfSignal?.aborted).toBe(true);
    await expect(csrf).rejects.toMatchObject({ name: "AbortError" });
  });
});
