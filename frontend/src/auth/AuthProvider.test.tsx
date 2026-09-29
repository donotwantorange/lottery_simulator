import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";
import { invalidateSessionRequests } from "../api/client";

function SessionActions() {
  const { user, login, logout, logoutPending } = useAuth();
  return (
    <>
      <output data-testid="user">{user?.username ?? "anonymous"}</output>
      {user && <output data-testid="private-data">资源-{user.id}</output>}
      <output data-testid="logout-pending">{String(logoutPending)}</output>
      <button onClick={() => void logout().catch(() => undefined)}>退出</button>
      <button onClick={() => void login("user-b", "password").catch(() => undefined)}>尝试切换账号</button>
    </>
  );
}

describe("AuthProvider request lifecycle", () => {
  beforeEach(() => invalidateSessionRequests());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("aborts session lookup when the provider unmounts", async () => {
    let lookupSignal: AbortSignal | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      if (String(input).endsWith("auth/csrf/")) {
        return new Response(JSON.stringify({ csrf_token: "csrf" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      lookupSignal = init?.signal ?? undefined;
      return new Promise<Response>((_resolve, reject) => {
        lookupSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const view = render(<AuthProvider><span>应用</span></AuthProvider>);
    await waitFor(() => expect(lookupSignal).toBeDefined());
    view.unmount();

    expect(lookupSignal?.aborted).toBe(true);
  });

  it("blocks a new login until the logout POST finishes", async () => {
    let finishLogout!: (response: Response) => void;
    const loginRequests: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url.endsWith("auth/csrf/")) {
        return new Response(JSON.stringify({ csrf_token: "csrf" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("auth/me/")) {
        return new Response(JSON.stringify({ id: "user-a", username: "user-a", role: "user", must_change_password: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("auth/logout/")) {
        return new Promise<Response>((resolve) => { finishLogout = resolve; });
      }
      if (url.endsWith("auth/login/")) loginRequests.push(url);
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthProvider><SessionActions /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("user-a"));

    fireEvent.click(screen.getByRole("button", { name: "退出" }));
    await waitFor(() => expect(screen.getByTestId("logout-pending")).toHaveTextContent("true"));
    fireEvent.click(screen.getByRole("button", { name: "尝试切换账号" }));
    expect(loginRequests).toHaveLength(0);

    await act(async () => {
      finishLogout(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    await waitFor(() => expect(screen.getByTestId("logout-pending")).toHaveTextContent("false"));
  });

  it("does not let a delayed account lookup replace the account logged in after logout", async () => {
    let finishAccountALookup!: (response: Response) => void;
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url.endsWith("auth/csrf/")) {
        return new Response(JSON.stringify({ csrf_token: "csrf" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("auth/me/")) {
        return new Promise<Response>((resolve) => { finishAccountALookup = resolve; });
      }
      if (url.endsWith("auth/logout/")) {
        return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("auth/login/")) {
        return new Response(JSON.stringify({ id: "user-b", username: "user-b", role: "user", must_change_password: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AuthProvider><SessionActions /></AuthProvider>);
    await waitFor(() => expect(finishAccountALookup).toBeDefined());

    fireEvent.click(screen.getByRole("button", { name: "退出" }));
    await waitFor(() => expect(screen.getByTestId("logout-pending")).toHaveTextContent("false"));
    fireEvent.click(screen.getByRole("button", { name: "尝试切换账号" }));
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("user-b"));

    await act(async () => {
      finishAccountALookup(new Response(JSON.stringify({ id: "user-a", username: "user-a", role: "user", must_change_password: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    });

    expect(screen.getByTestId("user")).toHaveTextContent("user-b");
    expect(screen.getByTestId("private-data")).toHaveTextContent("资源-user-b");
    expect(screen.queryByText("资源-user-a")).not.toBeInTheDocument();
  });
});
