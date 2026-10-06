import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { makeRuleDocument } from "../test-fixtures";
import { Rules } from "./Rules";

const { apiRequest, authUser, MockApiError } = vi.hoisted(() => {
  class MockApiError extends Error {
    constructor(readonly status: number, message: string, readonly code = "request_failed") { super(message); }
  }
  return { apiRequest: vi.fn(), authUser: { id: "user-a", role: "user" }, MockApiError };
});
vi.mock("../api/client", () => ({ apiRequest, ApiError: MockApiError, errorMessage: (error: Error) => error.message }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: authUser, sessionGeneration: 1 }) }));

const document = makeRuleDocument();
document.original_author = "原始作者";
const rule = {
  id: document.id, name: document.name, original_author: "原始作者", algorithm: document.algorithm,
  kind: "private" as const, visibility: "public" as const, owner_id: "user-b", owner_name: "bob",
  revision: 3, reference_count: 1, structure_locked: true, document,
};
const page = { items: [rule], total: 60, page: 1, page_size: 50 };

afterEach(() => { cleanup(); apiRequest.mockReset(); Object.assign(authUser, { id: "user-a", role: "user" }); });

it("shows the original author and keeps another user's public rule read-only", async () => {
  const copied = { ...rule, id: "copied-rule", owner_id: "user-a", owner_name: "alice" };
  apiRequest.mockImplementation((path: string, options?: RequestInit) =>
    path.startsWith("rules/?") ? Promise.resolve(page) : path === `rules/${rule.id}/copy/` && options?.method === "POST"
      ? Promise.resolve(copied) : Promise.resolve(rule));
  render(<MemoryRouter><Rules /></MemoryRouter>);

  expect(await screen.findByRole("cell", { name: "原始作者" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查看" }));
  expect(screen.getByRole("heading", { name: "规则详情" })).toBeInTheDocument();
  expect(screen.getByLabelText("规则名称")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "保存修改" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制规则" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(`rules/${rule.id}/copy/`, expect.objectContaining({ method: "POST" })));
  const copyRequest = apiRequest.mock.calls.find(([path]) => path === `rules/${rule.id}/copy/`);
  expect(JSON.parse(copyRequest?.[1]?.body as string)).toEqual({ name: `${rule.name}副本`, kind: "private" });
  expect(await screen.findByText(/最初作者：原始作者/)).toBeInTheDocument();
  expect(await screen.findByText("规则已复制；最初作者署名已保留。")).toBeInTheDocument();
});

it("requests each scope and page from the server", async () => {
  apiRequest.mockResolvedValue(page);
  render(<MemoryRouter><Rules /></MemoryRouter>);
  await screen.findByText("第 1 / 2 页 · 共 60 条");
  fireEvent.change(screen.getByLabelText("筛选"), { target: { value: "mine" } });
  await waitFor(() => expect(apiRequest).toHaveBeenLastCalledWith("rules/?scope=mine&page=1&page_size=50", {}, expect.any(AbortSignal)));
  await waitFor(() => expect(screen.getByRole("button", { name: "下一页" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  await waitFor(() => expect(apiRequest).toHaveBeenLastCalledWith("rules/?scope=mine&page=2&page_size=50", {}, expect.any(AbortSignal)));
});

it("places one basic-information heading before its fields in read-only view", async () => {
  apiRequest.mockResolvedValue(page);
  render(<MemoryRouter><Rules /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "查看" }));
  const heading = screen.getByRole("heading", { name: "基本信息与权限" });
  const name = screen.getByLabelText("规则名称");
  expect(heading.compareDocumentPosition(name) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getAllByRole("heading", { name: "基本信息与权限" })).toHaveLength(1);
  expect(screen.getByText(/公开后，其他用户可查看、绑定和复制，但不能编辑/)).toBeInTheDocument();
});

it("shows private rule creation to users and public creation to admins", async () => {
  apiRequest.mockResolvedValue({ ...page, items: [] });
  const userView = render(<MemoryRouter><Rules /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "新建规则" }));
  const heading = screen.getByRole("heading", { name: "基本信息与权限" });
  expect(heading.compareDocumentPosition(screen.getByLabelText("规则名称")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByLabelText("规则类型").querySelector('option[value="public"]')).toBeNull();
  userView.unmount();
  cleanup();
  Object.assign(authUser, { id: "admin", role: "admin" });
  apiRequest.mockReset();
  apiRequest.mockResolvedValue({ ...page, items: [] });
  render(<MemoryRouter><Rules /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "新建规则" }));
  expect(screen.getByLabelText("规则类型").querySelector('option[value="public"]')).toBeInTheDocument();
});

it("keeps the local draft after a revision conflict", async () => {
  Object.assign(authUser, { id: "user-b", role: "user" });
  apiRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("rules/?")) return Promise.resolve(page);
    if (path === `rules/${rule.id}/` && options?.method === "PATCH") {
      return Promise.reject(new MockApiError(409, "规则修订冲突", "revision_conflict"));
    }
    if (path === `rules/${rule.id}/`) return Promise.resolve(rule);
    return Promise.resolve(rule);
  });
  render(<MemoryRouter><Rules /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  expect(screen.getByRole("heading", { name: "基本信息与权限" }).compareDocumentPosition(screen.getByLabelText("规则名称")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.change(screen.getByLabelText("规则名称"), { target: { value: "保留的本地草稿" } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("草稿仍保留");
  expect(screen.getByLabelText("规则名称")).toHaveValue("保留的本地草稿");
  expect(screen.getByRole("button", { name: "重新加载最新版本" })).toBeInTheDocument();
});

it("previews import before confirming and resends the untouched file JSON", async () => {
  const raw = JSON.stringify(document).replace(/"hard_pity":\d+/, '"hard_pity":9007199254740993');
  const imported = { ...rule, id: "rule-imported", name: "导入规则", document: { ...document, name: "导入规则" } };
  apiRequest.mockImplementation((path: string) => {
    if (path.startsWith("rules/?")) return Promise.resolve({ ...page, total: 0, items: [] });
    if (path === "rules/import/preview/") return Promise.resolve({ document });
    if (path === "rules/import/confirm/") return Promise.resolve(imported);
    return Promise.resolve(imported);
  });
  render(<MemoryRouter><Rules /></MemoryRouter>);
  const file = new File([raw], "rule.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: async () => raw });
  const upload = await screen.findByLabelText("导入规则JSON");
  await waitFor(() => expect(upload).toBeEnabled());
  fireEvent.change(upload, { target: { files: [file] } });
  expect(await screen.findByRole("heading", { name: "确认导入规则" })).toBeInTheDocument();
  expect(apiRequest).not.toHaveBeenCalledWith("rules/import/confirm/", expect.anything());
  fireEvent.click(screen.getByRole("button", { name: "确认导入" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("rules/import/confirm/", expect.objectContaining({
    method: "POST", body: `{"document":${raw}}`,
  })));
});
