import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Management } from "./Management";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("../api/client", () => ({
  apiRequest,
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "请求失败",
}));
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "admin-id", role: "admin", username: "root" }, sessionGeneration: 1 }),
}));

describe("Management", () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  beforeEach(() => {
    apiRequest.mockImplementation((path: string) => {
      if (path.startsWith("management/users/?")) return Promise.resolve({ items: [
        { id: "admin-id", username: "root", role: "admin", enabled: true, deleting: false, must_change_password: false },
        { id: "user-id", username: "alice", role: "user", enabled: false, deleting: false, must_change_password: false },
        { id: "user-2-id", username: "bob", role: "user", enabled: true, deleting: false, must_change_password: false },
      ], total: 3, page: 1, page_size: 50 });
      if (path.startsWith("experiment-configs/?")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 });
      if (path.startsWith("management/jobs/?")) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 });
      if (path === "management/users/user-id/" || path === "management/users/user-2-id/") return Promise.resolve({
        delete_impact: { private_pools: "1", experiment_configs: "0", runs: "0", job_directories: "0", export_files: "0", other_users_pool_references: "0", public_pools_preserved: "1" },
      });
      return Promise.resolve(undefined);
    });
  });

  it("renders all three management sections and only sends allowed account fields", async () => {
    render(<MemoryRouter><Management /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "账号管理" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "实验配置管理" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "任务管理" })).toBeInTheDocument();
    const row = await screen.findByRole("row", { name: /alice/ });
    fireEvent.click(row.querySelector("button")!);
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "alice2" } });
    fireEvent.click(screen.getByRole("button", { name: "保存账号" }));
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("management/users/user-id/", expect.objectContaining({
      method: "PATCH", body: JSON.stringify({ username: "alice2", role: "user", enabled: false }),
    })));
    const body = JSON.parse(apiRequest.mock.calls.find(([path, options]) => path === "management/users/user-id/" && options?.method === "PATCH")![1].body);
    expect(Object.keys(body).sort()).toEqual(["enabled", "role", "username"]);
  });

  it("does not carry Alice's deletion confirmation over to Bob", async () => {
    render(<MemoryRouter><Management /></MemoryRouter>);
    const alice = await screen.findByRole("row", { name: /alice/ });
    fireEvent.click(alice.querySelector("button.danger-button")!);
    await screen.findByText(/私有角色池（含公开的私有池）/);
    fireEvent.click(screen.getByLabelText(/我已核对范围/));
    expect(screen.getByRole("button", { name: "确认删除" })).toBeEnabled();

    const bob = screen.getAllByRole("row").find((row) => row.textContent?.includes("bob"))!;
    fireEvent.click(bob.querySelector("button.danger-button")!);
    expect(screen.getByRole("heading", { name: /删除账号“bob”/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认删除" })).toBeDisabled();
    expect(apiRequest.mock.calls.some(([path, options]) => path === "management/users/user-2-id/" && options?.method === "DELETE")).toBe(false);
  });
});
