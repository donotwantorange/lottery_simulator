import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { makePoolDocument, makeRuleDocument } from "../test-fixtures";
import type { Pool, Rule } from "../api/types";
import { Pools } from "./Pools";

const { apiRequest, authUser, MockApiError } = vi.hoisted(() => {
  class MockApiError extends Error {
    constructor(readonly status: number, message: string, readonly code = "request_failed") { super(message); }
  }
  return { apiRequest: vi.fn(), authUser: { id: "user-a", role: "user" }, MockApiError };
});
vi.mock("../api/client", () => ({ apiRequest, ApiError: MockApiError, errorMessage: (error: Error) => error.message }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: authUser, sessionGeneration: 1 }) }));

const ruleDocument = makeRuleDocument();
const rule: Rule = { id: ruleDocument.id, name: "zmd", original_author: "原作者", algorithm: ruleDocument.algorithm,
  kind: "public", visibility: "public", owner_id: null, owner_name: null, revision: 4,
  reference_count: 1, structure_locked: true, document: ruleDocument };
const poolDocument = makePoolDocument();
const pool: Pool = { id: poolDocument.id, name: poolDocument.name, kind: "private", visibility: "public",
  owner_id: "user-b", owner_name: "bob", original_author: "原始作者",
  rule_ref: { id: rule.id, name: rule.name, revision: rule.revision }, document: poolDocument,
  revision: 7, updated_at: "2026-10-01T00:00:00Z" };
const poolPage = { items: [pool], total: 1, page: 1, page_size: 200 };
const rulePage = { items: [rule], total: 1, page: 1, page_size: 200 };

function renderPools() { return render(<MemoryRouter><Pools /></MemoryRouter>); }
afterEach(() => { cleanup(); apiRequest.mockReset(); Object.assign(authUser, { id: "user-a", role: "user" }); });

it("keeps another user's pool read-only while allowing a permission-checked copy", async () => {
  const copied: Pool = { ...pool, id: "pool-copy", name: "复制池", owner_id: "user-a", owner_name: "alice", revision: 1 };
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("pools/?")) return Promise.resolve(poolPage);
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    if (path === `pools/${pool.id}/copy/` && options?.method === "POST") return Promise.resolve(copied);
    return Promise.resolve(copied);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 复制" }));
  expect(screen.getByLabelText("角色池名称")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "保存修改" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制为新池" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(`pools/${pool.id}/copy/`, expect.objectContaining({ method: "POST" })));
  const request = apiRequest.mock.calls.find(([path]) => path === `pools/${pool.id}/copy/`);
  expect(JSON.parse(request?.[1]?.body as string)).toMatchObject({ expected_revision: 7,
    expected_source_rule_revision: 4, expected_rule_revision: 4,
    rule_ref: { id: rule.id, name: rule.name }, name: `${pool.name}副本`, kind: "private" });
});

it("saves a pool against both the pool and rule revisions", async () => {
  Object.assign(authUser, { id: "user-b", role: "user" });
  const saved = { ...pool, document: { ...poolDocument, name: "已修改池" }, name: "已修改池", revision: 8 };
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("pools/?")) return Promise.resolve(poolPage);
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    if (path === `pools/${pool.id}/` && options?.method === "PATCH") return Promise.resolve(saved);
    return Promise.resolve(saved);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  fireEvent.change(screen.getByLabelText("角色池名称"), { target: { value: "已修改池" } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(`pools/${pool.id}/`, expect.objectContaining({ method: "PATCH" })));
  const request = apiRequest.mock.calls.find(([path, options]) => path === `pools/${pool.id}/` && options?.method === "PATCH");
  expect(JSON.parse(request?.[1]?.body as string)).toMatchObject({ expected_revision: 7, expected_rule_revision: 4,
    name: "已修改池", rule_ref: { id: rule.id, name: rule.name } });
});

it("retains the pool draft and revision contract after a save conflict", async () => {
  Object.assign(authUser, { id: "user-b", role: "user" });
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("pools/?")) return Promise.resolve(poolPage);
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    if (path === `pools/${pool.id}/` && options?.method === "PATCH") {
      return Promise.reject(new MockApiError(409, "池或规则修订冲突", "revision_conflict"));
    }
    return Promise.resolve(pool);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  fireEvent.change(screen.getByLabelText("角色池名称"), { target: { value: "保留池草稿" } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("草稿仍保留");
  expect(screen.getByLabelText("角色池名称")).toHaveValue("保留池草稿");
  const request = apiRequest.mock.calls.find(([path, options]) => path === `pools/${pool.id}/` && options?.method === "PATCH");
  expect(JSON.parse(request?.[1]?.body as string)).toMatchObject({ expected_revision: 7, expected_rule_revision: 4 });
});

it("previews then confirms imports without parsing large integers in JavaScript", async () => {
  const [rarityId, amount] = Object.entries(poolDocument.rewards[0].amounts)[0];
  const raw = JSON.stringify(poolDocument).replace(`"${rarityId}":${amount}`, `"${rarityId}":9007199254740993`);
  const preview = { document: poolDocument, resolution: { status: "matched", rule: { id: rule.id, name: rule.name, revision: rule.revision } } };
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("pools/?")) return Promise.resolve({ ...poolPage, items: [], total: 0 });
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    if (path === "pools/import/preview/") return Promise.resolve(preview);
    if (path === "pools/import/confirm/") return Promise.resolve(pool);
    return Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 });
  });
  renderPools();
  const input = await screen.findByLabelText("导入池JSON");
  await waitFor(() => expect(input).toBeEnabled());
  const file = new File([raw], "pool.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: async () => raw });
  fireEvent.change(input, { target: { files: [file] } });
  expect(await screen.findByRole("heading", { name: "确认导入角色池" })).toBeInTheDocument();
  expect(apiRequest).not.toHaveBeenCalledWith("pools/import/confirm/", expect.anything());
  fireEvent.click(screen.getByRole("button", { name: "确认导入" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("pools/import/confirm/", expect.objectContaining({
    method: "POST", body: `{"document":${raw},"rule_id":"${rule.id}","rule_revision":${rule.revision}}`,
  })));
});
