import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { Pools } from "./Pools";

const { apiRequest, authUser, MockApiError } = vi.hoisted(() => {
  class MockApiError extends Error { constructor(readonly status: number, message: string) { super(message); } }
  return { apiRequest: vi.fn(), authUser: { id: "user-a", role: "user" }, MockApiError };
});
vi.mock("../api/client", () => ({ apiRequest, ApiError: MockApiError, errorMessage: (error: Error) => error.message }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: authUser, sessionGeneration: 1 }) }));

const pool = {
  id: "pool-1", name: "共有池", kind: "private", visibility: "public", owner_id: "user-a", owner_name: "alice",
  original_author: "初始作者", rule_name: "rule1", rarity_labels: { "4": "四星", "5": "五星", "6": "六星" },
  pool_config: { up_share: 0.5, five_star: { base_probability: 0.08, pity_enabled: true, hard_pity: 10 },
    six_star_characters: [], four_star_characters: [], five_star_characters: [], rewards: [] }, revision: 3, updated_at: "2026-09-01T00:00:00Z",
};

afterEach(() => { cleanup(); apiRequest.mockReset(); });

it("keeps another user's pool read-only and allows creating a copy", async () => {
  Object.assign(authUser, { id: "user-b", role: "user" });
  apiRequest.mockImplementation((path: string) => path.startsWith("pools/?")
    ? Promise.resolve({ items: [pool], total: 1, page: 1, page_size: 200 })
    : path === "pools/pool-1/copy/" ? Promise.resolve({ ...pool, id: "pool-copy", owner_id: "user-b", name: "共有池副本" })
      : Promise.resolve({}));
  render(<MemoryRouter><Pools /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "查看 / 复制" }));
  expect(screen.getByRole("heading", { name: "角色池详情" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存修改" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("角色池名称")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "复制" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("pools/pool-1/copy/", expect.objectContaining({ method: "POST" })));
  expect(screen.getByRole("heading", { name: "角色池详情" })).toBeInTheDocument();
});

it("preserves the edited pool name when the save returns a revision conflict", async () => {
  Object.assign(authUser, { id: "user-a", role: "user" });
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("pools/?")) return Promise.resolve({ items: [pool], total: 1, page: 1, page_size: 200 });
    if (path === "pools/pool-1/" && options?.method === "PATCH") return Promise.reject(new MockApiError(409, "角色池修订冲突"));
    return Promise.resolve({});
  });
  render(<MemoryRouter><Pools /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  const name = screen.getByLabelText("角色池名称");
  fireEvent.change(name, { target: { value: "尚未保存的草稿" } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("角色池修订冲突");
  expect(screen.getByLabelText("角色池名称")).toHaveValue("尚未保存的草稿");
  const save = apiRequest.mock.calls.find(([path, options]) => path === "pools/pool-1/" && options?.method === "PATCH");
  expect(JSON.parse(save?.[1]?.body as string)).toMatchObject({ name: "尚未保存的草稿", expected_revision: 3 });
});
