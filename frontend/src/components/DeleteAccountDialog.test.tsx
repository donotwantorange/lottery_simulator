import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeleteAccountDialog } from "./DeleteAccountDialog";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("../api/client", () => ({
  apiRequest,
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "请求失败",
}));

describe("DeleteAccountDialog", () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("waits for the deletion preview and explicit confirmation before deleting", async () => {
    let resolvePreview!: (value: unknown) => void;
    apiRequest.mockImplementation((path: string) => path === "management/users/user-id/"
      ? new Promise((resolve) => { resolvePreview = resolve; })
      : Promise.resolve(undefined));
    const account = { id: "user-id", username: "alice", role: "user" as const, enabled: true, deleting: false, must_change_password: false };
    render(<DeleteAccountDialog account={account} onClose={() => undefined} onDeleted={() => undefined} />);

    const confirm = screen.getByRole("button", { name: "确认删除" });
    expect(confirm).toBeDisabled();
    expect(apiRequest.mock.calls.map(([path]) => path)).toEqual(["management/users/user-id/"]);
    resolvePreview({ delete_impact: { private_pools: "1", experiment_configs: "0", runs: "0", job_directories: "0", export_files: "0", other_users_pool_references: "0", public_pools_preserved: "1" } });
    await screen.findByText(/私有角色池（含公开的私有池）/);
    expect(confirm).toBeDisabled();

    fireEvent.click(screen.getByLabelText(/我已核对范围/));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("management/users/user-id/", expect.objectContaining({
      method: "DELETE", body: JSON.stringify({ confirm: true }),
    })));
  });

  it("clears old preview and confirmation when the account prop changes", async () => {
    let resolveNextPreview!: (value: unknown) => void;
    apiRequest.mockImplementation((path: string, options?: RequestInit) => {
      if (options?.method === "DELETE") return Promise.resolve(undefined);
      if (path === "management/users/user-id/") return Promise.resolve({
        delete_impact: { private_pools: "1", experiment_configs: "0", runs: "0", job_directories: "0", export_files: "0", other_users_pool_references: "0", public_pools_preserved: "1" },
      });
      return new Promise((resolve) => { resolveNextPreview = resolve; });
    });
    const baseAccount = { role: "user" as const, enabled: true, deleting: false, must_change_password: false };
    const onClose = () => undefined;
    const onDeleted = () => undefined;
    const view = render(<DeleteAccountDialog account={{ ...baseAccount, id: "user-id", username: "alice" }} onClose={onClose} onDeleted={onDeleted} />);
    await screen.findByText(/私有角色池（含公开的私有池）/);
    fireEvent.click(screen.getByLabelText(/我已核对范围/));

    view.rerender(<DeleteAccountDialog account={{ ...baseAccount, id: "user-2-id", username: "bob" }} onClose={onClose} onDeleted={onDeleted} />);
    const confirm = screen.getByRole("button", { name: "确认删除" });
    expect(confirm).toBeDisabled();
    expect(screen.getByText("正在读取删除范围…")).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledWith("management/users/user-2-id/", {}, expect.anything());
    expect(apiRequest.mock.calls.some(([path, options]) => path === "management/users/user-2-id/" && options?.method === "DELETE")).toBe(false);

    resolveNextPreview({ delete_impact: { private_pools: "2", experiment_configs: "0", runs: "0", job_directories: "0", export_files: "0", other_users_pool_references: "0", public_pools_preserved: "1" } });
    await screen.findByText("2");
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/我已核对范围/));
    fireEvent.click(confirm);
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("management/users/user-2-id/", expect.objectContaining({
      method: "DELETE", body: JSON.stringify({ confirm: true }),
    })));
  });
});
