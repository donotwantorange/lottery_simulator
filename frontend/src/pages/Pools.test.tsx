import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { makePoolDocument, makeRuleDocument } from "../test-fixtures";
import type { Pool, Rule } from "../api/types";
import { Pools } from "./Pools";

const { apiRequest, authUser, MockApiError } = vi.hoisted(() => {
  class MockApiError extends Error {
    constructor(readonly status: number, message: string, readonly code = "request_failed",
      readonly fields?: Record<string, unknown>) { super(message); }
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

function makeAlternativeRule(): Rule {
  const document = makeRuleDocument();
  document.id = "alternative-rule-id";
  document.name = "替代规则";
  document.big_pity.enabled = false;
  document.grant.enabled = false;
  return { ...rule, id: document.id, name: document.name, revision: 2, document };
}

function renderPools() {
  const router = createMemoryRouter([{ path: "*", element: <Pools /> }], { initialEntries: ["/pools"] });
  return render(<RouterProvider router={router} />);
}
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
  expect(screen.getByText("角色池详情")).toBeInTheDocument();
  expect(screen.queryByLabelText("角色池名称")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存修改" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "准备副本" }));
  expect(screen.getByText(/来源：.*修订 7/)).toBeInTheDocument();
  expect(apiRequest).not.toHaveBeenCalledWith(`pools/${pool.id}/copy/`, expect.anything());
  fireEvent.click(screen.getByRole("button", { name: "保存副本" }));
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

it("rechecks access after a denied save and shows an accessible pool read-only", async () => {
  Object.assign(authUser, { id: "user-b", role: "user" });
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("pools/?")) return Promise.resolve(poolPage);
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    if (path === `pools/${pool.id}/` && options?.method === "PATCH") return Promise.reject(new MockApiError(403, "无权修改"));
    if (path === `pools/${pool.id}/`) return Promise.resolve({ ...pool, owner_id: "user-c" });
    return Promise.resolve(pool);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  expect(await screen.findByText(/当前以只读方式显示/)).toBeInTheDocument();
  expect(screen.getByText("角色池详情")).toBeInTheDocument();
  expect(screen.queryByLabelText("角色池名称")).toBeNull();
  expect(apiRequest).toHaveBeenCalledWith(`pools/${pool.id}/`);
});

it("clears inaccessible details after a denied write and failed GET", async () => {
  Object.assign(authUser, { id: "user-b", role: "user" });
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("pools/?")) return Promise.resolve(poolPage);
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    if (path === `pools/${pool.id}/` && options?.method === "PATCH") return Promise.reject(new MockApiError(403, "无权修改"));
    if (path === `pools/${pool.id}/`) return Promise.reject(new MockApiError(404, "不存在"));
    return Promise.resolve(pool);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  expect(await screen.findByText(/详情已清除/)).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "编辑角色池" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "角色池详情" })).toBeNull();
});

it("points known server fields at stable inputs and gives unknown issues as business text", async () => {
  Object.assign(authUser, { id: "user-b", role: "user" });
  const rosterIndex = poolDocument.rarity_pools.findIndex((roster) => roster.characters.length > 0);
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("pools/?")) return Promise.resolve(poolPage);
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    if (path === `pools/${pool.id}/` && options?.method === "PATCH") return Promise.reject(new MockApiError(400, "校验失败", "invalid", {
      name: "名称不合法", rosters: { [rosterIndex]: { characters: { 0: { weight: "权重不合法" } } } }, other: "其他业务约束不满足",
    }));
    return Promise.resolve(pool);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  const nameIssue = await screen.findByRole("button", { name: /角色池名称：名称不合法/ });
  fireEvent.click(nameIssue);
  await waitFor(() => expect(screen.getByLabelText("角色池名称")).toHaveFocus());
  expect(screen.getByRole("button", { name: /的权重：权重不合法/ })).toBeInTheDocument();
  expect(screen.getByText(/其他业务约束不满足/)).toBeInTheDocument();
  expect(screen.queryByText(/rosters\.0/)).toBeNull();
  fireEvent.change(screen.getByLabelText("角色池名称"), { target: { value: "修正名称" } });
  expect(screen.queryByRole("button", { name: /角色池名称：名称不合法/ })).toBeNull();
  expect(screen.getByRole("button", { name: /的权重：权重不合法/ })).toBeInTheDocument();
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

it("creates from a missing default rule by selecting an available rule directly", async () => {
  const alternative = makeAlternativeRule();
  const emptyPage = { ...poolPage, items: [], total: 0 };
  const savedDocument = { ...poolDocument, id: "new-pool-document", name: "新角色池",
    rule_ref: { id: alternative.id, name: alternative.name }, rarity_pools: alternative.document.rarities.map((rarity) => ({
      rarity_id: rarity.id, characters: [], up_enabled: false, up_share: 0,
    })), rarity_labels: {}, rewards: [], mechanism_targets: {} };
  const saved: Pool = { ...pool, id: "new-pool-id", name: "新角色池", owner_id: "user-a", owner_name: "alice",
    rule_ref: { id: alternative.id, name: alternative.name, revision: alternative.revision }, document: savedDocument,
    revision: 1 };
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("pools/?")) return Promise.resolve(emptyPage);
    if (path.startsWith("rules/?")) return Promise.resolve({ ...rulePage, items: [alternative] });
    if (path === "pools/" && options?.method === "POST") return Promise.resolve(saved);
    return Promise.resolve(emptyPage);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "新建角色池" }));
  const binding = screen.getByLabelText("绑定规则");
  expect(binding).toHaveValue("");
  fireEvent.change(binding, { target: { value: alternative.id } });
  expect(screen.queryByRole("heading", { name: "确认切换规则" })).toBeNull();
  expect(screen.getAllByText("此档仍可抽出，但不记录具体角色。")).toHaveLength(alternative.document.rarities.length);
  fireEvent.click(screen.getByRole("button", { name: "创建角色池" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("pools/", expect.objectContaining({ method: "POST" })));
  const request = apiRequest.mock.calls.find(([path, options]) => path === "pools/" && options?.method === "POST");
  expect(JSON.parse(request?.[1]?.body as string)).toMatchObject({ rule_ref: { id: alternative.id, name: alternative.name },
    rarity_pools: alternative.document.rarities.map((rarity) => ({ rarity_id: rarity.id, characters: [], up_enabled: false, up_share: 0 })),
    rarity_labels: {}, rewards: [] });
});

it("guides a new pool toward rule setup when no rules are available", async () => {
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("pools/?")) return Promise.resolve({ ...poolPage, items: [], total: 0 });
    if (path.startsWith("rules/?")) return Promise.resolve({ ...rulePage, items: [], total: 0 });
    return Promise.resolve({ ...poolPage, items: [], total: 0 });
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "新建角色池" }));
  expect(await screen.findByText(/没有符合此池所有者、类型和可见性的可用规则/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "前往规则页查看或创建规则" })).toHaveAttribute("href", "/rules/");
  expect(screen.getByRole("button", { name: "创建角色池" })).toBeDisabled();
});

it("keeps the default rule template when it is available", async () => {
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("pools/?")) return Promise.resolve({ ...poolPage, items: [], total: 0 });
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    return Promise.resolve({ ...poolPage, items: [], total: 0 });
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "新建角色池" }));
  expect(screen.getByLabelText("绑定规则")).toHaveValue(rule.id);
  expect(screen.getAllByRole("button", { name: "删除" }).length).toBeGreaterThan(0);
});

it("initializes empty rosters when the default rule ID has changed rarity structure", async () => {
  const changedRule = structuredClone(rule);
  const added = { ...changedRule.document.rarities[0], id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    name: "新档", rank: changedRule.document.rarities.length };
  changedRule.document.rarities.push(added);
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("pools/?")) return Promise.resolve({ ...poolPage, items: [], total: 0 });
    if (path.startsWith("rules/?")) return Promise.resolve({ ...rulePage, items: [changedRule] });
    return Promise.resolve({ ...poolPage, items: [], total: 0 });
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "新建角色池" }));
  expect(screen.getByLabelText("绑定规则")).toHaveValue(changedRule.id);
  expect(screen.getByRole("heading", { name: "新档" })).toBeInTheDocument();
  expect(screen.getAllByText("此档仍可抽出，但不记录具体角色。")).toHaveLength(changedRule.document.rarities.length);
  expect(screen.getByText("没有配置奖励。")).toBeInTheDocument();
});

it("cancels copy preparation without creating a pool", async () => {
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("pools/?")) return Promise.resolve(poolPage);
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    return Promise.resolve(pool);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 复制" }));
  fireEvent.click(screen.getByRole("button", { name: "准备副本" }));
  expect(screen.getByRole("heading", { name: "准备复制已保存版本" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "取消复制" }));
  expect(screen.queryByRole("heading", { name: "准备复制已保存版本" })).toBeNull();
  expect(apiRequest.mock.calls.some(([path, options]) => path === `pools/${pool.id}/copy/` && options?.method === "POST")).toBe(false);
});

it("asks before abandoning a changed pool when starting a new one", async () => {
  Object.assign(authUser, { id: "user-b", role: "user" });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("pools/?")) return Promise.resolve(poolPage);
    if (path.startsWith("rules/?")) return Promise.resolve(rulePage);
    return Promise.resolve(pool);
  });
  renderPools();
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  fireEvent.change(screen.getByLabelText("角色池名称"), { target: { value: "尚未保存" } });
  fireEvent.click(screen.getByRole("button", { name: "新建角色池" }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("角色池名称")).toHaveValue("尚未保存");
  expect(screen.getByRole("heading", { name: "编辑角色池" })).toBeInTheDocument();
  confirm.mockRestore();
});
